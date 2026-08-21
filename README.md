# ComfyUI-CustomVideoSave

**Video Save Plus (Custom Path) 🎬 — v2.0.1**

Saves a video **with its generated audio** (MP4, H.264/H.265 + AAC) to any folder
on any drive, plus a workflow PNG, an optional prompt `.txt` and optional frames.
Built for models with native audio (e.g. MiniMax) as well as classic
IMAGE + AUDIO workflows.

> v2 is a rewrite. The node name changed to `VideoSavePlus`; old
> `VideoCombineCustomPath` workflows must be re-wired once.

## Why v2

v1 wrote audio through `torchaudio.save` and silently dropped the audio track
when that failed (which it does on newer torchaudio versions). v2 pipes audio
as raw PCM and frames as raw RGB directly into ffmpeg — no torchaudio, no temp
PNG sequence — and **fails loudly** if an audio input cannot be processed.

## Files written

```
video_00012.mp4              ← video with audio
video_00012.png              ← first frame + embedded workflow (drag & drop into ComfyUI)
video_00012.txt              ← prompt (only if prompt_text is connected)
video_00012_last Frame.jpg   ← via button or save_frame option
video_00012_first Frame.jpg  ← via save_frame option
```

All files share the same base name; the counter is appended automatically.

## Inputs

| Input | Type | Notes |
|---|---|---|
| `video` | VIDEO (opt.) | Frames, audio and fps are taken from it |
| `images` | IMAGE (opt.) | Used when no VIDEO is connected |
| `audio` | AUDIO (opt.) | Overrides the audio of a VIDEO input |
| `prompt_text` | STRING (opt.) | Written as `name.txt` |
| `seed` | INT (opt.) | For the `%seed%` placeholder |
| `filename_prefix` | STRING | Supports subfolders and `%date%`, `%time%`, `%seed%`, `%date:yyyy-MM-dd%` |
| `custom_output_path` | STRING | Any folder; empty = ComfyUI output |
| `frame_rate` | FLOAT | Only for `images` input |
| `video_codec` | h264 / h265 | |
| `crf` | 0–51 (default 19) | Main quality control, lower = better |
| `preset` | ultrafast … veryslow | Speed vs. size, not quality |
| `pixel_format` | yuv420p / yuv444p | |
| `audio_bitrate` | 64–320 kbit/s | AAC |
| `save_workflow_png` | BOOLEAN | |
| `png_compression` | 0–9 | PNG is always lossless |
| `save_frame` | none / first / last / first+last / all | |
| `frame_format` | jpg / png | |
| `frame_quality` | 10–100 | JPEG quality |
| `copy_to_folder` | STRING | Target for "Save Training File" |

Every field has a tooltip in the node.

**Output:** `filepath` — the full path of the saved MP4.

## Buttons

- **Reveal in file manager** — opens Explorer/Finder with the last MP4 selected.
- **Open video (with sound)** — plays the last MP4 in the system player.
- **Save Last Frame** — writes `name_last Frame.jpg/png` from the frame kept in
  memory (lossless, instant). Falls back to a single ffmpeg seek if ComfyUI was
  restarted in between.
- **Save Training File** — copies the whole set (mp4 + png + txt + frames) to
  `copy_to_folder` with identical names.
- **Delete Last Generation** — deletes the whole set after confirmation.

After each run the node shows resolution, frame count, duration, size and an
audio status line (`✓ Audio: 48000 Hz stereo, 5.00 s` or `⚠ No audio`), plus an
inline player **with sound**.

Security: the server endpoints only operate on files this node saved during
the current session — never on arbitrary paths from the browser.

## Installation

### ComfyUI Manager
Search for **Video Save Plus** and install.

### Manual

```
cd ComfyUI/custom_nodes
git clone https://github.com/Slartibart23/ComfyUI-CustomVideoSave
```
Restart ComfyUI, then press Ctrl+F5 in the browser once.

Requirements: ffmpeg on the PATH (or `pip install imageio-ffmpeg`).
No torchaudio needed.

## License
MIT
