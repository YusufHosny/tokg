# ABOUTME: Builds audio/cues.json + subs_audio.srt from the whisper word timestamps of the recorded VO,
# ABOUTME: with text corrected to the script's spelling; unpunctuated takes are split on script sentences.
import json
import subprocess
import re
from pathlib import Path

# recorded part -> start offset (s) in the final video
RECORDED = {"recall-p1-real": 0.0, "recall-p1": 30.0, "recall-p3": 60.0, "recall-p4": 119.4}
# takes whisper returned without punctuation: split on these (as-recorded) script sentences
SENTENCES = {"recall-p1-real": [
  "This is Bob.", "Bob is a hiring manager at a Belgian tech company.", "Bob wants to hire a Brazilian developer.",
  "The wiki is from 2019.", "The AI assistant finds three versions of the process.",
  "A meeting note says the opposite.", "And nobody knows who owns it.", "Don't be like Bob.", "Bob went crazy."]}
# whisper mishearings -> script spelling, applied to the final cue text
FIXES = [(r"\brecall\b", "Recall"), (r"\bSarah\b", "Sara"), (r"\bToporo\b", "temporal"),
         (r"\bSupercede\b", "supersedes"), (r"\bOne is valid\b", "when it's valid"),
         (r"\bWhen is valid\b", "when it's valid"), (r"Fast API", "FastAPI"), (r"non -owner", "non-owner"),
         (r"\bTemporal Ownership Knowledge Graph\b", "temporal ownership knowledge graph"),
         (r"confirms what's known\.", "confirms what's known,"), (r"three things\.", "three things:"),
         (r"\btechs free\b", "text free"), (r"\bSD works\b", "SD Worx"), (r"\bindex knowledge\b", "indexed knowledge"),
         (r"\$20 billion", "twenty-billion-dollar"), (r"\bAI generated\b", "AI-generated"),
         (r"\bprivate cloud\b", "private-cloud"),
         (r"Recall, find it, understand it, trust it\.", "Recall. Find it. Understand it. Trust it.")]
MAX_CHARS = 100
ENDS = (".", "?", "!")


def _fmt(t: float) -> str:
  ms = int(round(t * 1000))
  return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def _norm(s: str) -> str:
  return re.sub(r"[^a-z0-9]", "", s.lower())


def _cue(words: list[dict], offset: float, text: str | None = None) -> dict:
  return {"start": round(words[0]["s"] + offset, 3), "end": round(words[-1]["e"] + offset + 0.15, 3),
          "text": text or " ".join(w["w"] for w in words)}


# consume transcript words until they spell the next script sentence
def _sentence_cues(words: list[dict], sentences: list[str], offset: float) -> list[dict]:
  cues, i = [], 0
  for sent in sentences:
    target, acc, start = _norm(sent), "", i
    while i < len(words) and len(acc) < len(target):
      acc += _norm(words[i]["w"])
      i += 1
    cues.append(_cue(words[start:i], offset, sent))
  return cues


def _split_cues(words: list[dict], offset: float) -> list[dict]:
  raw, cur = [], []
  for i, w in enumerate(words):
    cur.append(w)
    text = " ".join(x["w"] for x in cur)
    nxt = words[i + 1] if i + 1 < len(words) else None
    gap = nxt["s"] - w["e"] if nxt else 99
    clause_end = w["w"].endswith((",", ":", ";"))
    if nxt is None or len(text) >= MAX_CHARS or gap > 0.6 or w["w"].endswith(ENDS) or (clause_end and len(text) > 35):
      raw.append(_cue(cur, offset))
      cur = []
  # fold short fragments into a neighbour so nothing flashes: backwards when the previous cue is
  # mid-sentence, otherwise forwards into the next cue
  merged: list[dict] = []
  carry: dict | None = None
  for c in raw:
    if carry:
      c = {**c, "start": carry["start"], "text": carry["text"] + " " + c["text"]}
      carry = None
    if len(c["text"]) < 18 and merged and not merged[-1]["text"].endswith(ENDS):
      merged[-1] = {**merged[-1], "end": c["end"], "text": merged[-1]["text"] + " " + c["text"]}
    elif len(c["text"]) < 18 and c is not raw[-1] and not c["text"].endswith(ENDS):
      carry = c
    else:
      merged.append(c)
  return merged


def _finish(cues: list[dict]) -> list[dict]:
  prev_ended = True
  for c in cues:
    text = c["text"]
    for pat, rep in FIXES:
      text = re.sub(pat, rep, text)
    if prev_ended:
      text = text[0].upper() + text[1:]
    c["text"] = text
    prev_ended = text.endswith(ENDS)
  for a, b in zip(cues, cues[1:]):
    a["end"] = min(a["end"], b["start"] - 0.02)
  return cues


# whisper stretches a word's start across a preceding pause; snap cue starts in these takes to the
# next real speech onset (end of a silence) found by ffmpeg silencedetect
SNAP = {"recall-p1-real": Path("audio/recordings/recall-p1-real.m4a")}


def _onsets(path: Path) -> list[float]:
  log = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(path), "-af", "silencedetect=noise=-35dB:d=0.35",
                        "-f", "null", "-"], capture_output=True, text=True).stderr
  return [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]


def _snap(cues: list[dict], onsets: list[float], offset: float) -> list[dict]:
  for c in cues:
    local = c["start"] - offset
    if (nxt := next((o for o in onsets if o >= local - 0.05), None)) is not None and nxt - local < 3.0:
      c["start"] = round(max(local, nxt) + offset, 3)
  return cues


transcript = json.loads(Path("audio/transcript.json").read_text())
def _part_cues(part: str, offset: float) -> list[dict]:
  words = transcript[part]
  cues = _sentence_cues(words, SENTENCES[part], offset) if part in SENTENCES else _split_cues(words, offset)
  return _snap(cues, _onsets(SNAP[part]), offset) if part in SNAP else cues


cues = _finish([c for part, offset in RECORDED.items() for c in _part_cues(part, offset)])
Path("audio/cues.json").write_text(json.dumps(cues, indent=1))
Path("subs_audio.srt").write_text("\n".join(f"{i}\n{_fmt(c['start'])} --> {_fmt(c['end'])}\n{c['text']}\n"
                                            for i, c in enumerate(cues, 1)))
for c in cues:
  print(f"{c['start']:7.2f}-{c['end']:7.2f}  {c['text']}")
