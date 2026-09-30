# ABOUTME: LLM-backed stages with a fake chat model: structured outputs are used when valid,
# ABOUTME: hallucinated ids are dropped, and failures fall back to the deterministic defaults.
from datetime import UTC, datetime

from conftest import OWNER, doc, rule

from tokg.answer import LLMAnswerer
from tokg.extract import Extraction, LLMExtractor
from tokg.models import AttributeStatement, Claim, Node, SourceRef
from tokg.resolve import Decision, LLMResolver, ResolutionInput
from tokg.views import Answer, NodeView


class FakeLLM:
  def __init__(self, result: object) -> None:
    self.result = result
    self.calls: list = []

  def with_structured_output(self, schema):
    return self

  def invoke(self, messages):
    self.calls.append(messages)
    return self.result


def _inp(schema, candidates=None) -> ResolutionInput:
  claim = Claim(id="c:0", subject_id="policy:x", statement=AttributeStatement(attribute="rule", value="v2"),
                valid_from=datetime(2022, 1, 1, tzinfo=UTC), source=SourceRef(source_id="c"))
  return ResolutionInput(claim=claim, subject=Node(id="policy:x", type="Policy", name="X"),
                         candidates=candidates or [], owner_id=None, authoritative=True, schema=schema)


def test_extractor_returns_claims_and_degrades(schema):
  src = doc("doc:a", OWNER, "2021-01-01", "text")
  llm = FakeLLM(Extraction(claims=[rule("v")]))
  assert LLMExtractor(llm).extract(src, schema, []) == [rule("v")]  # type: ignore[arg-type]
  assert "Policy" in llm.calls[0][0][1]
  assert LLMExtractor(FakeLLM(None)).extract(src, schema, []) == []  # type: ignore[arg-type]


def test_resolver_filters_unknown_targets_and_falls_back(schema):
  from tokg.models import Fact
  existing = Fact(id="old:0", subject_id="policy:x", statement=AttributeStatement(attribute="rule", value="v1"),
                  valid_from=datetime(2021, 1, 1, tzinfo=UTC))
  llm = FakeLLM(Decision(action="supersede", target_fact_ids=["old:0", "made-up"], rationale="newer"))
  d = LLMResolver(llm).resolve(_inp(schema, [existing]))  # type: ignore[arg-type]
  assert d.action == "supersede" and d.target_fact_ids == ["old:0"]
  assert LLMResolver(FakeLLM(None)).resolve(_inp(schema, [existing])).action == "supersede"  # type: ignore[arg-type]
  assert LLMResolver(FakeLLM(None)).resolve(_inp(schema)).action == "create"  # type: ignore[arg-type]


def test_answerer_filters_citations(schema):
  view = NodeView(node=Node(id="policy:x", type="Policy", name="X"))
  llm = FakeLLM(Answer(answer="a", cited_fact_ids=["ghost"], contact_ids=["person:ghost"]))
  ans = LLMAnswerer(llm).answer("q", [view])  # type: ignore[arg-type]
  assert ans.answer == "a" and ans.cited_fact_ids == [] and ans.contact_ids == []
  assert "No knowledge" in LLMAnswerer(llm).answer("q", []).answer  # type: ignore[arg-type]
