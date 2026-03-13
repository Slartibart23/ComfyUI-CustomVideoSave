# ComfyUI-CustomVideoSave

## Video Combine (Custom Path) 🎬

Eine Custom Node für ComfyUI, die Einzelbilder zu einem Video kombiniert –
mit der Möglichkeit, das Video in **jedem beliebigen Ordner** auf **jedem Laufwerk** zu speichern.

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

| Input                     | Typ     | Beschreibung                                                                 |
|---------------------------|---------|-----------------------------------------------------------------------------|
| `images`                  | IMAGE   | Die Frames als ComfyUI IMAGE-Tensor (Pflicht)                              |
| `frame_rate`              | FLOAT   | Framerate des Videos (1–120, Standard: 24)                                  |
| `filename_prefix`         | STRING  | Dateiname-Präfix (z.B. `mein_video`)                                       |
| `format`                  | COMBO   | `mp4 (h264)`, `mp4 (h265)`, `webm (vp9)`, `avi (rawvideo)`, `gif`         |
| `quality`                 | COMBO   | `high`, `medium`, `low`                                                     |
| `custom_output_path`      | STRING  | **Beliebiger Ausgabepfad** – leer = ComfyUI output                         |
| `create_folder_if_missing`| BOOLEAN | Ordner automatisch erstellen wenn er nicht existiert (Standard: Ja)         |
| `audio` *(optional)*      | AUDIO   | Optionaler Audio-Input (wird als AAC in MP4 eingebettet)                    |

## Output

| Output     | Typ    | Beschreibung                        |
|------------|--------|-------------------------------------|
| `filepath` | STRING | Vollständiger Pfad zur erzeugten Datei |

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

- Dateinamen werden automatisch nummeriert (`prefix_00001.mp4`, `prefix_00002.mp4` usw.),
  damit keine Dateien überschrieben werden.
- Bei GIFs wird automatisch eine Farbpalette berechnet für optimale Qualität.
- Temporäre Frame-Dateien werden nach dem Export aufgeräumt.
- Im ComfyUI-Terminal siehst du den Fortschritt und den finalen Speicherpfad.
