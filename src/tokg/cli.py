# ABOUTME: `tokg` CLI: ingest source folders, ask questions, serve the HTTP API or MCP, mint tokens.
# ABOUTME: --rig replays a scripted run with no LLM; --record captures a live LLM run into a rig.
import fcntl
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, NoReturn

import typer
import yaml
from rich.console import Console
from rich.markup import escape

from tokg.api.auth import Principal, Role, TokenRegistry, hash_token, new_token
from tokg.graph import KnowledgeGraph
from tokg.ingest import load_sources
from tokg.resolve import LLMResolver
from tokg.rig import Rig
from tokg.safeio import write_text_atomic
from tokg.schema import Schema
from tokg.seed import Seed
from tokg.store import MemoryStore

app = typer.Typer(no_args_is_help=True, help="TOKG: Temporal Ownership-Grounded Knowledge Graph.")
console = Console()

SchemaOpt = Annotated[Path, typer.Option("--schema", "-s", help="Domain schema YAML.")]
StoreOpt = Annotated[Path, typer.Option("--store", help="JSON snapshot to load from and save to.")]
SeedOpt = Annotated[Path | None, typer.Option("--seed", help="Seed YAML: people, topics, owners, authorities.")]
RigOpt = Annotated[Path | None, typer.Option("--rig", help="Rig YAML to replay a scripted, LLM-free run.")]
RecordOpt = Annotated[Path | None, typer.Option("--record", help="Rig YAML to record this live run into.")]
LLMResolveOpt = Annotated[bool, typer.Option("--llm-resolve", help="Resolve with the LLM, not rules.")]
ContextOpt = Annotated[list[str], typer.Option("--context", "-c", help="key=value, repeatable.")]
MAX_CONTEXT = 16
MAX_PERSON_ID = 256
STORE_IN_USE = "store is in use by a running server; stop it or ingest through the API"
STORE_LOCKED = "store is in use by another running tokg process"


def _parse_context(pairs: list[str]) -> dict[str, str]:
  if len(pairs) > MAX_CONTEXT:
    raise typer.BadParameter(f"at most {MAX_CONTEXT} --context entries", param_hint="--context")
  context = {}
  for pair in pairs:
    key, sep, value = pair.partition("=")
    if not sep or not key.strip() or len(key) > 64 or len(value) > 256:
      raise typer.BadParameter(f"expected key=value (key up to 64, value up to 256 characters), got "
                               f"'{pair[:80]}'", param_hint="--context")
    context[key] = value
  return context


