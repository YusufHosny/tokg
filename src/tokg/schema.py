# ABOUTME: Declarative domain schema: entity types (with attributes), relation types and context
# ABOUTME: dimensions. Loaded from YAML per use case; tokg itself stays domain-agnostic.
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator

from tokg.safeio import load_yaml, read_text


class AttributeSpec(BaseModel):
  name: str = Field(..., description="Attribute key, e.g. 'procedure'")
  description: str = Field("", description="What a value of this attribute states")


class EntityType(BaseModel):
  name: str = Field(..., description="Entity type name, e.g. 'Process'")
  description: str = Field("", description="What kind of thing this entity is")
  attributes: list[AttributeSpec] = Field(default_factory=list)

  def attribute(self, name: str) -> AttributeSpec | None:
    return next((a for a in self.attributes if a.name == name), None)


class RelationType(BaseModel):
  name: str = Field(..., description="Relation name, e.g. 'example_of'")
  description: str = ""
  source: list[str] = Field(..., description="Entity types allowed as the relation subject")
  target: list[str] = Field(..., description="Entity types allowed as the relation target")


# a dimension a fact can be scoped to; `entity` makes values references to nodes of that type
# (e.g. client=Acme → the Client node), which lets views surface that node's owner as a contact
class ContextDimension(BaseModel):
  name: str = Field(..., description="Context key, e.g. 'country'")
  description: str = ""
  entity: str | None = Field(default=None, description="Entity type the values refer to, if any")


class Schema(BaseModel):
  name: str
  description: str = ""
  owner_type: str = "Person"
  entities: list[EntityType] = Field(default_factory=list)
  relations: list[RelationType] = Field(default_factory=list)
  context: list[ContextDimension] = Field(default_factory=list)

  @model_validator(mode="after")
  def _check(self) -> Self:
    if self.entity(self.owner_type) is None:
      self.entities.append(EntityType(name=self.owner_type, description="A person who can own knowledge"))
    for kind, names in (("entity", [e.name for e in self.entities]),
                        ("relation", [r.name for r in self.relations]),
                        ("context", [c.name for c in self.context])):
      if dupes := {n for n in names if names.count(n) > 1}:
        raise ValueError(f"duplicate {kind} names: {sorted(dupes)}")
    for r in self.relations:
      if unknown := [t for t in (*r.source, *r.target) if self.entity(t) is None]:
        raise ValueError(f"relation '{r.name}' references unknown entity types {unknown}")
    for c in self.context:
      if c.entity is not None and self.entity(c.entity) is None:
        raise ValueError(f"context '{c.name}' references unknown entity type '{c.entity}'")
    return self

  @classmethod
  def from_yaml(cls, path: str | Path) -> Self:
    return cls.model_validate(load_yaml(read_text(path)))

  def entity(self, name: str) -> EntityType | None:
    return next((e for e in self.entities if e.name == name), None)

  def relation(self, name: str) -> RelationType | None:
    return next((r for r in self.relations if r.name == name), None)

  def dimension(self, name: str) -> ContextDimension | None:
    return next((c for c in self.context if c.name == name), None)

  # validation helpers return an error message instead of raising: extraction output is untrusted
  # and a bad claim should be skipped, not abort the ingest
  def check_attribute(self, entity_type: str, attribute: str) -> str | None:
    if (et := self.entity(entity_type)) is None:
      return f"unknown entity type '{entity_type}'"
    if et.attribute(attribute) is None:
      return f"'{entity_type}' has no attribute '{attribute}'"
    return None

  def check_relation(self, relation: str, source_type: str, target_type: str) -> str | None:
    if (rt := self.relation(relation)) is None:
      return f"unknown relation '{relation}'"
    if source_type not in rt.source or target_type not in rt.target:
      return f"'{relation}' does not connect {source_type} -> {target_type}"
    return None

  def check_context(self, context: dict[str, str]) -> str | None:
    if unknown := [k for k in context if self.dimension(k) is None]:
      return f"unknown context dimensions {unknown}"
    return None

  # compact text form used inside LLM prompts
  def prompt_repr(self) -> str:
    lines = [f"Schema '{self.name}': {self.description}".strip(), "", "Entity types:"]
    for e in self.entities:
      lines.append(f"- {e.name}: {e.description}")
      lines += [f"    attribute '{a.name}': {a.description}" for a in e.attributes]
    lines += ["", "Relation types:"]
    lines += [f"- {r.name} ({'|'.join(r.source)} -> {'|'.join(r.target)}): {r.description}"
              for r in self.relations]
    lines += ["", "Context dimensions (facts may be scoped to these):"]
    lines += [f"- {c.name}{f' (refers to a {c.entity})' if c.entity else ''}: {c.description}"
              for c in self.context]
    lines += ["", f"Owners are always entities of type '{self.owner_type}'."]
    return "\n".join(lines)
