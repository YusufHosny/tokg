# ABOUTME: Renders out/recall_final.mp4 frame-by-frame: scene pages and the live Recall app are seeked
# ABOUTME: per frame in headless Chromium, subtitles are drawn in-page, then the real VO is muxed.
# Needs the tokg API on :8765 (rig) and a static server for this folder on :8766, see README.
import json
import re
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
BASE = "http://127.0.0.1:8766"
FPS = 30
WORKERS = 6
OUT = HERE / "out"
CHUNKS = OUT / "chunks"


# ------------------------------------------------------------------------------------------------
# timeline: every beat is anchored to a VO cue, so re-recording only means a new cues.json


def load_cues() -> list[dict]:
  path = HERE / "audio/cues.json"
  if path.exists():
    return json.loads(path.read_text())
  cues = []
  for line in (HERE / "vo_lines.txt").read_text().splitlines():
    if m := re.match(r"\[(\d+):(\d+)–(\d+):(\d+)\] (.*)", line):
      a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
      if m[5] != "(silence)":
        cues.append({"start": a, "end": b, "text": m[5].replace(" / ", " ").replace("/", "")})
  return cues


def beats(cues: list[dict]) -> dict[str, float]:
  # start of the first cue matching `pat`; `at=True` interpolates to the match inside the cue text
  def find(pat: str, at: bool = False, default: float | None = None) -> float:
    for c in cues:
      if m := re.search(pat, c["text"], re.I):
        if not at:
          return c["start"]
        return c["start"] + (c["end"] - c["start"]) * m.start() / max(1, len(c["text"]))
    if default is None:
      raise KeyError(f"no cue matches {pat!r}")
    return default

  T = {
    "hookJob": find(r"hiring manager at"), "hookWants": find(r"wants to hire"), "flood": find(r"wiki is from"),
    "floodOwner": find(r"buried|nobody knows"), "dont": find(r"don't be like"), "crazy": find(r"went crazy"),
    "again": find(r"this time"), "saraStart": find(r"\bSara\b|\bNina\b"), "tomStart": find(r"\bTom learns\b|\bLucas\b"),
    "tech": find(r"under the hood"), "problem": find(r"companies now"), "q1": find(r"what's current", True),
    "q2": find(r"what applies"), "q3": find(r"whose word", True), "ingest": find(r"step one"),
    "resolve": find(r"step two"), "confirm": find(r"confirms what"), "supersede": find(r"supersedes an older"),
    "escalate": find(r"non-owner"), "fact": find(r"three things"), "serve": find(r"step three"),
    "storage": find(r"in memory"), "finale": find(r"answers you can trust"), "biz": find(r"why now"),
    "market": find(r"we start(ed)? where"), "model": find(r"we sell"), "oversight": find(r"fixed oversight", True),
    "roadmap": find(r"next come"), "end": find(r"^recall\b"),
  }
  T["black"] = T["dont"] - 0.02
  T["hospital"] = T["crazy"] + 0.59
  T["againEnd"] = T["again"] + 3.4
  T["saraEnd"] = T["saraStart"] + 2.0
  T["tomEnd"] = T["tomStart"] + 2.0
  T["total"] = 177.0
  T["_hireAnswer"] = find(r"current (single permit )?process")
  T["_hireHistory"] = find(r"not the .*wiki", True)
  T["_hireCases"] = find(r"previous hires|Camila")
  T["_hireOwner"] = find(r"one person who owns", True)
  return T


@dataclass
class Segment:
  page: str      # "scenes" or a recall question key
  start: float
  end: float
  beats: dict[str, float] | None = None