@contextmanager
def _store_lock(store: Path) -> Iterator[bool]:
  fd = os.open(store.with_name(f"{store.name}.lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
  if not stat.S_ISREG(os.fstat(fd).st_mode):
    os.close(fd)
    raise typer.BadParameter(f"{store.name}.lock is not a regular file")
  try:
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
      yield False
    else:
      yield True
  finally:
    os.close(fd)


def _fail(message: str) -> NoReturn:
  console.print(f"[red]error:[/] {escape(message)}")
  raise typer.Exit(1)


@dataclass
class _Session:
  graph: KnowledgeGraph
  store: Path
  record: Path | None
  rig: Rig | None

  def save(self) -> None:
    self.graph.store.save(self.store)  # type: ignore[attr-defined]
    if self.record and self.rig:
      self.rig.save(self.record)


def _session(schema: Path, store: Path, seed: Path | None, rig: Path | None = None,
             record: Path | None = None, llm_resolve: bool = False) -> _Session:
  if rig and record:
    raise typer.BadParameter("--rig replays a run and --record captures one; pick one")
  s = Schema.from_yaml(schema)
  st = MemoryStore.load(store) if store.exists() else MemoryStore()
  sd = Seed.from_yaml(seed) if seed else None
  if rig is not None:
    return _Session(Rig.from_yaml(rig).graph(s, store=st, seed=sd), store, None, None)
  graph = KnowledgeGraph(s, store=st, seed=sd, resolver=LLMResolver() if llm_resolve else None)
  if record is None:
    return _Session(graph, store, None, None)
  recording = Rig.from_yaml(record) if record.exists() else Rig()
  return _Session(recording.record(graph), store, record, recording)


@app.command(help="Ingest a source file or folder (.eml, .json, frontmatter .md) into the store.")
def ingest(path: Annotated[Path, typer.Argument(help="File or folder of sources.")],
           schema: SchemaOpt, store: StoreOpt, seed: SeedOpt = None, rig: RigOpt = None,
           record: RecordOpt = None, llm_resolve: LLMResolveOpt = False) -> None:
  with _store_lock(store) as locked:
    if not locked:
      _fail(STORE_IN_USE)
    session = _session(schema, store, seed, rig, record, llm_resolve)
    report = session.graph.ingest(load_sources(path))
    session.save()
  for o in report.outcomes:
    if o.error:
      console.print(f"[yellow]skip[/] {escape(o.claim_id)}: {escape(o.error)}")
    elif o.decision:
      console.print(f"[green]{o.decision.action}[/] {escape(o.claim_id)}: {escape(o.decision.rationale)}")
  console.print(f"[bold]{len(report.source_ids)} sources, {len(report.outcomes)} claims[/] -> {escape(str(store))}")


@app.command(help="Ask a question against the graph.")
def ask(question: Annotated[str, typer.Argument(help="The question.")], schema: SchemaOpt, store: StoreOpt,
        seed: SeedOpt = None, rig: RigOpt = None, record: RecordOpt = None, context: ContextOpt = []) -> None:
  parsed = _parse_context(context)
  session = _session(schema, store, seed, rig, record)
  result = session.graph.ask(question, parsed)
  if session.record and session.rig:
    session.rig.save(session.record)
  console.print(result.answer.answer, markup=False, highlight=False)
  for c in result.answer.caveats:
    console.print(f"[yellow]! {escape(c)}[/]")
  if result.answer.contact_ids:
    console.print(f"[cyan]contacts:[/] {escape(', '.join(result.answer.contact_ids))}")


@app.command(help="Serve the HTTP API.")
def serve(schema: SchemaOpt, store: StoreOpt,
          tokens: Annotated[Path, typer.Option("--tokens", help="Token registry YAML.")],
          seed: SeedOpt = None, rig: RigOpt = None, llm_resolve: LLMResolveOpt = False,
          host: Annotated[str, typer.Option(help="Bind address.")] = "127.0.0.1",
          port: Annotated[int, typer.Option(help="Port.")] = 8000,
          cors: Annotated[list[str], typer.Option(help="Allowed CORS origin, repeatable.")] = []) -> None:
  import uvicorn

  from tokg.api import create_app

  with _store_lock(store) as locked:
    if not locked:
      _fail(STORE_LOCKED)
    session = _session(schema, store, seed, rig, llm_resolve=llm_resolve)
    uvicorn.run(create_app(session.graph, TokenRegistry.from_yaml(tokens), on_change=session.save,
                           cors_origins=cors), host=host, port=port)


@app.command(help="Run the MCP server over stdio, acting as one person.")
def mcp(schema: SchemaOpt, store: StoreOpt,
        user: Annotated[str, typer.Option("--user", help="Person node id the agent acts as.")],
        seed: SeedOpt = None, rig: RigOpt = None) -> None:
  from tokg.mcp import create_mcp

  with _store_lock(store) as locked:
    session = _session(schema, store, seed, rig)
    create_mcp(session.graph, user, on_change=session.save if locked else None,
               read_only=not locked).run(show_banner=False)


@app.command(help="Mint a token and add its hash to a token registry YAML.")
def token(person_id: Annotated[str, typer.Argument(help="Person node id, e.g. person:sophie-claes-foo-be")],
          tokens: Annotated[Path, typer.Option("--tokens", help="Token registry YAML to update.")],
          role: Annotated[Role, typer.Option(help="member or admin.")] = "member") -> None:
  if not person_id.strip() or len(person_id) > MAX_PERSON_ID or not person_id.isprintable() or "+" in person_id:
    raise typer.BadParameter(f"must be a printable person node id of up to {MAX_PERSON_ID} characters, "
                             "without '+'", param_hint="PERSON_ID")
  registry = TokenRegistry.from_yaml(tokens) if tokens.exists() else TokenRegistry()
  secret = new_token()
  registry.tokens[hash_token(secret)] = Principal(person_id=person_id, role=role)
  write_text_atomic(tokens, yaml.safe_dump(registry.model_dump(mode="json"), sort_keys=False))
  console.print(f"token for {escape(person_id)} ({role}), shown once:")
  console.print(secret, markup=False, highlight=False)


def main() -> None:
  app()
