# ComfyUI-CustomVideoSave

**Video Save Plus (Custom Path) 🎬 — v2.1.0**

Saves a video **with its generated audio** (MP4, H.264/H.265 + AAC) to any folder
on any drive, plus a workflow PNG, an optional workflow JSON, an optional prompt
`.txt` and optional frames. Built for models with native audio (Grok Imagine,
MiniMax, …) as well as classic IMAGE + AUDIO workflows.

## Three ways to feed it

| Input | What happens |
|---|---|
| `video` (VIDEO) | Frames, audio and fps are taken from the object and **re-encoded** with the quality settings. |
| `images` + `audio` | Classic: frames piped as raw RGB, audio as raw PCM into ffmpeg. |
| `source_video_path` (v2.1) | **Passthrough:** a finished MP4 (e.g. `video_path` of *Grok Imagine Video*) is copied 1:1 — no re-encoding, no quality loss, original audio kept. Connect `audio` as well and only the soundtrack is replaced (video stream copied). Codec/CRF/preset/pixel_format are ignored. |

Typical Grok wiring:

```
[Grok Imagine Video] --video_path--> source_video_path
                     --prompt------> prompt_text          (name.txt)
                     --frames------> images  (optional: lossless first/last frame, PNG)
```

## Files written

```
video_00012.mp4              ← video with audio
video_00012.png              ← first frame + embedded workflow (drag & drop into ComfyUI)
video_00012.json             ← workflow as JSON (save_workflow_json)
video_00012.txt              ← prompt (only if prompt_text is connected)
video_00012_last Frame.jpg   ← via button or save_frame option
video_00012_first Frame.jpg  ← via save_frame option
```

All files share the same base name; the counter is appended automatically.

## Inputs

| Input | Type | Notes |
|---|---|---|
| `video` | VIDEO (opt.) | Frames, audio and fps are taken from it |
| `images` | IMAGE (opt.) | Used when no VIDEO is connected; in passthrough only for PNG/frames |
| `audio` | AUDIO (opt.) | Overrides the audio of a VIDEO input / replaces the passthrough soundtrack |
| `source_video_path` | STRING (opt.) | Passthrough of a finished MP4 (connect or type a path) |
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
| `save_workflow_json` | BOOLEAN | new in 2.1 |
| `png_compression` | 0–9 | PNG is always lossless |
| `save_frame` | none / first / last / first+last / all | `all` needs frames |
| `frame_format` | jpg / png | |
| `frame_quality` | 10–100 | JPEG quality |
| `copy_to_folder` | STRING | Target for "Save Training File" |

Every field has an English tooltip in the node.

**Output:** `filepath` — the full path of the saved MP4.

## Buttons

- **Reveal in file manager** — opens Explorer/Finder with the last MP4 selected.
- **Open video (with sound)** — plays the last MP4 in the system player.
- **Save Last Frame** — writes `name_last Frame.jpg/png` from the frame kept in
  memory (lossless, instant); in passthrough mode or after a restart it is
  extracted from the MP4 with one ffmpeg seek.
- **Save Training File** — copies the whole set (mp4 + png + json + txt + frames) to
  `copy_to_folder` with identical names.
- **Delete Last Generation** — deletes the whole set after confirmation.

After each run the node shows resolution, frame count, duration, size, whether it
was a passthrough, and an audio status line (`✓ Audio: 48000 Hz stereo, 5.00 s` /
`✓ Audio: 44100 Hz stereo (original track kept)` / `⚠ No audio`), plus an inline
player **with sound**.

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

Requirements: ffmpeg on the PATH (or `pip install imageio-ffmpeg`); ffprobe
(ships with ffmpeg) is used for passthrough status. No torchaudio needed.

## License
MIT