def segments(T: dict[str, float]) -> list[Segment]:
  a, s0, t0 = T["againEnd"], T["saraEnd"], T["tomEnd"]
  hire = {"typeStart": 0.15, "typeEnd": 0.95, "submit": 34.6 - a, "answer": 35.2 - a,
          "history": T["_hireHistory"] - a, "pending": T["_hireHistory"] - a + 0.9,
          "cases": T["_hireCases"] - a + 0.1, "source": T["_hireCases"] - a + 1.9,
          "sourceClose": T["_hireOwner"] - a - 0.15, "owner": T["_hireOwner"] - a, "end": T["saraStart"] - a}

  def quick(dur: float) -> dict[str, float]:
    return {"typeStart": 0.1, "typeEnd": 1.1, "submit": 1.25, "answer": 1.45, "history": 2.0, "pending": 2.6,
            "cases": 3.0, "source": 999, "sourceClose": 999, "owner": dur - 1.1, "end": dur}

  return [
    Segment("scenes", 0, a),
    Segment("hiring", a, T["saraStart"], hire),
    Segment("scenes", T["saraStart"], s0),
    Segment("sick", s0, T["tomStart"], quick(T["tomStart"] - s0)),
    Segment("scenes", T["tomStart"], t0),
    Segment("hardware", t0, T["tech"], quick(T["tech"] - t0)),
    Segment("scenes", T["tech"], T["total"]),
  ]


RECALL_OPTS = {
  "hiring": "&cases=ravi|camila&histlabel=2019%20wiki&ctx2=region%20%3D%20Flanders&title=Single%20permit%2C%20Flanders%20%28non-EU%20hire%29&drawer=left",
  "sick": "&compact=1&hist=%5B%7B%22i%22%3A%200%2C%20%22date%22%3A%20%22Client%20rule%22%2C%20%22title%22%3A%20%22Client%27s%20old%20doctor%27s-note%20rule%20%28Art.%207.3%29%22%2C%20%22sub%22%3A%20%22Medical%20certificate%20within%2048%20hours%20for%20every%20absence%2C%20even%20one%20day.%22%2C%20%22badge%22%3A%20%22Superseded%20by%20the%20new%20sick-leave%20law%22%7D%5D",
  "hardware": "&compact=1&ownerrole=1&hist=%5B%7B%22i%22%3A%201%2C%20%22date%22%3A%20%22Old%20budget%22%2C%20%22title%22%3A%20%22Old%20%5Cu20ac500%20Amazon%20budget%22%2C%20%22sub%22%3A%20%22Buy%20peripherals%20on%20Amazon%20and%20expense%20up%20to%20%5Cu20ac500%20a%20year.%22%2C%20%22badge%22%3A%20%22Gone%3A%20order%20through%20the%20new%20IT%20portal%22%7D%5D",
}

SUB_CSS = """
#__sub { position: fixed; left: 0; right: 0; bottom: 56px; display: flex; justify-content: center; z-index: 999; pointer-events: none; }
#__sub span { max-width: 1500px; text-align: center; font-family: Inter, sans-serif; font-weight: 600; font-size: 38px; line-height: 1.3;
  color: #fff; background: rgba(8, 12, 24, .78); padding: 10px 26px; border-radius: 14px; }
#__sub span:empty { display: none; }
"""


# ------------------------------------------------------------------------------------------------
# rendering


