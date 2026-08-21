"""
ComfyUI Custom Node: Video Save Plus (Custom Path)

Saves a video (MP4, H.264/H.265 + AAC) with its generated audio to any folder,
plus a workflow PNG (first frame with embedded workflow), optional prompt .txt
and optional first/last/all frames.

Buttons on the node (session-bound, pure file operations):
- Reveal in file manager
- Open video (system player, with sound)
- Save Training File (copy the whole set to a folder)
- Save Last Frame (from memory, no re-render)
- Delete Last Generation (with confirmation)

No torchaudio needed: audio is piped to ffmpeg as raw float32 PCM,
frames are piped as raw RGB24. Nothing is written to temp files except
the audio buffer.
"""

import os
import re
import sys
import json
import shutil
import platform
import subprocess
import tempfile
import threading
from datetime import datetime
from fractions import Fraction
from typing import Optional

import numpy as np
import torch
from PIL import Image
from PIL.PngImagePlugin import PngInfo

import folder_paths

__version__ = "2.0.1"

LOG = "[VideoSavePlus]"

# --------------------------------------------------------------------------- #
# Session registry: node_id -> info about the last generation of that node.
# The API routes only ever operate on paths stored here, never on arbitrary
# paths coming from the browser.
# --------------------------------------------------------------------------- #
_SESSION: dict[str, dict] = {}
_SESSION_LOCK = threading.Lock()

FIRST_SUFFIX = "_first Frame"
LAST_SUFFIX = "_last Frame"

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
           "medium", "slow", "slower", "veryslow"]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _find_ffmpeg() -> str:
    ff = shutil.which("ffmpeg")
    if ff:
        return ff
    try:
        import imageio_ffmpeg  # often present in ComfyUI envs
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    base = os.path.dirname(sys.executable)
    for c in (os.path.join(base, exe),
              os.path.join(base, "Scripts", exe),
              os.path.join(base, "..", exe)):
        if os.path.isfile(c):
            return os.path.abspath(c)
    raise FileNotFoundError(
        f"{LOG} ffmpeg not found. Install ffmpeg and make sure it is on the "
        f"system PATH (or pip install imageio-ffmpeg)."
    )


def _apply_template(prefix: str, seed: Optional[int]) -> str:
    """%date%, %time%, %seed%, and ComfyUI-style %date:yyyy-MM-dd%."""
    now = datetime.now()

    def date_repl(m):
        fmt = m.group(1)
        for k, v in (("yyyy", "%Y"), ("yy", "%y"), ("MM", "%m"), ("dd", "%d"),
                     ("hh", "%H"), ("mm", "%M"), ("ss", "%S")):
            fmt = fmt.replace(k, v)
        return now.strftime(fmt)

    s = re.sub(r"%date:([^%]+)%", date_repl, prefix)
    s = s.replace("%date%", now.strftime("%Y-%m-%d"))
    s = s.replace("%time%", now.strftime("%H%M%S"))
    s = s.replace("%seed%", str(seed) if seed is not None else "noseed")
    return s


def _sanitize_name(name: str) -> str:
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).strip().rstrip(".")
    return name or "video"


def _resolve_output_dir(custom_path: str) -> str:
    if not custom_path or not custom_path.strip():
        return folder_paths.get_output_directory()
    return os.path.abspath(os.path.expanduser(custom_path.strip()))


def _next_basename(directory: str, name: str) -> str:
    """name_00001, continuing the highest existing counter in the folder."""
    pat = re.compile(re.escape(name) + r"_(\d{5})(?:[._]|$)")
    max_n = 0
    if os.path.isdir(directory):
        for f in os.listdir(directory):
            m = pat.match(f)
            if m:
                max_n = max(max_n, int(m.group(1)))
    n = max_n + 1
    while True:
        base = f"{name}_{n:05d}"
        if not os.path.exists(os.path.join(directory, base + ".mp4")):
            return base
        n += 1


