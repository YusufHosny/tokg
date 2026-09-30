# ABOUTME: Debug helper: screenshots a seekable page at given times, e.g.
# ABOUTME: python snap.py "http://127.0.0.1:8766/demo/recall.html?q=hiring&script=1&frame=1" 3 9 out/snap
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

url, *times, prefix = sys.argv[1:]
token = (Path(__file__).parent / "demo/.token").read_text().strip()
with sync_playwright() as p:
  b = p.chromium.launch()
  page = b.new_page(viewport={"width": 1920, "height": 1080})
  page.on("console", lambda m: print("console:", m.text))
  page.on("pageerror", lambda e: print("pageerror:", e))
  page.goto(f"{url}#token={token}")
  page.evaluate("window.ready")
  for t in times:
    page.evaluate(f"window.seek({t})")
    page.screenshot(path=f"{prefix}_{t}.png")
  b.close()
