# ABOUTME: Ingestors turn raw files into Source models: .eml emails, JSON source documents, and
# ABOUTME: markdown with YAML frontmatter whose `kind` picks the variant (meeting, wiki, document, ...).
import email
import email.policy
from abc import ABC
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

import yaml
from pydantic import TypeAdapter, ValidationError

from tokg.models import EmailSource, Source, slugify
from tokg.safeio import load_json, load_yaml, read_bytes, read_text

_SOURCE = TypeAdapter(Source)
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_FOLDER_FILES = 10_000


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
    root = path.resolve()
    found: list[Path] = []
    for p in path.rglob("*"):
      if p.suffix in self.suffixes and p.is_file() and p.resolve().is_relative_to(root):
        found.append(p)
        if len(found) > MAX_FOLDER_FILES:
          raise ValueError(f"{path}: more than {MAX_FOLDER_FILES} {'/'.join(self.suffixes)} files")
    return [s for p in sorted(found) if (s := self.parse(p)) is not None]


class EmailIngestor(Ingestor):
  suffixes = (".eml",)

  def parse(self, path: Path) -> Source | None:
    msg = email.message_from_bytes(read_bytes(path, MAX_SOURCE_BYTES), policy=email.policy.default)
    if not isinstance(msg, EmailMessage):
      raise ValueError(f"{path}: not an email message")
    try:
      timestamp = parsedate_to_datetime(str(msg["date"]))
    except (TypeError, ValueError) as e:
      raise ValueError(f"{path}: missing or invalid Date header") from e
    body = msg.get_body(preferencelist=("plain", "html"))
    try:
      content = body.get_content().strip() if body else ""
    except (LookupError, ValueError) as e:
      raise ValueError(f"{path}: undecodable body: {e}") from e
    recipients = [f"{n} <{a}>" if n else a
                  for n, a in getaddresses([*msg.get_all("to", []), *msg.get_all("cc", [])])]
    return EmailSource(
      id=f"email:{slugify(path.stem)}",
      title=str(msg.get("subject", path.stem)),
      author=str(msg.get("from", "unknown")),
      timestamp=timestamp,
      content=content,
      recipients=recipients,
      uri=str(path),
    )


# frontmatter keys map 1:1 onto the Source variant fields; `id` defaults to `<kind>:<file stem>`
class MarkdownIngestor(Ingestor):
  suffixes = (".md",)

  def parse(self, path: Path) -> Source | None:
    text = read_text(path, MAX_SOURCE_BYTES)
    if not text.startswith("---"):
      return None
    if len(parts := text.split("---", 2)) < 3:
      raise ValueError(f"{path}: unterminated frontmatter")
    _, front, body = parts
    try:
      meta = load_yaml(front) or {}
    except (yaml.YAMLError, ValueError) as e:
      raise ValueError(f"{path}: invalid frontmatter: {e}") from e
    if not isinstance(meta, dict):
      raise ValueError(f"{path}: frontmatter must be a mapping")
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
    text = read_text(path, MAX_SOURCE_BYTES)
    try:
      raw = load_json(text)
    except ValueError as e:
      raise ValueError(f"{path}: invalid JSON: {e}") from e
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