def _tensor_frame_to_uint8(frame: torch.Tensor) -> np.ndarray:
    """(H, W, C) float tensor -> (H, W, 3) uint8 numpy."""
    arr = frame.detach().to(torch.float32).cpu().numpy()
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.shape[2] == 1:
        arr = np.repeat(arr, 3, axis=2)
    elif arr.shape[2] > 3:
        arr = arr[:, :, :3]
    return (arr * 255.0).clip(0, 255).astype(np.uint8)


def _save_image(arr: np.ndarray, path: str, fmt: str, quality: int,
                png_compression: int, pnginfo: Optional[PngInfo] = None):
    img = Image.fromarray(arr)
    if fmt == "jpg":
        img.save(path, format="JPEG", quality=int(quality), subsampling=0,
                 optimize=True)
    else:
        img.save(path, format="PNG", compress_level=int(png_compression),
                 pnginfo=pnginfo)


def _prepare_audio(audio: dict):
    """Returns (raw_f32le_bytes, sample_rate, channels, seconds) or None if
    the audio is empty. Raises on malformed input (we never fail silently)."""
    if not isinstance(audio, dict):
        raise ValueError("AUDIO input is not a dict with waveform/sample_rate.")
    wf = audio.get("waveform")
    sr = audio.get("sample_rate")
    if wf is None or sr is None:
        raise ValueError("AUDIO input is missing 'waveform' or 'sample_rate'.")
    if isinstance(sr, torch.Tensor):
        sr = int(sr.flatten()[0].item())
    sr = int(sr)
    if sr <= 0:
        raise ValueError(f"Invalid sample rate: {sr}")

    wf = wf.detach()
    if wf.dim() == 3:
        wf = wf[0]
    elif wf.dim() == 1:
        wf = wf.unsqueeze(0)
    elif wf.dim() != 2:
        raise ValueError(f"Unexpected waveform shape {tuple(wf.shape)}")

    # Heuristic: (samples, channels) instead of (channels, samples)
    if wf.shape[0] > 16 and wf.shape[0] > wf.shape[1]:
        wf = wf.transpose(0, 1)

    wf = wf.to(torch.float32).cpu().clamp(-1.0, 1.0)
    channels, n = wf.shape
    if n == 0:
        return None
    data = wf.transpose(0, 1).contiguous().numpy().astype("<f4").tobytes()
    return data, sr, channels, n / sr


def _components_from_video(video):
    """Extract (images, audio, frame_rate) from a ComfyUI VIDEO object."""
    if hasattr(video, "get_components"):
        comp = video.get_components()
        images = getattr(comp, "images", None)
        audio = getattr(comp, "audio", None)
        fr = getattr(comp, "frame_rate", None)
        if isinstance(fr, Fraction):
            fr = float(fr)
        return images, audio, (float(fr) if fr else None)
    if isinstance(video, dict):  # very old style
        return video.get("images"), video.get("audio"), video.get("frame_rate")
    raise TypeError(f"Unsupported VIDEO object: {type(video)}")


def _open_in_file_manager(path: str):
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif system == "Darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def _open_with_default_app(path: str):
    system = platform.system()
    if system == "Windows":
        os.startfile(path)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


