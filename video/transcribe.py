# ABOUTME: Transcribes the recorded VO parts with faster-whisper and dumps word-level timestamps
# ABOUTME: to audio/transcript.json, so subtitles and scene cuts follow the real recording.
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from faster_whisper import WhisperModel

parts = [Path(p) for p in sys.argv[1:]]
model = WhisperModel("medium.en", device="cpu", compute_type="int8", cpu_threads=12)
prev = Path("audio/transcript.json")
out = json.loads(prev.read_text()) if prev.exists() else {}
for p in parts:
  # decode with ffmpeg ourselves: faster-whisper's PyAV call breaks on the installed av version
  raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(p), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                       capture_output=True, check=True).stdout
  audio = np.frombuffer(raw, dtype=np.float32)
  segments, _ = model.transcribe(audio, word_timestamps=True, vad_filter=False, beam_size=5)
  words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)}
           for seg in segments for w in seg.words]
  out[p.stem] = words
  print(p.stem, " ".join(w["w"] for w in words), flush=True)
Path("audio").mkdir(exist_ok=True)
Path("audio/transcript.json").write_text(json.dumps(out, indent=1))
