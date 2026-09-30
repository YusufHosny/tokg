"""Check that every mock data file matches the schema.

Run from the repo root: python examples/validate_data.py
"""
import json
import sys
from pathlib import Path

from schema import Person, SourceDocument

DATA = Path(__file__).parent / "data"

people = [Person.model_validate(p) for p in json.loads((DATA / "people.json").read_text())]
person_ids = {p.id for p in people}

errors = []
docs = []
for path in sorted(DATA.glob("*/*.json")):
    try:
        doc = SourceDocument.model_validate_json(path.read_text())
    except Exception as e:
        errors.append(f"{path.name}: {e}")
        continue
    if path.stem != doc.id:
        errors.append(f"{path.name}: id '{doc.id}' does not match the file name")
    if path.parent.name != doc.source.value:
        errors.append(f"{path.name}: source '{doc.source.value}' but stored in {path.parent.name}/")
    docs.append(doc)

ids = [d.id for d in docs]
if len(ids) != len(set(ids)):
    errors.append("duplicate document ids")

# Authors that are not people (meeting bot, newsletters) are fine, but list them
# so extraction never uses them as an owner.
non_people = sorted({d.author for d in docs} - person_ids)

print(f"{len(docs)} documents, {len(people)} people")
print("authors that are not people:", ", ".join(non_people))
if errors:
    print("\n".join(errors))
    sys.exit(1)
print("OK")
