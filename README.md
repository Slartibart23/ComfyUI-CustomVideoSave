# ComfyUI-CustomVideoSave

## Video Combine (Custom Path) 🎬

Eine Custom Node für ComfyUI, die Einzelbilder zu einem Video kombiniert –
mit der Möglichkeit, das Video in **jedem beliebigen Ordner** auf **jedem Laufwerk** zu speichern.

---

## Features

- **Custom Output Path** – Speichere Videos überall, z.B. `O:\#LORA_SUSANNE\##WAN\...`
- **Metadata (JSON)** – Alle Generation-Settings (Prompt, LoRA, Seed, CFG, Steps ...) als JSON neben dem Video
- **Preview** – Zeigt Vorschaubilder direkt in der ComfyUI-Oberfläche an
- **Workflow PNG** – Speichert den kompletten Workflow als PNG (erstes Frame mit eingebettetem Workflow). Per Drag & Drop in ComfyUI wieder ladbar!

---

## Installation

1. Kopiere den gesamten Ordner `ComfyUI-CustomVideoSave` nach:

   ```
   ComfyUI/custom_nodes/ComfyUI-CustomVideoSave/
   ```

2. Starte ComfyUI neu.

3. Die Node findest du unter: **video/custom → Video Combine (Custom Path) 🎬**

### Voraussetzungen

- **Python 3.11.9** (getestet)
- **ffmpeg** muss installiert und im PATH verfügbar sein
- **Pillow** (ist bei ComfyUI normalerweise dabei)
- **torchaudio** (optional, nur für Audio-Input nötig)

---

## Inputs

### Required

| Input                     | Typ     | Beschreibung                                                                 |
|---------------------------|---------|-----------------------------------------------------------------------------|
| `images`                  | IMAGE   | Die Frames als ComfyUI IMAGE-Tensor                                        |
| `frame_rate`              | FLOAT   | Framerate des Videos (1–120, Standard: 24)                                  |
| `filename_prefix`         | STRING  | Dateiname-Präfix (z.B. `mein_video`)                                       |
| `format`                  | COMBO   | `mp4 (h264)`, `mp4 (h265)`, `webm (vp9)`, `avi (rawvideo)`, `gif`         |
| `quality`                 | COMBO   | `high`, `medium`, `low`                                                     |
| `custom_output_path`      | STRING  | **Beliebiger Ausgabepfad** – leer = ComfyUI output                         |
| `create_folder_if_missing`| BOOLEAN | Ordner automatisch erstellen (Standard: Ja)                                 |

### Optional – Audio

| Input   | Typ   | Beschreibung                                      |
|---------|-------|---------------------------------------------------|
| `audio` | AUDIO | Optionaler Audio-Input (wird als AAC eingebettet)  |

### Optional – Metadata

| Input                | Typ    | Beschreibung                          |
|----------------------|--------|---------------------------------------|
| `save_metadata`      | BOOLEAN| Metadata als JSON speichern (Std: Ja) |
| `meta_model_name`    | STRING | Modellname (z.B. WAN2.1)              |
| `meta_positive_prompt`| STRING| Positiver Prompt                      |
| `meta_negative_prompt`| STRING| Negativer Prompt                      |
| `meta_lora_name`     | STRING | LoRA-Name                             |
| `meta_lora_strength` | FLOAT  | LoRA-Stärke (0–5)                     |
| `meta_steps`         | INT    | Sampling Steps                        |
| `meta_cfg`           | FLOAT  | CFG Scale                             |
| `meta_seed`          | INT    | Seed                                  |
| `meta_resolution`    | STRING | Auflösung als Text                    |
| `meta_custom_notes`  | STRING | Eigene Notizen (Multiline)            |

### Optional – Preview

| Input                | Typ    | Beschreibung                                    |
|----------------------|--------|-------------------------------------------------|
| `enable_preview`     | BOOLEAN| Vorschau in ComfyUI anzeigen (Std: Ja)          |
| `preview_max_frames` | INT    | Anzahl Preview-Frames (1–16, gleichmäßig verteilt)|

### Optional – Workflow PNG

| Input               | Typ    | Beschreibung                                           |
|---------------------|--------|-------------------------------------------------------|
| `save_workflow_png`  | BOOLEAN| Workflow als PNG speichern (Std: Ja)                   |

> Die Workflow-PNG enthält das erste Frame mit dem kompletten ComfyUI-Workflow in den PNG-Metadaten.
> Du kannst die PNG-Datei einfach per **Drag & Drop** in ComfyUI ziehen, um den Workflow wiederherzustellen!

## Output

| Output     | Typ    | Beschreibung                        |
|------------|--------|-------------------------------------|
| `filepath` | STRING | Vollständiger Pfad zur Video-Datei  |

---

## Was wird gespeichert?

Bei einem Lauf mit allen Optionen aktiviert entstehen z.B. diese Dateien:

```
O:\MeinOrdner\
├── output_video_00001.mp4              ← Das Video
├── output_video_00001_metadata.json    ← Metadata (Prompt, Seed, CFG, ...)
└── output_video_00001_workflow.png     ← Erstes Frame + eingebetteter Workflow
```

### Beispiel: metadata.json

```json
{
  "file_info": {
    "video_file": "output_video_00001.mp4",
    "created": "2026-03-13 14:30:00",
    "format": "mp4 (h264)",
    "quality": "high",
    "frame_rate": 24.0,
    "total_frames": 81,
    "frame_resolution": "1280x720",
    "duration_seconds": 3.38
  },
  "generation_settings": {
    "model": "WAN2.1",
    "positive_prompt": "a beautiful sunset over the ocean ...",
    "negative_prompt": "blurry, low quality ...",
    "lora": "Sus4nn3_WAN22_02",
    "lora_strength": 0.8,
    "steps": 30,
    "cfg": 7.0,
    "seed": 123456789,
    "resolution": "1280x720"
  },
  "notes": "Test mit neuer LoRA"
}
```

---

## Beispiel-Pfade für `custom_output_path`

```
O:\#LORA_SUSANNE\##WAN\Sus4nn3_WAN22_02\1280
D:\Videos\ComfyUI_Exports
C:\Users\Susanne\Desktop\Renders
\\NAS\share\videos
```

Wird das Feld **leer** gelassen, speichert die Node wie gewohnt in den ComfyUI-Output-Ordner.

---

## Dateistruktur

```
ComfyUI-CustomVideoSave/
├── __init__.py                      # Node-Registrierung
├── video_combine_custom_path.py     # Node-Logik
└── README.md                        # Diese Datei
```

---

## Hinweise

- Dateinamen werden automatisch nummeriert (`prefix_00001.mp4`, `prefix_00002.mp4` usw.)
- Bei GIFs wird automatisch eine Farbpalette berechnet für optimale Qualität
- Preview-Bilder landen im ComfyUI-Output unter `video_previews/`
- Temporäre Frame-Dateien werden nach dem Export aufgeräumt
- Im ComfyUI-Terminal siehst du den Fortschritt und den finalen Speicherpfad
