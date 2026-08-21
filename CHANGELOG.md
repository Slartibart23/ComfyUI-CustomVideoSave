# Changelog

## 2.0.1
- Publishing to the Comfy Registry via GitHub Action (pyproject PublisherId, .comfyignore)
- No functional changes

## 2.0.0
- Rewrite: node is now `VideoSavePlus` ("Video Save Plus (Custom Path) 🎬")
- Fix: audio no longer silently dropped — raw PCM piped to ffmpeg, no torchaudio;
  malformed audio input now raises a clear error
- New: VIDEO input (native-audio models such as MiniMax), IMAGE + AUDIO still supported
- New: precise quality controls with tooltips (codec, CRF default 19, preset,
  pixel format, audio bitrate, PNG compression)
- New: prompt `.txt` sidecar, `%date%` / `%time%` / `%seed%` placeholders
- New: frames as `_first Frame` / `_last Frame` / all, jpg or png
- New: buttons — Reveal, Open video, Save Last Frame, Save Training File,
  Delete Last Generation
- New: audio status line and inline video preview with sound
- Removed: metadata JSON, preview PNGs in `video_previews/`, gif/webm/avi formats

## 1.x
- Video Combine (Custom Path) with metadata JSON and workflow PNG
