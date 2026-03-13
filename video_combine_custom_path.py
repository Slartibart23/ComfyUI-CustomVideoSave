"""
ComfyUI Custom Node: Video Combine (Custom Path)
Basierend auf der Idee von comfyui-videohelpersuite "Video Combine",
aber mit der Möglichkeit, in beliebige Ordner/Laufwerke zu speichern.

Features:
- Beliebiger Ausgabepfad (auch andere Laufwerke)
- Optionale Metadata-Speicherung (JSON)
- Video-Preview im ComfyUI-Interface
- Workflow als PNG speichern (mit eingebettetem Workflow)

Kompatibel mit Python 3.11.9 und ComfyUI.
"""

import os
import sys
import subprocess
import shutil
import tempfile
import json
import numpy as np
from pathlib import Path
from typing import Optional
from datetime import datetime

import torch


class VideoCombineCustomPath:
    """
    Kombiniert Einzelbilder (IMAGE-Tensor) zu einem Video und speichert es
    in einem frei wählbaren Ordner – auch auf anderen Laufwerken.
    """

    CATEGORY = "video/custom"
    FUNCTION = "combine_video"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("filepath",)
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "frame_rate": ("FLOAT", {
                    "default": 24.0,
                    "min": 1.0,
                    "max": 120.0,
                    "step": 0.1,
                    "display": "number",
                }),
                "filename_prefix": ("STRING", {
                    "default": "output_video",
                }),
                "format": (["mp4 (h264)", "mp4 (h265)", "webm (vp9)", "avi (rawvideo)", "gif"],),
                "quality": (["high", "medium", "low"],),
                "custom_output_path": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": r"z.B. O:\MeinOrdner\Videos oder leer = ComfyUI output",
                }),
                "create_folder_if_missing": ("BOOLEAN", {
                    "default": True,
                }),
            },
            "optional": {
                "audio": ("AUDIO",),
                # --- Metadata ---
                "save_metadata": ("BOOLEAN", {
                    "default": True,
                }),
                "meta_model_name": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "z.B. WAN2.1, SVD, AnimateDiff ...",
                }),
                "meta_positive_prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "Positive Prompt",
                }),
                "meta_negative_prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "Negative Prompt",
                }),
                "meta_lora_name": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "z.B. Sus4nn3_WAN22_02",
                }),
                "meta_lora_strength": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 5.0,
                    "step": 0.05,
                }),
                "meta_steps": ("INT", {
                    "default": 20,
                    "min": 1,
                    "max": 200,
                }),
                "meta_cfg": ("FLOAT", {
                    "default": 7.0,
                    "min": 0.0,
                    "max": 30.0,
                    "step": 0.1,
                }),
                "meta_seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                }),
                "meta_resolution": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "placeholder": "z.B. 1280x720",
                }),
                "meta_custom_notes": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "placeholder": "Eigene Notizen ...",
                }),
                # --- Preview ---
                "enable_preview": ("BOOLEAN", {
                    "default": True,
                }),
                "preview_max_frames": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 16,
                    "step": 1,
                    "display": "number",
                }),
                # --- Workflow PNG ---
                "save_workflow_png": ("BOOLEAN", {
                    "default": True,
                }),
            },
            "hidden": {
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    # ------------------------------------------------------------------ #
    #  Hilfsfunktionen
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_ffmpeg() -> str:
        """Sucht ffmpeg im System-PATH und in typischen ComfyUI-Pfaden."""
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

        raise FileNotFoundError(
            "ffmpeg wurde nicht gefunden! Bitte installiere ffmpeg und stelle "
            "sicher, dass es im System-PATH liegt oder im ComfyUI-Python-Ordner."
        )

    @staticmethod
    def _get_codec_args(fmt: str, quality: str) -> list[str]:
        """Gibt ffmpeg-Codec-Argumente zurück."""
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
        elif fmt == "gif":
            return []
        return []

    @staticmethod
    def _get_extension(fmt: str) -> str:
        ext_map = {
            "mp4 (h264)": ".mp4",
            "mp4 (h265)": ".mp4",
            "webm (vp9)": ".webm",
            "avi (rawvideo)": ".avi",
            "gif": ".gif",
        }
        return ext_map.get(fmt, ".mp4")

    @staticmethod
    def _resolve_output_path(custom_path: str, create: bool) -> str:
        """
        Bestimmt den Ausgabeordner.
        - Leer → ComfyUI Standard-Output
        - Sonst → benutzerdefinierter Pfad
        """
        if not custom_path or custom_path.strip() == "":
            import folder_paths
            return folder_paths.get_output_directory()

        resolved = os.path.abspath(custom_path.strip())

        if not os.path.exists(resolved):
            if create:
                os.makedirs(resolved, exist_ok=True)
                print(f"[VideoCombineCustomPath] Ordner erstellt: {resolved}")
            else:
                raise FileNotFoundError(
                    f"Der Ausgabeordner existiert nicht: {resolved}\n"
                    f"Aktiviere 'create_folder_if_missing' oder erstelle ihn manuell."
                )

        if not os.path.isdir(resolved):
            raise NotADirectoryError(f"Der Pfad ist kein Ordner: {resolved}")

        return resolved

    @staticmethod
    def _unique_filepath(directory: str, prefix: str, ext: str) -> tuple[str, str]:
        """
        Erzeugt einen eindeutigen Dateinamen (prefix_00001.ext usw.).
        Gibt (voller_pfad, basis_name_ohne_ext) zurück.
        """
        counter = 1
        while True:
            basename = f"{prefix}_{counter:05d}"
            full = os.path.join(directory, f"{basename}{ext}")
            if not os.path.exists(full):
                return full, basename
            counter += 1

    # ------------------------------------------------------------------ #
    #  Metadata
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_metadata(
        filepath_json: str,
        video_filepath: str,
        frame_rate: float,
        fmt: str,
        quality: str,
        num_frames: int,
        resolution: tuple,
        model_name: str = "",
        positive_prompt: str = "",
        negative_prompt: str = "",
        lora_name: str = "",
        lora_strength: float = 1.0,
        steps: int = 20,
        cfg: float = 7.0,
        seed: int = 0,
        meta_resolution: str = "",
        custom_notes: str = "",
        prompt: dict = None,
    ):
        """Speichert Metadaten als JSON-Datei neben dem Video."""
        metadata = {
            "file_info": {
                "video_file": os.path.basename(video_filepath),
                "video_path": video_filepath,
                "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "format": fmt,
                "quality": quality,
                "frame_rate": frame_rate,
                "total_frames": num_frames,
                "frame_resolution": f"{resolution[1]}x{resolution[0]}",
                "duration_seconds": round(num_frames / frame_rate, 2),
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

        # ComfyUI Workflow-Prompt (wenn verfügbar)
        if prompt:
            metadata["comfyui_prompt"] = prompt

        with open(filepath_json, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"[VideoCombineCustomPath] Metadata gespeichert: {filepath_json}")

    # ------------------------------------------------------------------ #
    #  Preview-Bilder erzeugen
    # ------------------------------------------------------------------ #

    @staticmethod
    def _generate_preview_images(
        images: torch.Tensor,
        output_dir: str,
        basename: str,
        max_frames: int = 1,
    ) -> list[dict]:
        """
        Speichert Preview-Frames als PNG im ComfyUI-Output-Ordner
        und gibt die UI-Daten für die Bildvorschau zurück.
        """
        from PIL import Image as PILImage
        import folder_paths

        # Preview kommt immer in den ComfyUI output-Ordner (für die UI)
        preview_dir = folder_paths.get_output_directory()
        preview_subfolder = "video_previews"
        preview_path = os.path.join(preview_dir, preview_subfolder)
        os.makedirs(preview_path, exist_ok=True)

        num_frames = images.shape[0]
        results = []

        if max_frames == 1:
            indices = [0]
        else:
            # Gleichmäßig verteilte Frames
            indices = np.linspace(0, num_frames - 1, min(max_frames, num_frames),
                                  dtype=int).tolist()

        for idx, frame_idx in enumerate(indices):
            frame_np = (images[frame_idx].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            img = PILImage.fromarray(frame_np)

            preview_filename = f"{basename}_preview_{idx:03d}.png"
            preview_filepath = os.path.join(preview_path, preview_filename)
            img.save(preview_filepath, format="PNG")

            results.append({
                "filename": preview_filename,
                "subfolder": preview_subfolder,
                "type": "output",
            })

        print(f"[VideoCombineCustomPath] {len(results)} Preview-Bild(er) erzeugt")
        return results

    # ------------------------------------------------------------------ #
    #  Workflow als PNG speichern
    # ------------------------------------------------------------------ #

    @staticmethod
    def _save_workflow_png(
        images: torch.Tensor,
        filepath_png: str,
        prompt: dict = None,
        extra_pnginfo: dict = None,
    ):
        """
        Speichert das erste Frame als PNG mit eingebettetem ComfyUI-Workflow
        in den tEXt-Chunks (wie ComfyUI es bei Bildern macht).
        So kann der Workflow später per Drag & Drop wieder geladen werden.
        """
        from PIL import Image as PILImage
        from PIL.PngImagePlugin import PngInfo

        # Erstes Frame als Bild
        frame_np = (images[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        img = PILImage.fromarray(frame_np)

        # PNG Metadata mit Workflow-Infos
        png_meta = PngInfo()

        if prompt is not None:
            png_meta.add_text("prompt", json.dumps(prompt))

        if extra_pnginfo is not None:
            for key, value in extra_pnginfo.items():
                if isinstance(value, str):
                    png_meta.add_text(key, value)
                else:
                    png_meta.add_text(key, json.dumps(value))

        img.save(filepath_png, format="PNG", pnginfo=png_meta)
        print(f"[VideoCombineCustomPath] Workflow-PNG gespeichert: {filepath_png}")

    # ------------------------------------------------------------------ #
    #  Hauptfunktion
    # ------------------------------------------------------------------ #

    def combine_video(
        self,
        images: torch.Tensor,
        frame_rate: float,
        filename_prefix: str,
        format: str,
        quality: str,
        custom_output_path: str,
        create_folder_if_missing: bool,
        # Optional
        audio: Optional[dict] = None,
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
        # Hidden
        prompt: dict = None,
        extra_pnginfo: dict = None,
    ):
        ffmpeg = self._find_ffmpeg()
        output_dir = self._resolve_output_path(custom_output_path, create_folder_if_missing)
        ext = self._get_extension(format)
        output_file, basename = self._unique_filepath(output_dir, filename_prefix, ext)

        # -------------------------------------------------------------- #
        #  Bilder als temporäre PNG-Sequenz schreiben
        # -------------------------------------------------------------- #
        num_frames = images.shape[0]
        if num_frames == 0:
            raise ValueError("Keine Frames zum Kombinieren vorhanden!")

        height, width = images.shape[1], images.shape[2]

        print(f"[VideoCombineCustomPath] {num_frames} Frames → {output_file}")
        print(f"[VideoCombineCustomPath] Format: {format}, FPS: {frame_rate}, "
              f"Qualität: {quality}, Auflösung: {width}x{height}")

        tmpdir = tempfile.mkdtemp(prefix="comfyui_vccp_")

        try:
            from PIL import Image as PILImage

            for i in range(num_frames):
                frame_np = (images[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
                img = PILImage.fromarray(frame_np)
                img.save(os.path.join(tmpdir, f"frame_{i:06d}.png"))

            # ---------------------------------------------------------- #
            #  Audio vorbereiten (optional)
            # ---------------------------------------------------------- #
            audio_path = None
            if audio is not None:
                audio_path = os.path.join(tmpdir, "audio_input.wav")
                try:
                    import torchaudio
                    waveform = audio["waveform"]
                    sample_rate = audio["sample_rate"]
                    if waveform.dim() == 3:
                        waveform = waveform[0]
                    torchaudio.save(audio_path, waveform.cpu(), sample_rate)
                except Exception as e:
                    print(f"[VideoCombineCustomPath] Audio-Warnung: {e}")
                    audio_path = None

            # ---------------------------------------------------------- #
            #  ffmpeg aufrufen
            # ---------------------------------------------------------- #
            input_pattern = os.path.join(tmpdir, "frame_%06d.png")

            if format == "gif":
                palette_path = os.path.join(tmpdir, "palette.png")
                cmd_palette = [
                    ffmpeg, "-y",
                    "-framerate", str(frame_rate),
                    "-i", input_pattern,
                    "-vf", "palettegen=max_colors=256:stats_mode=diff",
                    palette_path,
                ]
                subprocess.run(cmd_palette, check=True, capture_output=True)

                cmd_gif = [
                    ffmpeg, "-y",
                    "-framerate", str(frame_rate),
                    "-i", input_pattern,
                    "-i", palette_path,
                    "-lavfi", "paletteuse=dither=bayer:bayer_scale=5",
                    output_file,
                ]
                subprocess.run(cmd_gif, check=True, capture_output=True)
            else:
                codec_args = self._get_codec_args(format, quality)
                cmd = [
                    ffmpeg, "-y",
                    "-framerate", str(frame_rate),
                    "-i", input_pattern,
                ]

                if audio_path and os.path.isfile(audio_path):
                    cmd += ["-i", audio_path, "-c:a", "aac", "-b:a", "192k"]

                cmd += codec_args
                cmd += ["-r", str(frame_rate), output_file]

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    error_msg = result.stderr[-2000:] if result.stderr else "Unbekannter Fehler"
                    raise RuntimeError(
                        f"ffmpeg fehlgeschlagen (Code {result.returncode}):\n{error_msg}"
                    )

        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"[VideoCombineCustomPath] Video fertig! {output_file} ({file_size_mb:.1f} MB)")

        # -------------------------------------------------------------- #
        #  Metadata speichern (optional)
        # -------------------------------------------------------------- #
        if save_metadata:
            json_path = os.path.join(output_dir, f"{basename}_metadata.json")
            self._save_metadata(
                filepath_json=json_path,
                video_filepath=output_file,
                frame_rate=frame_rate,
                fmt=format,
                quality=quality,
                num_frames=num_frames,
                resolution=(height, width),
                model_name=meta_model_name,
                positive_prompt=meta_positive_prompt,
                negative_prompt=meta_negative_prompt,
                lora_name=meta_lora_name,
                lora_strength=meta_lora_strength,
                steps=meta_steps,
                cfg=meta_cfg,
                seed=meta_seed,
                meta_resolution=meta_resolution,
                custom_notes=meta_custom_notes,
                prompt=prompt,
            )

        # -------------------------------------------------------------- #
        #  Workflow als PNG speichern (optional)
        # -------------------------------------------------------------- #
        if save_workflow_png:
            png_path = os.path.join(output_dir, f"{basename}_workflow.png")
            self._save_workflow_png(
                images=images,
                filepath_png=png_path,
                prompt=prompt,
                extra_pnginfo=extra_pnginfo,
            )

        # -------------------------------------------------------------- #
        #  Preview erzeugen (optional)
        # -------------------------------------------------------------- #
        ui_data = {
            "text": [f"Gespeichert: {output_file} ({file_size_mb:.1f} MB)"],
        }

        if enable_preview:
            preview_images = self._generate_preview_images(
                images=images,
                output_dir=output_dir,
                basename=basename,
                max_frames=preview_max_frames,
            )
            ui_data["images"] = preview_images

        return {"ui": ui_data, "result": (output_file,)}


# ====================================================================== #
#  Node-Registrierung
# ====================================================================== #

NODE_CLASS_MAPPINGS = {
    "VideoCombineCustomPath": VideoCombineCustomPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoCombineCustomPath": "Video Combine (Custom Path) 🎬",
}
