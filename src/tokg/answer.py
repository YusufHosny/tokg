# ABOUTME: Answer stage: turn retrieved NodeViews into a grounded Answer. TemplateAnswerer needs
# ABOUTME: no LLM (and is the fallback); LLMAnswerer writes prose but may only cite retrieved facts.
from abc import ABC

from langchain_core.language_models import BaseChatModel

from tokg.llm import default_llm
from tokg.views import Answer, FactView, NodeView


class Answerer(ABC):
  def answer(self, question: str, views: list[NodeView]) -> Answer:
    raise NotImplementedError("answer should be implemented by subclasses")


def _fact_line(fv: FactView) -> str:
  f = fv.fact
  ctx = ", ".join(f"{k}={v}" for k, v in f.context.items()) or "general"
  return f"[{f.id}] ({fv.trust}, since {f.valid_from.date()}, {ctx}) {f.statement.describe()}"


def render_views(views: list[NodeView]) -> str:
  blocks = []
  for v in views:
    lines = [f"## {v.node.type}: {v.node.name} (owner: {v.owner.name if v.owner else 'NONE'})"]
    lines += [f"current {_fact_line(fv)}" for fv in v.current]
    lines += [f"also applicable {_fact_line(fv)}" for fv in v.alternatives]
    lines += [f"pending approval {_fact_line(fv)}" for fv in v.pending]
    lines += [f"linked from {fv.fact.subject_id}: {_fact_line(fv)}" for fv in v.incoming]
    lines += [f"contact [{c.person.id}] {c.person.name}: {c.role}" for c in v.contacts]
    blocks.append("\n".join(lines))
  return "\n\n".join(blocks)


class TemplateAnswerer(Answerer):
  def answer(self, question: str, views: list[NodeView]) -> Answer:
    if not views:
      return Answer(answer="No knowledge found for this question.",
                    caveats=["Nothing in the graph matches; consider asking an owner."])
    return Answer(
      answer=render_views(views),
      cited_fact_ids=[fv.fact.id for v in views for fv in v.current],
      contact_ids=list(dict.fromkeys(c.person.id for v in views for c in v.contacts)),
      caveats=[f"Pending change on {v.node.name}: {fv.fact.statement.describe()}"
               for v in views for fv in v.pending]
              + [f"{v.node.name} has no owner." for v in views if v.owner is None],
    )


def get_answer_system_prompt() -> str:
  return """You answer employee questions using ONLY the knowledge graph excerpt provided.
- Answer directly and briefly with the current procedure/rule for the given context.
- Cite the fact ids you rely on. Never cite ids that are not in the excerpt.
- Name who to contact (person ids from the 'contact' lines) and why.
- Put pending changes, unconfirmed facts, missing owners and missing knowledge in caveats.
- If the excerpt does not answer the question, say so instead of guessing."""


class LLMAnswerer(Answerer):
  def __init__(self, llm: BaseChatModel | None = None, fallback: Answerer | None = None) -> None:
    self._llm = llm
    self.fallback = fallback or TemplateAnswerer()

  @property
  def llm(self) -> BaseChatModel:
    if self._llm is None:
      self._llm = default_llm()
    return self._llm

  def answer(self, question: str, views: list[NodeView]) -> Answer:
    if not views:
      return self.fallback.answer(question, views)
    chain = self.llm.with_structured_output(Answer)
    result = chain.invoke([("system", get_answer_system_prompt()),
                           ("human", f"Question: {question}\n\nKnowledge graph:\n{render_views(views)}")])
    if not isinstance(result, Answer):
      return self.fallback.answer(question, views)
    fact_ids = {fv.fact.id for v in views for fv in (*v.current, *v.alternatives, *v.pending, *v.incoming)}
    person_ids = {c.person.id for v in views for c in v.contacts}
    result.cited_fact_ids = [i for i in result.cited_fact_ids if i in fact_ids]
    result.contact_ids = [i for i in result.contact_ids if i in person_ids]
    return result