def _render_chunk(args: tuple[int, int, int]) -> str:
  from playwright.sync_api import sync_playwright

  idx, f0, f1 = args
  cues = load_cues()
  T = beats(cues)
  segs = segments(T)
  token = (HERE / "demo/.token").read_text().strip()
  out = CHUNKS / f"chunk_{idx:02}.mp4"
  enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", "-r", str(FPS), str(out)],
                         stdin=subprocess.PIPE)
  with sync_playwright() as p:
    browser = p.chromium.launch()
    pages = {}

    def page_for(seg: Segment):
      key = seg.page if seg.page == "scenes" else f"{seg.page}:{seg.start}"
      if key in pages:
        return pages[key]
      pg = browser.new_page(viewport={"width": 1920, "height": 1080})
      pg.on("pageerror", lambda e: print(f"[chunk {idx}] pageerror:", e, file=sys.stderr))
      if seg.page == "scenes":
        pg.add_init_script(f"window.__T = {json.dumps(T)};")
        pg.goto(f"{BASE}/scenes/video.html")
      else:
        pg.add_init_script(f"window.__beats = {json.dumps(seg.beats)};")
        pg.goto(f"{BASE}/demo/recall.html?q={seg.page}&script=1&frame=1{RECALL_OPTS[seg.page]}#token={token}")
      pg.evaluate("window.ready")
      pg.add_style_tag(content=SUB_CSS)
      pg.evaluate("document.body.insertAdjacentHTML('beforeend', '<div id=\"__sub\"><span></span></div>')")
      pages[key] = pg
      return pg

    for f in range(f0, f1):
      t = f / FPS
      seg = next(s for s in segs if s.start <= t < s.end) if t < segs[-1].end else segs[-1]
      pg = page_for(seg)
      local = t if seg.page == "scenes" else t - seg.start
      cue = next((c["text"] for c in cues if c["start"] <= t < c["end"]), "")
      pg.evaluate("([t, s]) => { window.seek(t); document.querySelector('#__sub span').textContent = s; }", [local, cue])
      enc.stdin.write(pg.screenshot(type="jpeg", quality=93))
    browser.close()
  enc.stdin.close()
  enc.wait()
  return str(out)


def render() -> Path:
  CHUNKS.mkdir(parents=True, exist_ok=True)
  T = beats(load_cues())
  total = int(T["total"] * FPS)
  step = -(-total // WORKERS)
  jobs = [(i, i * step, min(total, (i + 1) * step)) for i in range(WORKERS)]
  with ProcessPoolExecutor(WORKERS) as ex:
    chunks = list(ex.map(_render_chunk, jobs))
  listing = CHUNKS / "list.txt"
  listing.write_text("".join(f"file '{Path(c).name}'\n" for c in chunks))
  silent = OUT / "recall_final_silent.mp4"
  subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(silent)], check=True)
  return silent


def mux(silent: Path) -> Path:
  final = OUT / "recall_final.mp4"
  audio = HERE / "audio/final_mix.wav"
  subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(silent), "-i", str(audio), "-map", "0:v", "-map", "1:a",
                  "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", "177", "-movflags", "+faststart", str(final)], check=True)
  return final


def gif(src: Path) -> Path:
  T = beats(load_cues())
  start = segments(T)[1].beats["answer"] - 0.3
  out = OUT / "demo.gif"
  vf = "fps=12,scale=1280:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4"
  subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", "10", "-i", str(OUT / "recall_v3_nosub_product.mp4"),
                  "-vf", vf, "-loop", "0", str(out)], check=True)
  return out


def product_clip() -> Path:
  # the GIF uses a subtitle-free render of the hiring segment, so it reads without audio
  from playwright.sync_api import sync_playwright

  T = beats(load_cues())
  seg = segments(T)[1]
  token = (HERE / "demo/.token").read_text().strip()
  out = OUT / "recall_v3_nosub_product.mp4"
  enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                          "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
  with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1920, "height": 1080})
    pg.add_init_script(f"window.__beats = {json.dumps(seg.beats)};")
    pg.goto(f"{BASE}/demo/recall.html?q=hiring&script=1&frame=1{RECALL_OPTS['hiring']}#token={token}")
    pg.evaluate("window.ready")
    for f in range(int((seg.end - seg.start) * FPS)):
      pg.evaluate(f"window.seek({f / FPS})")
      enc.stdin.write(pg.screenshot(type="jpeg", quality=93))
    b.close()
  enc.stdin.close()
  enc.wait()
  return out


if __name__ == "__main__":
  cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
  if cmd == "beats":
    print(json.dumps(beats(load_cues()), indent=1))
  if cmd in ("render", "all"):
    print("rendered", render())
  if cmd in ("mux", "all"):
    print("muxed", mux(OUT / "recall_final_silent.mp4"))
  if cmd in ("gif", "all"):
    product_clip()
    print("gif", gif(OUT / "recall_v3.mp4"))
