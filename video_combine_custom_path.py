"""
ComfyUI Custom Node: Video Combine (Custom Path)
Basierend auf der Idee von comfyui-videohelpersuite "Video Combine",
aber mit der Möglichkeit, in beliebige Ordner/Laufwerke zu speichern.

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
            },
        }

    # ------------------------------------------------------------------ #
    #  Hilfsfunktionen
    # ------------------------------------------------------------------ #

    @staticmethod
    def _find_ffmpeg() -> str:
        """Sucht ffmpeg im System-PATH und in typischen ComfyUI-Pfaden."""
        # 1) Normaler PATH
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg:
            return ffmpeg

        # 2) Typische Orte in ComfyUI-Installationen (Windows)
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
            return []  # GIF wird separat behandelt
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
        - Sonst → benutzerdefinierter Pfad (wird ggf. erstellt)
        """
        if not custom_path or custom_path.strip() == "":
            # Fallback: ComfyUI output folder
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
    def _unique_filename(directory: str, prefix: str, ext: str) -> str:
        """Erzeugt einen eindeutigen Dateinamen (prefix_00001.ext usw.)."""
        counter = 1
        while True:
            name = f"{prefix}_{counter:05d}{ext}"
            full = os.path.join(directory, name)
            if not os.path.exists(full):
                return full
            counter += 1

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
        audio: Optional[dict] = None,
    ):
        ffmpeg = self._find_ffmpeg()
        output_dir = self._resolve_output_path(custom_output_path, create_folder_if_missing)
        ext = self._get_extension(format)
        output_file = self._unique_filename(output_dir, filename_prefix, ext)

        # -------------------------------------------------------------- #
        #  Bilder als temporäre PNG-Sequenz schreiben
        # -------------------------------------------------------------- #
        # images shape: (N, H, W, C)  Werte 0..1 float
        num_frames = images.shape[0]
        if num_frames == 0:
            raise ValueError("Keine Frames zum Kombinieren vorhanden!")

        print(f"[VideoCombineCustomPath] {num_frames} Frames → {output_file}")
        print(f"[VideoCombineCustomPath] Format: {format}, FPS: {frame_rate}, Qualität: {quality}")

        tmpdir = tempfile.mkdtemp(prefix="comfyui_vccp_")

        try:
            # Frames als PNG speichern
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
                    waveform = audio["waveform"]      # (batch, channels, samples)
                    sample_rate = audio["sample_rate"]
                    # Ersten Eintrag im Batch nehmen
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
                # GIF: Palette erzeugen für bessere Qualität
                palette_path = os.path.join(tmpdir, "palette.png")
                # Schritt 1: Palette
                cmd_palette = [
                    ffmpeg, "-y",
                    "-framerate", str(frame_rate),
                    "-i", input_pattern,
                    "-vf", "palettegen=max_colors=256:stats_mode=diff",
                    palette_path,
                ]
                subprocess.run(cmd_palette, check=True, capture_output=True)

                # Schritt 2: GIF mit Palette
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

                # Audio hinzufügen falls vorhanden
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
            # Temporäre Dateien aufräumen
            shutil.rmtree(tmpdir, ignore_errors=True)

        file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
        print(f"[VideoCombineCustomPath] Fertig! {output_file} ({file_size_mb:.1f} MB)")

        return {"ui": {"text": [f"Gespeichert: {output_file} ({file_size_mb:.1f} MB)"]},
                "result": (output_file,)}


# ====================================================================== #
#  Node-Registrierung
# ====================================================================== #

NODE_CLASS_MAPPINGS = {
    "VideoCombineCustomPath": VideoCombineCustomPath,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoCombineCustomPath": "Video Combine (Custom Path) 🎬",
}
