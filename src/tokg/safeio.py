import io
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 512 * 1024 * 1024
MAX_DEPTH = 64
MAX_NODES = 1_000_000
MAX_YAML_ALIASES = 256


def read_bytes(path: str | Path, limit: int = MAX_FILE_BYTES) -> bytes:
  path = Path(path)
  fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
  if not stat.S_ISREG(os.fstat(fd).st_mode):
    os.close(fd)
    raise ValueError(f"{path}: not a regular file")
  with os.fdopen(fd, "rb") as f:
    data = f.read(limit + 1)
  if len(data) > limit:
    raise ValueError(f"{path}: larger than {limit} bytes")
  return data


def read_text(path: str | Path, limit: int = MAX_FILE_BYTES) -> str:
  return io.TextIOWrapper(io.BytesIO(read_bytes(path, limit)), encoding="utf-8").read()


def check_shape(value: Any, depth_limit: int = MAX_DEPTH, node_limit: int = MAX_NODES) -> Any:
  stack, seen = [(value, 1)], 0
  while stack:
    item, depth = stack.pop()
    if (seen := seen + 1) > node_limit:
      raise ValueError(f"more than {node_limit} values")
    if isinstance(item, dict | list):
      if depth > depth_limit:
        raise ValueError(f"nested deeper than {depth_limit} levels")
      children = item.values() if isinstance(item, dict) else item
      stack.extend((c, depth + 1) for c in children)
  return value


class _GuardedLoader(yaml.SafeLoader):
  def __init__(self, stream: str) -> None:
    super().__init__(stream)
    self._depth = 0
    self._aliases = 0

  def flatten_mapping(self, node: Any) -> None:
    if any(key.tag == "tag:yaml.org,2002:merge" for key, _ in node.value):
      raise ValueError("YAML merge keys are not allowed")
    super().flatten_mapping(node)

  def compose_node(self, parent: Any, index: Any) -> Any:
    if self.check_event(yaml.AliasEvent):
      self._aliases += 1
      if self._aliases > MAX_YAML_ALIASES:
        raise ValueError(f"more than {MAX_YAML_ALIASES} YAML aliases")
    self._depth += 1
    if self._depth > MAX_DEPTH:
      raise ValueError(f"YAML nested deeper than {MAX_DEPTH} levels")
    try:
      return super().compose_node(parent, index)
    finally:
      self._depth -= 1


def load_yaml(text: str) -> Any:
  loader = _GuardedLoader(text)
  try:
    return check_shape(loader.get_single_data())
  finally:
    loader.dispose()


def load_json(text: str) -> Any:
  try:
    return check_shape(json.loads(text))
  except RecursionError as e:
    raise ValueError("JSON nested too deeply") from e


def write_text_atomic(path: str | Path, text: str) -> None:
  path = Path(path)
  fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
  try:
    with os.fdopen(fd, "w", encoding="utf-8") as f:
      f.write(text)
      f.flush()
      os.fsync(f.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
  except BaseException:
    Path(tmp).unlink(missing_ok=True)
    raise
