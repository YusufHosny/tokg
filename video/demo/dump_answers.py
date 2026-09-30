# ABOUTME: Replays the Foo BV rig through the real tokg library and dumps the three scenario
# ABOUTME: AskResults as JSON, so the video's product scenes show real graph output.
import json
from pathlib import Path

from tokg.rig import Rig
from tokg.schema import Schema
from tokg.seed import Seed
from tokg.store import MemoryStore

MAIN = Path(__file__).resolve().parents[2] / "examples" / "foo"
HERE = Path(__file__).parent
QUESTIONS = {
  "hiring": "How do I hire a non-EU citizen in Belgium?",
  "sick": "An employee called in sick for just today. Do they need to upload a doctor's note, or is an email notification enough?",
  "hardware": "Can I buy a monitor on Amazon and expense up to €500?",
}

graph = Rig.from_yaml(MAIN / "rig.yaml").graph(
  Schema.from_yaml(MAIN / "schema.yaml"), store=MemoryStore.load(HERE / "foo.snapshot.json"),
  seed=Seed.from_yaml(MAIN / "seed.yaml"))
out = {k: graph.ask(q, {"country": "BE"}).model_dump(mode="json") for k, q in QUESTIONS.items()}
(HERE / "answers.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
for k, v in out.items():
  print("=====", k, "\n", v["answer"]["answer"], "\ncaveats:", v["answer"]["caveats"], "\ncontacts:", v["answer"]["contact_ids"])
  print("views:", [(vw["node"]["id"], len(vw.get("current", []))) for vw in v.get("views", [])])
