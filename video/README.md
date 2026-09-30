# Demo video

[`recall_demo.mp4`](recall_demo.mp4) is the submitted demo video: 2:57, 1920×1080. Everything in it is generated from this folder, except the voice-over recordings:
- the stickman hook, the tech diagram and the business slides;
- the real Recall app answering from the rig;
- the subtitles, the music bed and the sound effects.

- [`storyboard.md`](storyboard.md): the shot list with timings, visuals, on-screen text and voice-over.
- [`script.md`](script.md) / [`vo_lines.txt`](vo_lines.txt): the voice-over script as handed to the voice actor, with timestamps.

## How it works

```
audio/recordings/*.m4a ──transcribe.py (faster-whisper, word timestamps)──► audio/transcript.json
                        ──build_cues.py (fix mishearings, split, snap to speech onsets)──► audio/cues.json
gen_audio.py (numpy: ambient music bed + heart-monitor SFX) ─┐
recordings, placed per section ──────────────────────────────┴─ffmpeg mix (music ducked under VO)──► audio/final_mix.wav

scenes/video.html (hook, tech, business: JS seek(t) timeline) ─┐
demo/recall.html (Recall app on the live tokg API, rig mode)  ─┴─render.py: headless Chromium, seek + screenshot
                                                                  every frame, beats timed from cues.json ──► out/recall_final.mp4
```

- **Deterministic rendering.** Every scene exposes `seek(t)`. `render.py` seeks each frame (30 fps), screenshots it and pipes the frames to ffmpeg, so there's no screen-recording jitter and every re-render is identical.
- **The product section is the real app.** `demo/recall.html` calls the real `tokg serve` API (`/ask`, `/nodes/{id}`, `/sources/{id}`) running the Foo BV rig, so the answers, history, pending items and owners on screen are real graph output.
- **The voice-over drives the timing.** Scene beats are keyed to `audio/cues.json`, so re-recording a line and re-running the cue and render steps re-times the video.
- **All the audio beyond the voice is ours.** `gen_audio.py` synthesises the music and sound effects, so there's no licensing risk.

## Re-render

```bash
# once: headless Chromium for Playwright
uv run --no-project --with playwright playwright install chromium-headless-shell

# 1. cues from the recordings (only needed when the VO changes)
cd video
uv run --no-project --with faster-whisper python transcribe.py audio/recordings/*.m4a
python3 build_cues.py
uv run --no-project --with numpy python gen_audio.py      # then mix audio/final_mix.wav as in build notes below

# 2. the Recall API on the Foo BV rig (from the repo root), plus a static server for this folder
uv run tokg ingest examples/data -s examples/foo/schema.yaml --seed examples/foo/seed.yaml \
  --store video/demo/foo.snapshot.json --rig examples/foo/rig.yaml
uv run tokg serve -s examples/foo/schema.yaml --seed examples/foo/seed.yaml --store video/demo/foo.snapshot.json \
  --rig examples/foo/rig.yaml --tokens video/demo/tokens.yaml --port 8765 --cors http://127.0.0.1:8766
python3 -m http.server 8766 --directory video

# 3. render (about 2.5 minutes)
cd video && uv run --no-project --with playwright python render.py all
```

`demo/tokens.yaml` and `demo/.token` hold a local API token for the recording, and snapshots and render output are generated. None of them are committed (see `.gitignore`). Create a token for any seeded person to render.

**Build notes: audio mix.** The recordings are placed at 0.0 (hook), 30.0 (product), 60.0 (tech, take p3) and 119.4 s (business). They're loudness-normalised to −16 LUFS. The music bed starts at 59 s at a low level and is sidechain-ducked under the VO. The monitor SFX sits at 27.0 s.
