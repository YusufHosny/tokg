"""Schema for the temporal, ownership-aware organisational knowledge graph.

Three layers:
1. SourceDocument - the raw ingest format (email | meeting | wiki | portal)
2. Graph nodes / edges - Policy, Example, Person (+ Edge)
3. AnswerBundle - what the API returns for a question
Plus ExtractionResult, which is what the LLM returns per document.
"""
from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums

class SourceKind(str, Enum):
    EMAIL = "email"
    MEETING = "meeting"
    WIKI = "wiki"
    PORTAL = "portal"


class PolicyType(str, Enum):
    PROCESS = "process"  # step-by-step procedure (e.g. single permit hiring)
    RULE = "rule"  # a constraint or entitlement (e.g. sick day certificates)
    GUIDEBOOK = "guidebook"  # general how-to / reference (e.g. who to ask for IT)


class PolicyStatus(str, Enum):
    CURRENT = "current"  # the answer we give today
    SUPERSEDED = "superseded"  # replaced by a newer version, kept as history
    CONTESTED = "contested"  # a claim that conflicts with the current version, needs review


class EvidenceRole(str, Enum):
    DEFINES = "defines"  # source states the policy
    UPDATES = "updates"  # source changes an earlier version
    CONFIRMS = "confirms"  # source restates it unchanged
    CONTRADICTS = "contradicts"  # source says something conflicting
    MENTIONS = "mentions"


class EdgeType(str, Enum):
    OWNS = "OWNS"  # Person -> Policy
    SUPERSEDES = "SUPERSEDES"  # newer Policy -> older Policy
    CONTRADICTS = "CONTRADICTS"  # contested Policy -> current Policy
    EXAMPLE_OF = "EXAMPLE_OF"  # Example -> Policy (by topic)
    EVIDENCED_BY = "EVIDENCED_BY"  # Policy | Example -> SourceDocument
    HANDLED = "HANDLED"  # Person -> Example


# ---------------------------------------------------------------- layer 1: raw input

class SourceDocument(BaseModel):
    """Exactly the JSON format of the mock data files."""
    id: str
    source: SourceKind
    timestamp: dt.datetime
    author: str  # email address
    recipients: list[str] = Field(default_factory=list)
    title: str
    body: str


# ---------------------------------------------------------------- layer 2: graph

class Person(BaseModel):
    id: str  # email address
    name: str
    role: str
    external: bool = False  # e.g. the SD Worx consultant
    owns_topics: list[str] = Field(default_factory=list)  # bootstrap: topic_keys they own


class Evidence(BaseModel):
    """Link from a graph node back to the unstructured source (drill-down / audit)."""
    source_id: str
    role: EvidenceRole
    excerpt: Optional[str] = None  # short supporting snippet


class Scope(BaseModel):
    """When does this policy apply? Two policies with the same topic_key but a
    different scope do not supersede each other."""
    country: Optional[str] = None  # e.g. "BE"
    audience: Optional[str] = None  # e.g. "non-EU nationals"


class Policy(BaseModel):
    id: str  # unique per version
    topic_key: str  # stable across versions, e.g. "hire_non_eu"
    type: PolicyType
    subtype: Optional[str] = None  # e.g. "hiring", "leave", "procurement"
    title: str
    summary: str
    steps: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)

    # temporal
    version: int = 1
    status: PolicyStatus = PolicyStatus.CURRENT
    valid_from: dt.datetime  # when this version became true
    valid_to: Optional[dt.datetime] = None  # set when superseded
    recorded_at: dt.datetime  # when we ingested it

    # ownership, required at creation
    owner_id: str  # Person.id
    escalate_to_id: Optional[str] = None  # who to ask if the owner is unavailable

    # provenance
    evidence: list[Evidence] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    needs_review: bool = False  # low confidence or conflict -> human review queue


class Example(BaseModel):
    """A past real case attached to a topic (e.g. a previous hire)."""
    id: str
    topic_key: str
    title: str
    summary: str
    occurred_at: dt.datetime
    handled_by_id: Optional[str] = None
    lessons: list[str] = Field(default_factory=list)
    policy_version_id: Optional[str] = None  # which policy version it followed
    evidence: list[Evidence] = Field(min_length=1)


class Edge(BaseModel):
    type: EdgeType
    src: str
    dst: str
    valid_from: Optional[dt.datetime] = None
    valid_to: Optional[dt.datetime] = None
    note: Optional[str] = None


class KnowledgeGraph(BaseModel):
    """Plain data container. Logic (temporal resolution etc.) lives elsewhere."""
    sources: dict[str, SourceDocument] = Field(default_factory=dict)
    people: dict[str, Person] = Field(default_factory=dict)
    policies: dict[str, Policy] = Field(default_factory=dict)
    examples: dict[str, Example] = Field(default_factory=dict)
    edges: list[Edge] = Field(default_factory=list)


# ---------------------------------------------------------------- LLM extraction output

class ExtractedPolicy(BaseModel):
    topic_key: str  # must reuse an existing key when it matches
    type: PolicyType
    subtype: Optional[str] = None
    title: str
    summary: str
    steps: list[str] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
    effective_from: Optional[dt.datetime] = None  # falls back to the document timestamp
    owner_email: Optional[str] = None
    evidence_role: EvidenceRole
    excerpt: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractedExample(BaseModel):
    topic_key: str
    title: str
    summary: str
    occurred_at: Optional[dt.datetime] = None
    handled_by_email: Optional[str] = None
    lessons: list[str] = Field(default_factory=list)
    excerpt: Optional[str] = None


class ExtractionResult(BaseModel):
    """One per SourceDocument. Noise documents return empty lists."""
    policies: list[ExtractedPolicy] = Field(default_factory=list)
    examples: list[ExtractedExample] = Field(default_factory=list)


# ---------------------------------------------------------------- layer 3: API answer

class OwnerInfo(BaseModel):
    person: Optional[Person] = None
    escalate_to: Optional[Person] = None


class PolicyVersion(BaseModel):
    policy: Policy
    sources: list[SourceDocument] = Field(default_factory=list)


class AnswerBundle(BaseModel):
    """Three parts of the demo answer, plus trust flags."""
    topic_key: Optional[str] = None
    current: Optional[PolicyVersion] = None  # latest via temporal graph
    history: list[PolicyVersion] = Field(default_factory=list)  # superseded versions
    contested: list[PolicyVersion] = Field(default_factory=list)  # conflicting claims
    examples: list[Example] = Field(default_factory=list)  # drill-down cases
    owner: OwnerInfo = Field(default_factory=OwnerInfo)  # who to contact
    answerable: bool = True  # False -> no reliable answer, escalate
    escalation_note: Optional[str] = None
