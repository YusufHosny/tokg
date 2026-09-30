# ABOUTME: Debug helper: snapshots the three Recall product segments with the exact render options/beats.
import json
import subprocess
import urllib.parse as u

import render

T = render.beats(render.load_cues())
segs = {s.page: s for s in render.segments(T) if s.page != "scenes"}
shots = {"hiring": ["7.5", "10.2", "12", "14.5"], "sick": ["3.8"], "hardware": ["6.2"]}
for k, ts in shots.items():
  beats = "&beats=" + u.quote(json.dumps(segs[k].beats))
  url = f"http://127.0.0.1:8766/demo/recall.html?q={k}&script=1&frame=1{render.RECALL_OPTS[k]}{beats}"
  subprocess.run(["python", "snap.py", url, *ts, f"out/snaps/v4{k}"], check=True)
