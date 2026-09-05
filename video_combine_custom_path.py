"""
ComfyUI Custom Node: Video Combine (Custom Path)
Based on the idea of comfyui-videohelpersuite "Video Combine", but able to
save into ANY folder on ANY drive.

Features:
- Custom output path (other drives, UNC paths)
- Optional metadata JSON next to the video
- Preview frames in the ComfyUI interface
- Workflow as PNG (first frame with embedded workflow, drag & drop reload)
- v1.1: passthrough mode — hand in a finished MP4 (e.g. from the Grok
  Imagine Video node) and it is copied without re-encoding, audio track kept;
  optional <name>_prompt.txt and <name>_workflow.json exports;
  English tooltips on every widget.

Compatible with Python 3.11.9 and ComfyUI.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from typing import Optional

import numpy as np
import torch


class VideoCombineCustomPath:
    """Combine frames (IMAGE tensor) into a video — or pass a finished video
    through — and save it in a freely chosen folder, on any drive."""

    CATEGORY = "video/custom"
    FUNCTION = "combine_video"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "frame_rate": ("FLOAT", {
                    "default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1,
                    "display": "number", "tooltip":
                    "Frames per second of the encoded video. Connect the fps output of "
                    "your video source (e.g. Grok Imagine Video) to keep the original "
                    "speed. Ignored in passthrough mode."}),
                "filename_prefix": ("STRING", {"default": "output_video", "tooltip":
                    "Base name of the files. A counter is appended automatically: "
                    "prefix_00001.mp4, prefix_00002.mp4 ... Sidecar files use the same "
                    "base name (_metadata.json, _workflow.png/.json, _prompt.txt)."}),
                "format": (["mp4 (h264)", "mp4 (h265)", "webm (vp9)", "avi (rawvideo)", "gif"],
                           {"tooltip":
                    "Container/codec when encoding frames. mp4 (h264) is the most "
                    "compatible choice. Ignored in passthrough mode (the source file is "
                    "copied as-is)."}),
                "quality": (["high", "medium", "low"], {"tooltip":
                    "Encoder quality (CRF 18 / 23 / 30). high = larger file, best "
                    "picture. Ignored for avi/gif and in passthrough mode."}),
                "custom_output_path": ("STRING", {
                    "default": "", "multiline": False,
                    "placeholder": r"e.g. O:\MyFolder\Videos  (empty = ComfyUI output)",
                    "tooltip":
                    "Destination folder on any drive, e.g. D:\\Videos or a network "
                    "share. Leave empty to use the ComfyUI output folder."}),
                "create_folder_if_missing": ("BOOLEAN", {"default": True, "tooltip":
                    "Create the destination folder (and parents) if it does not exist. "
                    "Off = stop with an error instead."}),
            },
            "optional": {
                "images": ("IMAGE", {"tooltip":
                    "The frames to encode. Optional in passthrough mode — then they are "
                    "only used for the preview and the workflow PNG (if not connected, "
                    "the first frame is taken from the source video)."}),
                "audio": ("AUDIO", {"tooltip":
                    "Optional audio track, embedded as AAC. In passthrough mode it "
                    "REPLACES the source video's own audio (video stream is copied, not "
                    "re-encoded). Leave unconnected to keep the original soundtrack."}),
                # --- Passthrough (v1.1) ---
                "source_video_path": ("STRING", {"default": "", "multiline": False,
                    "placeholder": "connect video_path of Grok Imagine Video",
                    "tooltip":
                    "PASSTHROUGH MODE: path of a finished video file (e.g. the "
                    "video_path output of Grok Imagine Video). When set, the file is "
                    "copied 1:1 to the destination — no re-encoding, no quality loss, "
                    "audio kept — and the format/quality/frame_rate widgets are ignored. "
                    "Leave empty to encode 'images' as before."}),
                # --- Metadata ---
                "save_metadata": ("BOOLEAN", {"default": True, "tooltip":
                    "Write <name>_metadata.json next to the video with the file info and "
                    "all meta_* fields below (plus the API-format workflow prompt)."}),
                "meta_model_name": ("STRING", {"default": "", "multiline": False,
                    "placeholder": "e.g. WAN2.2, LTX-2.3, grok-imagine-video-1.5",
                    "tooltip": "Name of the generation model, stored in the metadata JSON."}),
                "meta_positive_prompt": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "Positive prompt", "tooltip":
                    "The positive prompt. Connect the 'prompt' output of Grok Imagine "
                    "Video or any text node. Stored in the metadata JSON and, with "
                    "save_prompt_txt, written to <name>_prompt.txt."}),
                "meta_negative_prompt": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "Negative prompt", "tooltip":
                    "The negative prompt (if your model uses one). Stored in the "
                    "metadata JSON and appended to the prompt .txt when present."}),
                "meta_lora_name": ("STRING", {"default": "", "multiline": False,
                    "placeholder": "e.g. my_character_v2", "tooltip":
                    "LoRA name, for your records in the metadata JSON."}),
                "meta_lora_strength": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 5.0,
                    "step": 0.05, "tooltip": "LoRA strength, for your records."}),
                "meta_steps": ("INT", {"default": 20, "min": 1, "max": 200, "tooltip":
                    "Sampling steps used, for your records."}),
                "meta_cfg": ("FLOAT", {"default": 7.0, "min": 0.0, "max": 30.0,
                    "step": 0.1, "tooltip": "CFG scale used, for your records."}),
                "meta_seed": ("INT", {"default": 0, "min": 0, "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Seed used, for your records."}),
                "meta_resolution": ("STRING", {"default": "", "multiline": False,
                    "placeholder": "e.g. 1280x720", "tooltip":
                    "Resolution as text, for your records (the real frame size is "
                    "recorded automatically)."}),
                "meta_custom_notes": ("STRING", {"default": "", "multiline": True,
                    "placeholder": "Your notes ...", "tooltip":
                    "Free-form notes stored in the metadata JSON."}),
                # --- Preview ---
                "enable_preview": ("BOOLEAN", {"default": True, "tooltip":
                    "Show preview frames on the node after saving. Preview PNGs are "
                    "written to ComfyUI/output/video_previews."}),
                "preview_max_frames": ("INT", {"default": 1, "min": 1, "max": 16,
                    "step": 1, "display": "number", "tooltip":
                    "How many evenly spaced frames to show as preview (1 = first frame)."}),
                # --- Workflow exports ---
                "save_workflow_png": ("BOOLEAN", {"default": True, "tooltip":
                    "Write <name>_workflow.png: the first frame with the complete "
                    "workflow embedded. Drag & drop it into ComfyUI to reload the "
                    "workflow."}),
                "save_workflow_json": ("BOOLEAN", {"default": False, "tooltip":
                    "Also write <name>_workflow.json — the same workflow as plain JSON "
                    "(loadable via Workflow → Open), readable without image tools."}),
                "save_prompt_txt": ("BOOLEAN", {"default": False, "tooltip":
                    "Write <name>_prompt.txt containing meta_positive_prompt (and the "
                    "negative prompt, if given)."}),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_ffmpeg() -> str:
        """Find ffmpeg in PATH, typical ComfyUI locations, or imageio-ffmpeg."""
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

        candidates = [
            os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe"),
            os.path.join(os.path.dirname(sys.executable), "Scripts", "ffmpeg.exe"),
            os.path.join(os.path.dirname(sys.executable), "..", "ffmpeg.exe"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
        raise FileNotFoundError(
            "ffmpeg not found! Install ffmpeg and put it on the PATH (or "
            "`pip install imageio-ffmpeg` into the ComfyUI python)."
        )

    @staticmethod
    def _get_codec_args(fmt: str, quality: str) -> list[str]:
        crf_map = {"high": "18", "medium": "23", "low": "30"}
        crf = crf_map.get(quality, "23")

        if fmt == "mp4 (h264)":
            return ["-c:v", "libx264", "-crf", crf, "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        elif fmt == "mp4 (h265)":
            return ["-c:v", "libx265", "-crf", crf, "-preset", "medium",
                    "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-tag:v", "hvc1"]
        elif fmt == "webm (vp9)":
            crf_vp9 = {"high": "20", "medium": "30", "low": "40"}.get(quality, "30")
            return ["-c:v", "libvpx-vp9", "-crf", crf_vp9, "-b:v", "0",
                    "-pix_fmt", "yuv420p"]
        elif fmt == "avi (rawvideo)":
            return ["-c:v", "rawvideo", "-pix_fmt", "bgr24"]
        return []

    @staticmethod
    def _get_extension(fmt: str) -> str:
        return {
            "mp4 (h264)": ".mp4",
            "mp4 (h265)": ".mp4",
            "webm (vp9)": ".webm",
            "avi (rawvideo)": ".avi",
            "gif": ".gif",
        }.get(fmt, ".mp4")

    @staticmethod
    def _resolve_output_path(custom_path: str, create: bool) -> str:
        if not custom_path or custom_path.strip() == "":
            import folder_paths
            return folder_paths.get_output_directory()

        resolved = os.path.abspath(custom_path.strip().strip('"'))

        if not os.path.exists(resolved):
            if create:
                os.makedirs(resolved, exist_ok=True)
                print(f"[VideoCombineCustomPath] Folder created: {resolved}")
            else:
                raise FileNotFoundError(
                    f"Output folder does not exist: {resolved}\n"
                    f"Enable 'create_folder_if_missing' or create it manually."
                )

        if not os.path.isdir(resolved):
            raise NotADirectoryError(f"Path is not a folder: {resolved}")

        return resolved

    @staticmethod
    def _unique_filepath(directory: str, prefix: str, ext: str) -> tuple[str, str]:
        """prefix_00001.ext, prefix_00002.ext ... Returns (full_path, basename)."""
        counter = 1
        while True:
            basename = f"{prefix}_{counter:05d}"
            full = os.path.join(directory, f"{basename}{ext}")
            if not os.path.exists(full):
                return full, basename
            counter += 1

    @staticmethod
    def _write_audio_wav(audio: dict, path: str) -> bool:
        """Write a ComfyUI AUDIO dict to a 16-bit WAV. Uses torchaudio when
        available, otherwise the standard-library wave module."""
        try:
            waveform = audio["waveform"]
            sample_rate = int(audio["sample_rate"])
            if waveform.dim() == 3:
                waveform = waveform[0]
            try:
                import torchaudio
                torchaudio.save(path, waveform.cpu(), sample_rate)
                return True
            except Exception:
                pass
            import wave
            data = np.asarray(waveform.cpu().numpy(), dtype=np.float32)  # (C, N)
            if data.ndim == 1:
                data = data[None, :]
            pcm = (np.clip(data, -1.0, 1.0) * 32767.0).astype("<i2").T  # (N, C)
            with wave.open(path, "wb") as w:
                w.setnchannels(pcm.shape[1])
                w.setsampwidth(2)
                w.setframerate(sample_rate)
                w.writeframes(np.ascontiguousarray(pcm).tobytes())
            return True
        except Exception as e:
            print(f"[VideoCombineCustomPath] Audio warning: {e}")
            return False

    def _first_frame_from_video(self, ffmpeg: str, video_path: str) -> Optional[torch.Tensor]:
        """Grab the first frame of a video file as a (1,H,W,3) tensor."""
        from PIL import Image as PILImage
        tmp = tempfile.mkdtemp(prefix="comfyui_vccp_ff_")
        try:
            png = os.path.join(tmp, "first.png")
            r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", video_path,
                                "-frames:v", "1", png], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.isfile(png):
                return None
            arr = np.asarray(PILImage.open(png).convert("RGB")).astype(np.float32) / 255.0
            return torch.from_numpy(arr)[None, ...]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    @staticmethod
    def _probe_video(ffmpeg: str, video_path: str) -> dict:
        """Best-effort width/height/fps/duration via ffprobe or ffmpeg -i."""
        info = {}
        ffprobe = shutil.which("ffprobe") or os.path.join(os.path.dirname(ffmpeg), "ffprobe")
        try:
            r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "v:0",
                                "-show_entries", "stream=width,height,r_frame_rate,nb_frames"
                                ":format=duration", "-of", "json", video_path],
                               capture_output=True, text=True)
            if r.returncode == 0:
                j = json.loads(r.stdout or "{}")
                st = (j.get("streams") or [{}])[0]
                info["width"] = st.get("width")
                info["height"] = st.get("height")
                fr = st.get("r_frame_rate", "")
                if "/" in fr:
                    a, b = fr.split("/")
                    info["fps"] = round(float(a) / float(b), 3) if float(b) else None
                nf = st.get("nb_frames")
                info["total_frames"] = int(nf) if nf and str(nf).isdigit() else None
                dur = (j.get("format") or {}).get("duration")
                info["duration_seconds"] = round(float(dur), 2) if dur else None
        except Exception:
            pass
        return info

    # ------------------------------------------------------------------ #
    #  Metadata
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_metadata(filepath_json, video_filepath, frame_rate, fmt, quality,
                       num_frames, resolution, model_name="", positive_prompt="",
                       negative_prompt="", lora_name="", lora_strength=1.0,
                       steps=20, cfg=7.0, seed=0, meta_resolution="",
                       custom_notes="", prompt=None, source_video=None,
                       duration_seconds=None):
        if duration_seconds is None and frame_rate and num_frames:
            duration_seconds = round(num_frames / frame_rate, 2)
        metadata = {
            "file_info": {
                "video_file": os.path.basename(video_filepath),
                "video_path": video_filepath,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "format": fmt,
                "quality": quality,
                "frame_rate": frame_rate,
                "total_frames": num_frames,
                "frame_resolution": (f"{resolution[1]}x{resolution[0]}"
                                     if resolution and resolution[0] else ""),
                "duration_seconds": duration_seconds,
            },
            "generation_settings": {
                "model": model_name,
                "positive_prompt": positive_prompt,
                "negative_prompt": negative_prompt,
                "lora": lora_name,
                "lora_strength": lora_strength,
                "steps": steps,
                "cfg": cfg,
                "seed": seed,
                "resolution": meta_resolution,
            },
            "notes": custom_notes,
        }
        if source_video:
            metadata["file_info"]["source_video"] = source_video
            metadata["file_info"]["passthrough"] = True
        if prompt:
            metadata["comfyui_prompt"] = prompt

        with open(filepath_json, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
        print(f"[VideoCombineCustomPath] Metadata saved: {filepath_json}")

    # ------------------------------------------------------------------ #
    #  Preview
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_preview_images(images, basename, max_frames=1) -> list[dict]:
        from PIL import Image as PILImage
        import folder_paths

        preview_dir = folder_paths.get_output_directory()
        preview_subfolder = "video_previews"
        preview_path = os.path.join(preview_dir, preview_subfolder)
        os.makedirs(preview_path, exist_ok=True)

        num_frames = images.shape[0]
        if max_frames == 1:
            indices = [0]
        else:
            indices = np.linspace(0, num_frames - 1, min(max_frames, num_frames),
                                  dtype=int).tolist()

        results = []
        for idx, frame_idx in enumerate(indices):
            frame_np = (images[frame_idx].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            img = PILImage.fromarray(frame_np)
            preview_filename = f"{basename}_preview_{idx:03d}.png"
            img.save(os.path.join(preview_path, preview_filename), format="PNG")
            results.append({"filename": preview_filename,
                            "subfolder": preview_subfolder, "type": "output"})

        print(f"[VideoCombineCustomPath] {len(results)} preview image(s) created")
        return results

    # ------------------------------------------------------------------ #
    #  Workflow exports
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_workflow_png(images, filepath_png, prompt=None, extra_pnginfo=None):
        from PIL import Image as PILImage
        from PIL.PngImagePlugin import PngInfo

        frame_np = (images[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        img = PILImage.fromarray(frame_np)

        png_meta = PngInfo()
        if prompt is not None:
            png_meta.add_text("prompt", json.dumps(prompt))
        if extra_pnginfo is not None:
            for key, value in extra_pnginfo.items():
                png_meta.add_text(key, value if isinstance(value, str) else json.dumps(value))

        img.save(filepath_png, format="PNG", pnginfo=png_meta)
        print(f"[VideoCombineCustomPath] Workflow PNG saved: {filepath_png}")

    @staticmethod
    def _save_workflow_json(filepath_json, prompt=None, extra_pnginfo=None) -> bool:
        workflow = None
        if isinstance(extra_pnginfo, dict):
            workflow = extra_pnginfo.get("workflow")
        if workflow is None and prompt is None:
            print("[VideoCombineCustomPath] No workflow data available — JSON skipped.")
            return False
        with open(filepath_json, "w", encoding="utf-8") as f:
            json.dump(workflow if workflow is not None else {"prompt": prompt}, f,
                      indent=2, ensure_ascii=False)
        print(f"[VideoCombineCustomPath] Workflow JSON saved: {filepath_json}")
        return True

    @staticmethod
    def _save_prompt_txt(filepath_txt, positive, negative="") -> bool:
        positive = (positive or "").strip()
        negative = (negative or "").strip()
        if not positive and not negative:
            print("[VideoCombineCustomPath] Prompt is empty — .txt skipped.")
            return False
        with open(filepath_txt, "w", encoding="utf-8") as f:
            f.write(positive + "\n")
            if negative:
                f.write("\n--- negative ---\n" + negative + "\n")
        print(f"[VideoCombineCustomPath] Prompt saved: {filepath_txt}")
        return True

    # ------------------------------------------------------------------ #
    #  Main
    # ------------------------------------------------------------------ #

    def combine_video(
        self,
        frame_rate: float,
        filename_prefix: str,
        format: str,
        quality: str,
        custom_output_path: str,
        create_folder_if_missing: bool,
        # Optional
        images: Optional[torch.Tensor] = None,
        audio: Optional[dict] = None,
        source_video_path: str = "",
        save_metadata: bool = True,
        meta_model_name: str = "",
        meta_positive_prompt: str = "",
        meta_negative_prompt: str = "",
        meta_lora_name: str = "",
        meta_lora_strength: float = 1.0,
        meta_steps: int = 20,
        meta_cfg: float = 7.0,
        meta_seed: int = 0,
        meta_resolution: str = "",
        meta_custom_notes: str = "",
        enable_preview: bool = True,
        preview_max_frames: int = 1,
        save_workflow_png: bool = True,
        save_workflow_json: bool = False,
        save_prompt_txt: bool = False,
        # Hidden
        prompt: dict = None,
        extra_pnginfo: dict = None,
    ):
        ffmpeg = self._find_ffmpeg()
        output_dir = self._resolve_output_path(custom_output_path, create_folder_if_missing)
        source = (source_video_path or "").strip().strip('"')
        passthrough = bool(source)

        if passthrough and not os.path.isfile(source):
            raise FileNotFoundError(f"source_video_path not found: {source}")
        if not passthrough and images is None:
            raise ValueError("Connect 'images' (frames to encode) or set "
                             "'source_video_path' (passthrough of a finished video).")

        ext = (os.path.splitext(source)[1] or ".mp4") if passthrough else self._get_extension(format)
        output_file, basename = self._unique_filepath(output_dir, filename_prefix, ext)

        tmpdir = tempfile.mkdtemp(prefix="comfyui_vccp_")
        try:
            # ---------------------------------------------------------- #
            #  Audio (optional)
            # ---------------------------------------------------------- #
            audio_path = None
            if audio is not None:
                audio_path = os.path.join(tmpdir, "audio_input.wav")
                if not self._write_audio_wav(audio, audio_path):
                    audio_path = None

            if passthrough:
                # ------------------------------------------------------ #
                #  PASSTHROUGH: copy (or remux with new audio), no re-encode
                # ------------------------------------------------------ #
                print(f"[VideoCombineCustomPath] Passthrough: {source} -> {output_file}")
                if audio_path and os.path.isfile(audio_path):
                    cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", source, "-i", audio_path,
                           "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                           "-c:a", "aac", "-b:a", "192k", "-shortest", output_file]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise RuntimeError(f"ffmpeg remux failed (code {result.returncode}):\n"
                                           f"{(result.stderr or '')[-2000:]}")
                    print("[VideoCombineCustomPath] Video stream copied, audio replaced.")
                else:
                    shutil.copy2(source, output_file)
                probe = self._probe_video(ffmpeg, output_file)
                if images is None:
                    images = self._first_frame_from_video(ffmpeg, output_file)
                num_frames = probe.get("total_frames") or (int(images.shape[0]) if images is not None else 0)
                height = probe.get("height") or (int(images.shape[1]) if images is not None else 0)
                width = probe.get("width") or (int(images.shape[2]) if images is not None else 0)
                used_fps = probe.get("fps") or frame_rate
                duration = probe.get("duration_seconds")
                used_format = f"passthrough ({ext.lstrip('.')})"
                used_quality = "source"
            else:
                # ------------------------------------------------------ #
                #  ENCODE frames with ffmpeg
                # ------------------------------------------------------ #
                num_frames = images.shape[0]
                if num_frames == 0:
                    raise ValueError("No frames to combine!")
                height, width = int(images.shape[1]), int(images.shape[2])
                used_fps, duration = frame_rate, None
                used_format, used_quality = format, quality

                print(f"[VideoCombineCustomPath] {num_frames} frames -> {output_file}")
                print(f"[VideoCombineCustomPath] Format: {format}, FPS: {frame_rate}, "
                      f"quality: {quality}, resolution: {width}x{height}")

                from PIL import Image as PILImage
                for i in range(num_frames):
                    frame_np = (images[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                    PILImage.fromarray(frame_np).save(os.path.join(tmpdir, f"frame_{i:06d}.png"))

                input_pattern = os.path.join(tmpdir, "frame_%06d.png")
                if format == "gif":
                    palette_path = os.path.join(tmpdir, "palette.png")
                    subprocess.run([ffmpeg, "-y", "-framerate", str(frame_rate), "-i",
                                    input_pattern, "-vf",
                                    "palettegen=max_colors=256:stats_mode=diff",
                                    palette_path], check=True, capture_output=True)
                    subprocess.run([ffmpeg, "-y", "-framerate", str(frame_rate), "-i",
                                    input_pattern, "-i", palette_path, "-lavfi",
                                    "paletteuse=dither=bayer:bayer_scale=5", output_file],
                                   check=True, capture_output=True)
                else:
                    cmd = [ffmpeg, "-y", "-framerate", str(frame_rate), "-i", input_pattern]
                    if audio_path and os.path.isfile(audio_path):
                        cmd += ["-i", audio_path, "-c:a", "aac", "-b:a", "192k", "-shortest"]
                    cmd += self._get_codec_args(format, quality)
                    cmd += ["-r", str(frame_rate), output_file]
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode != 0:
                        raise RuntimeError(f"ffmpeg failed (code {result.returncode}):\n"
                                           f"{(result.stderr or 'unknown error')[-2000:]}")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"[VideoCombineCustomPath] Video done! {output_file} ({file_size_mb:.1f} MB)")

        # ---------------------------------------------------------- #
        #  Sidecar files
        # ---------------------------------------------------------- #
        if save_metadata:
            self._save_metadata(
                filepath_json=os.path.join(output_dir, f"{basename}_metadata.json"),
                video_filepath=output_file, frame_rate=used_fps, fmt=used_format,
                quality=used_quality, num_frames=num_frames, resolution=(height, width),
                model_name=meta_model_name, positive_prompt=meta_positive_prompt,
                negative_prompt=meta_negative_prompt, lora_name=meta_lora_name,
                lora_strength=meta_lora_strength, steps=meta_steps, cfg=meta_cfg,
                seed=meta_seed, meta_resolution=meta_resolution,
                custom_notes=meta_custom_notes, prompt=prompt,
                source_video=source if passthrough else None, duration_seconds=duration,
            )

        if save_workflow_png:
            if images is not None:
                self._save_workflow_png(images, os.path.join(output_dir, f"{basename}_workflow.png"),
                                        prompt=prompt, extra_pnginfo=extra_pnginfo)
            else:
                print("[VideoCombineCustomPath] No frame available — workflow PNG skipped "
                      "(enable save_workflow_json instead).")

        if save_workflow_json:
            self._save_workflow_json(os.path.join(output_dir, f"{basename}_workflow.json"),
                                     prompt=prompt, extra_pnginfo=extra_pnginfo)

        if save_prompt_txt:
            self._save_prompt_txt(os.path.join(output_dir, f"{basename}_prompt.txt"),
                                  meta_positive_prompt, meta_negative_prompt)

        # ---------------------------------------------------------- #
        #  Preview
        # ---------------------------------------------------------- #
        ui_data = {"text": [f"Saved: {output_file} ({file_size_mb:.1f} MB)"]}
        if enable_preview and images is not None:
            ui_data["images"] = self._generate_preview_images(images, basename,
                                                              preview_max_frames)

        return {"ui": ui_data, "result": (output_file,)}


NODE_CLASS_MAPPINGS = {
    "VideoCombineCustomPath": VideoCombineCustomPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoCombineCustomPath": "Video Combine (Custom Path) 🎬",
}
