# ABOUTME: Seed config: the bounded human bootstrap — people, canonical topic nodes and their initial
# ABOUTME: owners, org-wide authorities, and authors that are systems (bots) rather than people.
import json
from email.utils import parseaddr
from pathlib import Path
from typing import Self

import yaml
from pydantic import AliasChoices, BaseModel, Field


class PersonSeed(BaseModel):
  id: str = Field(..., description="Email address")
  name: str
  role: str | None = None
  external: bool = False
  owns: list[str] = Field(default_factory=list, validation_alias=AliasChoices("owns", "owns_topics"),
                          description="Topic keys this person owns from the start")


# canonical nodes the extractor should reuse, so versions of one topic land on one node
class TopicSeed(BaseModel):
  key: str = Field(..., description="Stable handle, e.g. 'hire_non_eu'")
  type: str = Field(..., description="Entity type from the schema")
  name: str
  description: str | None = None
  aliases: list[str] = Field(default_factory=list)


class Seed(BaseModel):
  people: list[PersonSeed] = Field(default_factory=list)
  topics: list[TopicSeed] = Field(default_factory=list)
  authorities: list[str] = Field(
    default_factory=list, description="Emails of people whose statements are authoritative on any topic")
  non_people: list[str] = Field(
    default_factory=list, description="Author addresses that are systems; never owners or asserters")

  # `people_file` (JSON or YAML list, relative to the seed file) keeps a shared people list reusable
  @classmethod
  def from_yaml(cls, path: str | Path) -> Self:
    path = Path(path)
    data = yaml.safe_load(path.read_text()) or {}
    if people_file := data.pop("people_file", None):
      extra = path.parent / people_file
      loaded = json.loads(extra.read_text()) if extra.suffix == ".json" else yaml.safe_load(extra.read_text())
      data["people"] = [*data.get("people", []), *loaded]
    return cls.model_validate(data)

  def is_non_person(self, ref: str) -> bool:
    addr = (parseaddr(ref)[1] or ref).strip().lower()
    return addr in {a.lower() for a in self.non_people}
