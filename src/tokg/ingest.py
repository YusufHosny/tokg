# ABOUTME: Ingestors turn raw files into Source models: .eml emails, JSON source documents, and
# ABOUTME: markdown with YAML frontmatter whose `kind` picks the variant (meeting, wiki, document, ...).
import email
import email.policy
import json
from abc import ABC
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from tokg.models import EmailSource, Source, slugify

_SOURCE = TypeAdapter(Source)


class Ingestor(ABC):
  suffixes: tuple[str, ...] = ()

  # None means "this file is not a source" (e.g. a README next to the data); malformed sources raise
  def parse(self, path: Path) -> Source | None:
    raise NotImplementedError("parse should be implemented by subclasses")

  def load_file(self, path: Path) -> Source:
    if (source := self.parse(path)) is None:
      raise ValueError(f"{path}: not a source document")
    return source

  # folder scans skip non-sources; an explicitly given file must be one
  def load(self, path: str | Path) -> list[Source]:
    path = Path(path)
    if not path.is_dir():
      return [self.load_file(path)]
    files = sorted(p for p in path.rglob("*") if p.suffix in self.suffixes)
    return [s for p in files if (s := self.parse(p)) is not None]


class EmailIngestor(Ingestor):
  suffixes = (".eml",)

  def parse(self, path: Path) -> Source | None:
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    body = msg.get_body(preferencelist=("plain", "html"))
    recipients = [f"{n} <{a}>" if n else a
                  for n, a in getaddresses([*msg.get_all("to", []), *msg.get_all("cc", [])])]
    return EmailSource(
      id=f"email:{slugify(path.stem)}",
      title=str(msg.get("subject", path.stem)),
      author=str(msg.get("from", "unknown")),
      timestamp=parsedate_to_datetime(str(msg["date"])),
      content=body.get_content().strip() if body else "",
      recipients=recipients,
      uri=str(path),
    )


# frontmatter keys map 1:1 onto the Source variant fields; `id` defaults to `<kind>:<file stem>`
class MarkdownIngestor(Ingestor):
  suffixes = (".md",)

  def parse(self, path: Path) -> Source | None:
    text = path.read_text()
    if not text.startswith("---"):
      return None
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front) or {}
    if "date" in meta and "timestamp" not in meta:
      meta["timestamp"] = meta.pop("date")
    meta.setdefault("id", f"{meta.get('kind', 'document')}:{slugify(path.stem)}")
    meta.setdefault("uri", str(path))
    try:
      return _SOURCE.validate_python({**meta, "content": body.strip()})
    except ValidationError as e:
      raise ValueError(f"{path}: invalid frontmatter: {e}") from e


# one object per file: {id, source, timestamp, author, recipients, title, body}; `source` is the
# kind. Top-level arrays (e.g. a people.json next to the data) are not sources.
class JsonIngestor(Ingestor):
  suffixes = (".json",)

  def parse(self, path: Path) -> Source | None:
    raw = json.loads(path.read_text())
    if not isinstance(raw, dict):
      return None
    doc = dict(raw)
    doc["kind"] = doc.pop("source", doc.get("kind"))
    doc["content"] = doc.pop("body", doc.get("content"))
    doc.setdefault("uri", str(path))
    try:
      return _SOURCE.validate_python(doc)
    except ValidationError as e:
      raise ValueError(f"{path}: invalid source document: {e}") from e


INGESTORS: list[Ingestor] = [EmailIngestor(), MarkdownIngestor(), JsonIngestor()]


# chronological order matters: facts are resolved against what the graph already knows
def load_sources(path: str | Path, ingestors: list[Ingestor] | None = None) -> list[Source]:
  path = Path(path)
  sources = [s for ingestor in ingestors or INGESTORS
             if path.is_dir() or path.suffix in ingestor.suffixes
             for s in ingestor.load(path)]
  return sorted(sources, key=lambda s: s.timestamp)
