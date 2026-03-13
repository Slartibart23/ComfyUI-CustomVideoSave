"""
ComfyUI-CustomVideoSave
========================
Custom Node: Video Combine (Custom Path)

Erlaubt das Speichern von Videos in beliebigen Ordnern und Laufwerken,
nicht nur im ComfyUI output-Ordner.

Installation:
    Kopiere diesen Ordner nach: ComfyUI/custom_nodes/ComfyUI-CustomVideoSave/
    Starte ComfyUI neu.
"""

from .video_combine_custom_path import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = None

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
