# ABOUTME: Debug helper: pulls frames at given times from a video and tiles them into a contact sheet.
# ABOUTME: python frames.py out/recall_v3.mp4 out/v3check 12 35 42 ...
import subprocess
import sys
from pathlib import Path

from PIL import Image

video, outdir, *times = sys.argv[1:]
out = Path(outdir)
out.mkdir(parents=True, exist_ok=True)
paths = []
for t in times:
  p = out / f"f_{t}.png"
  subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", t, "-i", video, "-frames:v", "1", str(p)], check=True)
  paths.append(p)
for k in range(0, len(paths), 6):
  sheet = Image.new("RGB", (960 * 2, 540 * 3), "gray")
  for i, p in enumerate(paths[k:k + 6]):
    sheet.paste(Image.open(p).resize((960, 540)), ((i % 2) * 960, (i // 2) * 540))
  sheet.save(out / f"sheet{k // 6}.png")
print(len(paths), "frames")