# --------------------------------------------------------------------------- #
# The node
# --------------------------------------------------------------------------- #
class VideoSavePlus:
    CATEGORY = "video/custom"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    OUTPUT_NODE = True
    DESCRIPTION = ("Saves MP4 with audio + workflow PNG to any folder. "
                   "Buttons: reveal, open, training copy, last frame, delete.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "filename_prefix": ("STRING", {
                    "default": "video",
                    "tooltip": "Base filename. May contain subfolders (scene1/take) and "
                               "placeholders: %date% (2026-08-21), %time% (143012), "
                               "%seed% (from the seed input), %date:yyyy-MM-dd hh-mm-ss%. "
                               "A 5-digit counter (_00001) is always appended.",
                }),
                "custom_output_path": ("STRING", {
                    "default": "",
                    "placeholder": r"e.g. O:\Projects\Videos  (empty = ComfyUI output)",
                    "tooltip": "Any folder on any drive. Created if missing. "
                               "Empty = ComfyUI's default output folder.",
                }),
                "frame_rate": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 120.0, "step": 0.01,
                    "tooltip": "Only used for the 'images' input. With a VIDEO input the "
                               "video's own frame rate is used automatically.",
                }),
                "video_codec": (["h264", "h265"], {
                    "default": "h264",
                    "tooltip": "h264 = plays everywhere (Windows, web, phones). "
                               "h265 = ~40% smaller at the same quality but not every "
                               "player/browser supports it.",
                }),
                "crf": ("INT", {
                    "default": 19, "min": 0, "max": 51, "step": 1,
                    "tooltip": "Constant quality. Lower = better and larger. "
                               "0 = lossless, 17-19 = visually lossless, 23 = ffmpeg "
                               "default, 28 = small. Main quality control.",
                }),
                "preset": (PRESETS, {
                    "default": "medium",
                    "tooltip": "Encoding speed vs. file size at the SAME quality (CRF). "
                               "Does not change picture quality. Slower = smaller file, "
                               "longer encode.",
                }),
                "pixel_format": (["yuv420p", "yuv444p"], {
                    "default": "yuv420p",
                    "tooltip": "yuv420p = maximum compatibility (standard). "
                               "yuv444p = full colour resolution, sharper edges/text, "
                               "but many players and all browsers refuse to play it.",
                }),
                "audio_bitrate": ("INT", {
                    "default": 192, "min": 64, "max": 320, "step": 32,
                    "tooltip": "AAC bitrate in kbit/s. 128 = speech, 192 = very good, "
                               "256-320 = music/transparent.",
                }),
                "save_workflow_png": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Save the first frame as PNG with the complete workflow "
                               "embedded. Drag & drop into ComfyUI restores the workflow.",
                }),
                "png_compression": ("INT", {
                    "default": 4, "min": 0, "max": 9, "step": 1,
                    "tooltip": "PNG is ALWAYS lossless. This only trades file size "
                               "against write time: 0 = fastest/largest, 9 = smallest/"
                               "slowest. 4 is a good balance.",
                }),
                "save_frame": (["none", "first", "last", "first+last", "all"], {
                    "default": "none",
                    "tooltip": "Automatically save frames as images next to the video "
                               "(name_first Frame / name_last Frame / name_frame_00001). "
                               "The 'Save Last Frame' button works independently of this.",
                }),
                "frame_format": (["jpg", "png"], {
                    "default": "jpg",
                    "tooltip": "Image format for saved frames. jpg = small, lossy. "
                               "png = lossless, larger (uses png_compression).",
                }),
                "frame_quality": ("INT", {
                    "default": 95, "min": 10, "max": 100, "step": 1,
                    "tooltip": "JPEG quality for saved frames (ignored for png). "
                               "90-95 = excellent, 100 = near lossless but large.",
                }),
                "copy_to_folder": ("STRING", {
                    "default": "",
                    "placeholder": "Target folder for 'Save Training File'",
                    "tooltip": "Target folder used by the 'Save Training File' button. "
                               "Copies mp4 + png + txt + frames with identical names.",
                }),
            },
            "optional": {
                "video": ("VIDEO", {
                    "tooltip": "VIDEO output of models with native audio (e.g. MiniMax). "
                               "Frames, audio and frame rate are taken from it. "
                               "A connected 'audio' input overrides its audio track.",
                }),
                "images": ("IMAGE", {
                    "tooltip": "Frames as IMAGE batch (used when no VIDEO is connected).",
                }),
                "audio": ("AUDIO", {
                    "tooltip": "Audio track. Overrides the audio contained in a VIDEO input.",
                }),
                "prompt_text": ("STRING", {
                    "forceInput": True,
                    "tooltip": "Saved as name.txt next to the video (training pair). "
                               "Nothing is written if empty.",
                }),
                "seed": ("INT", {
                    "forceInput": True, "default": 0, "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Only used for the %seed% placeholder in filename_prefix.",
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
                "unique_id": "UNIQUE_ID",
            },
        }

    # ------------------------------------------------------------------ #
    def save(self, filename_prefix, custom_output_path, frame_rate, video_codec,
             crf, preset, pixel_format, audio_bitrate, save_workflow_png,
             png_compression, save_frame, frame_format, frame_quality,
             copy_to_folder="", video=None, images=None, audio=None,
             prompt_text=None, seed=None, prompt=None, extra_pnginfo=None,
             unique_id=None):

        ffmpeg = _find_ffmpeg()

        # ---------------- collect frames / audio / fps ----------------
        fps = float(frame_rate)
        video_audio = None
        if video is not None:
            v_images, video_audio, v_fps = _components_from_video(video)
            if v_images is None or len(v_images) == 0:
                raise ValueError(f"{LOG} VIDEO input contains no frames.")
            images = v_images
            if v_fps:
                fps = v_fps
        if images is None or images.shape[0] == 0:
            raise ValueError(f"{LOG} Connect either 'video' or 'images'.")

        audio_src = audio if audio is not None else video_audio
        audio_data = None
        audio_info = "no audio"
        if audio_src is not None:
            audio_data = _prepare_audio(audio_src)  # raises loudly on bad input
            if audio_data is None:
                audio_info = "audio input is empty (0 samples)"
            else:
                _, a_sr, a_ch, a_sec = audio_data
                ch_name = {1: "mono", 2: "stereo"}.get(a_ch, f"{a_ch} ch")
                audio_info = f"{a_sr} Hz {ch_name}, {a_sec:.2f} s"

        num_frames, height, width = int(images.shape[0]), int(images.shape[1]), int(images.shape[2])
        duration = num_frames / fps

        # ---------------- resolve paths ----------------
        out_root = _resolve_output_dir(custom_output_path)
        templated = _apply_template(filename_prefix, seed)
        sub, name = os.path.split(templated.replace("\\", "/"))
        name = _sanitize_name(name)
        out_dir = os.path.normpath(os.path.join(out_root, sub)) if sub else out_root
        os.makedirs(out_dir, exist_ok=True)
        base = _next_basename(out_dir, name)
        video_path = os.path.join(out_dir, base + ".mp4")

        print(f"{LOG} {num_frames} frames {width}x{height} @ {fps:.3f} fps "
              f"({duration:.2f} s) -> {video_path}")
        print(f"{LOG} audio: {audio_info}")

        # ---------------- encode ----------------
        tmpdir = tempfile.mkdtemp(prefix="comfyui_vsp_")
        stderr_path = os.path.join(tmpdir, "ffmpeg_stderr.txt")
        try:
            cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                   "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
                   "-r", f"{fps:.6f}", "-i", "pipe:0"]

            audio_raw_path = None
            if audio_data is not None:
                raw, a_sr, a_ch, _ = audio_data
                audio_raw_path = os.path.join(tmpdir, "audio.f32le")
                with open(audio_raw_path, "wb") as f:
                    f.write(raw)
                cmd += ["-f", "f32le", "-ar", str(a_sr), "-ac", str(a_ch),
                        "-i", audio_raw_path]

            cmd += ["-map", "0:v:0"]
            if audio_raw_path:
                cmd += ["-map", "1:a:0"]

            vf = []
            if pixel_format == "yuv420p" and (width % 2 or height % 2):
                vf.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
                print(f"{LOG} odd dimensions -> scaled to even size for yuv420p")
            if vf:
                cmd += ["-vf", ",".join(vf)]

            if video_codec == "h265":
                cmd += ["-c:v", "libx265", "-tag:v", "hvc1",
                        "-x265-params", "log-level=error"]
            else:
                cmd += ["-c:v", "libx264"]
            cmd += ["-crf", str(int(crf)), "-preset", preset,
                    "-pix_fmt", pixel_format, "-movflags", "+faststart"]

            if audio_raw_path:
                cmd += ["-c:a", "aac", "-b:a", f"{int(audio_bitrate)}k", "-shortest"]

            cmd += [video_path]

            with open(stderr_path, "wb") as errf:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                        stdout=subprocess.DEVNULL, stderr=errf)
                try:
                    for i in range(num_frames):
                        proc.stdin.write(_tensor_frame_to_uint8(images[i]).tobytes())
                except BrokenPipeError:
                    pass
                finally:
                    try:
                        proc.stdin.close()
                    except Exception:
                        pass
                    proc.wait()

            if proc.returncode != 0 or not os.path.isfile(video_path):
                with open(stderr_path, "r", errors="replace") as f:
                    err = f.read()[-3000:]
                raise RuntimeError(f"{LOG} ffmpeg failed (code {proc.returncode}):\n{err}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        size_mb = os.path.getsize(video_path) / (1024 * 1024)
        print(f"{LOG} saved {video_path} ({size_mb:.1f} MB)")

        files = [video_path]

        # ---------------- workflow PNG ----------------
        first_arr = _tensor_frame_to_uint8(images[0])
        last_arr = _tensor_frame_to_uint8(images[-1])
        if save_workflow_png:
            meta = PngInfo()
            if prompt is not None:
                meta.add_text("prompt", json.dumps(prompt))
            if extra_pnginfo:
                for k, v in extra_pnginfo.items():
                    meta.add_text(k, v if isinstance(v, str) else json.dumps(v))
            png_path = os.path.join(out_dir, base + ".png")
            _save_image(first_arr, png_path, "png", 100, png_compression, meta)
            files.append(png_path)

        # ---------------- prompt txt ----------------
        if prompt_text is not None and str(prompt_text).strip():
            txt_path = os.path.join(out_dir, base + ".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(str(prompt_text))
            files.append(txt_path)

        # ---------------- frames ----------------
        ext = "." + frame_format
        if save_frame in ("first", "first+last"):
            p = os.path.join(out_dir, base + FIRST_SUFFIX + ext)
            _save_image(first_arr, p, frame_format, frame_quality, png_compression)
            files.append(p)
        if save_frame in ("last", "first+last"):
            p = os.path.join(out_dir, base + LAST_SUFFIX + ext)
            _save_image(last_arr, p, frame_format, frame_quality, png_compression)
            files.append(p)
        if save_frame == "all":
            for i in range(num_frames):
                p = os.path.join(out_dir, f"{base}_frame_{i + 1:05d}{ext}")
                _save_image(_tensor_frame_to_uint8(images[i]), p, frame_format,
                            frame_quality, png_compression)
                files.append(p)

        # ---------------- remember for buttons ----------------
        node_key = str(unique_id) if unique_id is not None else "default"
        with _SESSION_LOCK:
            _SESSION[node_key] = {
                "dir": out_dir,
                "base": base,
                "video": video_path,
                "files": files,
                "first_frame": first_arr,
                "last_frame": last_arr,
                "frame_format": frame_format,
                "frame_quality": int(frame_quality),
                "png_compression": int(png_compression),
                "ffmpeg": ffmpeg,
            }

        status = {
            "node_id": node_key,
            "video": video_path,
            "base": base,
            "size_mb": round(size_mb, 2),
            "frames": num_frames,
            "fps": round(fps, 3),
            "duration": round(duration, 2),
            "resolution": f"{width}x{height}",
            "audio": audio_info,
            "has_audio": audio_data is not None,
            "files": [os.path.basename(f) for f in files],
        }
        return {
            "ui": {
                "text": [f"{base}.mp4 ({size_mb:.1f} MB) | audio: {audio_info}"],
                "vsp_status": [status],
            },
            "result": (video_path,),
        }


# --------------------------------------------------------------------------- #
# Button actions (server side)
# --------------------------------------------------------------------------- #
def _get_entry(node_id: str) -> Optional[dict]:
    with _SESSION_LOCK:
        return _SESSION.get(str(node_id))


def _existing(files):
    return [f for f in files if os.path.isfile(f)]


def _last_frame_path(entry) -> str:
    return os.path.join(entry["dir"], entry["base"] + LAST_SUFFIX + "." + entry["frame_format"])


def _extract_last_frame_with_ffmpeg(entry, target: str):
    """Fallback when the frame is no longer in memory: one seek near the end,
    overwrite until the final frame remains. Sub-second, slight H.264 loss."""
    cmd = [entry["ffmpeg"], "-y", "-hide_banner", "-loglevel", "error",
           "-sseof", "-1", "-i", entry["video"], "-update", "1"]
    if entry["frame_format"] == "jpg":
        q = max(2, min(31, int(round(31 - (entry["frame_quality"] - 10) * 29 / 90))))
        cmd += ["-q:v", str(q)]
    cmd += [target]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.isfile(target):
        raise RuntimeError(r.stderr[-1000:] or "ffmpeg failed")


def handle_action(action: str, node_id: str, payload: dict) -> dict:
    entry = _get_entry(node_id)
    if entry is None:
        return {"ok": False, "message": "Nothing saved by this node in the current session yet."}

    if action == "reveal":
        if not os.path.isfile(entry["video"]):
            return {"ok": False, "message": "Video file no longer exists."}
        _open_in_file_manager(entry["video"])
        return {"ok": True, "message": f"Revealed {os.path.basename(entry['video'])}"}

    if action == "open_video":
        if not os.path.isfile(entry["video"]):
            return {"ok": False, "message": "Video file no longer exists."}
        _open_with_default_app(entry["video"])
        return {"ok": True, "message": f"Opening {os.path.basename(entry['video'])}"}

    if action == "save_last_frame":
        target = _last_frame_path(entry)
        arr = entry.get("last_frame")
        if arr is not None:
            _save_image(arr, target, entry["frame_format"], entry["frame_quality"],
                        entry["png_compression"])
            src = "from memory (lossless)"
        else:
            _extract_last_frame_with_ffmpeg(entry, target)
            src = "extracted from mp4"
        with _SESSION_LOCK:
            if target not in entry["files"]:
                entry["files"].append(target)
        return {"ok": True, "message": f"Saved {os.path.basename(target)} ({src})",
                "path": target}

    if action == "copy":
        target_dir = (payload.get("target") or "").strip()
        if not target_dir:
            return {"ok": False, "message": "Enter a folder in 'copy_to_folder' first."}
        target_dir = os.path.abspath(os.path.expanduser(target_dir))
        os.makedirs(target_dir, exist_ok=True)
        copied = []
        for f in _existing(entry["files"]):
            dst = os.path.join(target_dir, os.path.basename(f))
            shutil.copy2(f, dst)
            copied.append(os.path.basename(f))
        if not copied:
            return {"ok": False, "message": "No files left to copy."}
        return {"ok": True, "message": f"Copied {len(copied)} file(s) to {target_dir}",
                "files": copied}

    if action == "delete":
        deleted = []
        for f in _existing(entry["files"]):
            try:
                os.remove(f)
                deleted.append(os.path.basename(f))
            except Exception as e:
                print(f"{LOG} could not delete {f}: {e}")
        with _SESSION_LOCK:
            _SESSION.pop(str(node_id), None)
        if not deleted:
            return {"ok": False, "message": "Nothing to delete (files already gone)."}
        return {"ok": True, "message": f"Deleted {len(deleted)} file(s)", "files": deleted}

    if action == "status":
        return {"ok": True, "video": entry["video"], "files": entry["files"]}

    return {"ok": False, "message": f"Unknown action '{action}'"}


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
def register_routes():
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception as e:  # pragma: no cover
        print(f"{LOG} routes not registered: {e}")
        return

    srv = PromptServer.instance
    if getattr(srv, "_vsp_routes_registered", False):
        return
    srv._vsp_routes_registered = True

    @srv.routes.post("/video_save_plus/action")
    async def vsp_action(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        action = str(data.get("action", ""))
        node_id = str(data.get("node_id", ""))
        try:
            result = handle_action(action, node_id, data)
        except Exception as e:
            print(f"{LOG} action '{action}' failed: {e}")
            result = {"ok": False, "message": str(e)}
        return web.json_response(result)

    @srv.routes.get("/video_save_plus/file")
    async def vsp_file(request):
        node_id = request.query.get("node_id", "")
        entry = _get_entry(node_id)
        if entry is None or not os.path.isfile(entry["video"]):
            return web.Response(status=404, text="not found")
        return web.FileResponse(entry["video"], headers={"Cache-Control": "no-store"})

    print(f"{LOG} v{__version__} routes registered")


NODE_CLASS_MAPPINGS = {"VideoSavePlus": VideoSavePlus}
NODE_DISPLAY_NAME_MAPPINGS = {"VideoSavePlus": "Video Save Plus (Custom Path) 🎬"}
