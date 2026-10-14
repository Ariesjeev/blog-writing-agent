from __future__ import annotations

import operator
import os
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Callable, List, Literal, Optional, TypedDict

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel, Field

load_dotenv()

# ============================================================
# Config (set from the UI sidebar)
# ============================================================
DEFAULT_CONFIG = {
    "model": "gpt-4.1-mini",
    "temperature": 0.7,
    "tone": "",            # empty = let the planner choose
    "audience": "",
    "length": "medium",    # short | medium | long
    "max_images": 3,       # 0-3
    "require_approval": True,
    "fact_check": True,
    "seo": True,
    "social": True,
}
LENGTH_HINT = {
    "short": "about 900 words in total, 4-5 tasks",
    "medium": "about 1600 words in total, 5-7 tasks",
    "long": "about 2600 words in total, 7-9 tasks",
}


def _cfg(c: Optional[dict]) -> dict:
    return {**DEFAULT_CONFIG, **(c or {})}


@lru_cache(maxsize=16)
def _llm(model: str, temperature: float) -> ChatOpenAI:
    return ChatOpenAI(model=model, temperature=temperature, stream_usage=True)


def get_llm(cfg: Optional[dict], creative: bool = False) -> ChatOpenAI:
    c = _cfg(cfg)
    return _llm(c["model"], float(c["temperature"]) if creative else 0.2)


# ============================================================
# Schemas
# ============================================================
class Task(BaseModel):
    id: int
    title: str
    goal: str = Field(..., description="One sentence describing what the reader should do/understand.")
    bullets: List[str] = Field(..., min_length=3, max_length=6)
    target_words: int = Field(..., description="Target words (120–550).")
    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal["explainer", "tutorial", "news_roundup", "comparison", "system_design"] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(5)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


class ImageSpec(BaseModel):
    placeholder: str = Field(..., description="e.g. [[IMAGE_1]]")
    filename: str = Field(..., description="Save under images/, e.g. qkv_flow.png")
    alt: str
    caption: str
    prompt: str
    size: Literal["1024x1024", "1024x1536", "1536x1024"] = "1024x1024"
    quality: Literal["low", "medium", "high"] = "medium"


class GlobalImagePlan(BaseModel):
    md_with_placeholders: str
    images: List[ImageSpec] = Field(default_factory=list)


class ClaimIssue(BaseModel):
    claim: str
    section: str
    problem: str = Field(..., description="Why it is unsupported or wrong")
    severity: Literal["low", "medium", "high"] = "medium"


class FactCheckReport(BaseModel):
    summary: str
    issues: List[ClaimIssue] = Field(default_factory=list)


class SEOPack(BaseModel):
    meta_description: str = Field(..., description="Max 160 characters")
    slug: str
    keywords: List[str]
    title_options: List[str] = Field(..., description="3-5 alternative titles")


class SocialPack(BaseModel):
    linkedin_post: str
    tweet_thread: List[str] = Field(..., description="4-8 tweets, each <= 270 chars")


class State(TypedDict, total=False):
    topic: str
    config: dict
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]
    as_of: str
    recency_days: int
    sections: Annotated[List[tuple[int, str]], operator.add]
    merged_md: str
    md_with_placeholders: str
    image_specs: List[dict]
    fact_report: dict
    final: str
    seo: dict
    social: dict


# ============================================================
# Router / Research / Orchestrator
# ============================================================
ROUTER_SYSTEM = """You are a routing module for a technical blog planner.
Decide whether web research is needed BEFORE planning.

Modes:
- closed_book (needs_research=false): evergreen concepts.
- hybrid (needs_research=true): evergreen + needs up-to-date examples/tools/models.
- open_book (needs_research=true): volatile weekly/news/"latest"/pricing/policy.

If needs_research=true:
- Output 3–10 high-signal, scoped queries.
- For open_book weekly roundup, include queries reflecting last 7 days.
"""


def router_node(state: State) -> dict:
    decision = get_llm(state.get("config")).with_structured_output(RouterDecision).invoke(
        [SystemMessage(content=ROUTER_SYSTEM),
         HumanMessage(content=f"Topic: {state['topic']}\nAs-of date: {state['as_of']}")]
    )
    recency = {"open_book": 7, "hybrid": 45}.get(decision.mode, 3650)
    return {"needs_research": decision.needs_research, "mode": decision.mode,
            "queries": decision.queries, "recency_days": recency}


def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"


def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    if not os.getenv("TAVILY_API_KEY"):
        return []
    try:
        from langchain_community.tools.tavily_search import TavilySearchResults
        results = TavilySearchResults(max_results=max_results).invoke({"query": query})
        return [{
            "title": r.get("title") or "", "url": r.get("url") or "",
            "snippet": r.get("content") or r.get("snippet") or "",
            "published_at": r.get("published_date") or r.get("published_at"),
            "source": r.get("source"),
        } for r in results or []]
    except Exception:
        return []


def _iso_to_date(s: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(s[:10]) if s else None
    except Exception:
        return None


RESEARCH_SYSTEM = """You are a research synthesizer.
Given raw web search results, produce EvidenceItem objects.

Rules:
- Only include items with a non-empty url.
- Prefer relevant + authoritative sources.
- Normalize published_at to ISO YYYY-MM-DD if reliably inferable; else null (do NOT guess).
- Keep snippets short.
- Deduplicate by URL.
"""


def research_node(state: State) -> dict:
    raw: List[dict] = []
    for q in (state.get("queries") or [])[:10]:
        raw.extend(_tavily_search(q, max_results=6))
    if not raw:
        return {"evidence": []}

    pack = get_llm(state.get("config")).with_structured_output(EvidencePack).invoke(
        [SystemMessage(content=RESEARCH_SYSTEM),
         HumanMessage(content=f"As-of date: {state['as_of']}\nRecency days: {state['recency_days']}\n\nRaw results:\n{raw}")]
    )
    evidence = list({e.url: e for e in pack.evidence if e.url}.values())
    if state.get("mode") == "open_book":
        cutoff = date.fromisoformat(state["as_of"]) - timedelta(days=int(state["recency_days"]))
        evidence = [e for e in evidence if (d := _iso_to_date(e.published_at)) and d >= cutoff]
    return {"evidence": evidence}


ORCH_SYSTEM = """You are a senior technical writer and developer advocate.
Produce a highly actionable outline for a technical blog post.

Requirements:
- Each task has goal + 3–6 bullets + target_words. Follow the requested overall length.
- Tags are flexible; do not force a fixed taxonomy.
- If the user supplied a tone or audience, use it exactly in the plan.

Grounding:
- closed_book: evergreen, no evidence dependence.
- hybrid: use evidence for up-to-date examples; mark those tasks requires_research=True and requires_citations=True.
- open_book: weekly/news roundup:
  - Set blog_kind="news_roundup"
  - No tutorial content unless requested
  - If evidence is weak, plan should explicitly reflect that (don't invent events).

Output must match Plan schema.
"""


def orchestrator_node(state: State) -> dict:
    c = _cfg(state.get("config"))
    mode = state.get("mode", "closed_book")
    evidence = state.get("evidence", [])
    plan = get_llm(c).with_structured_output(Plan).invoke(
        [SystemMessage(content=ORCH_SYSTEM),
         HumanMessage(content=(
             f"Topic: {state['topic']}\nMode: {mode}\n"
             f"As-of: {state['as_of']} (recency_days={state['recency_days']})\n"
             f"Length: {LENGTH_HINT[c['length']]}\n"
             f"Preferred tone: {c['tone'] or 'your choice'}\n"
             f"Preferred audience: {c['audience'] or 'your choice'}\n"
             f"{'Force blog_kind=news_roundup' if mode == 'open_book' else ''}\n\n"
             f"Evidence:\n{[e.model_dump() for e in evidence][:16]}"))]
    )
    if mode == "open_book":
        plan.blog_kind = "news_roundup"
    return {"plan": plan}


# ============================================================
# 1) Human approval of the outline (interrupt + checkpointer)
# ============================================================
def plan_review(state: State) -> dict:
    if not _cfg(state.get("config"))["require_approval"]:
        return {}
    edited = interrupt({"plan": state["plan"].model_dump()})  # pauses; resumes with the edited plan dict
    return {"plan": Plan(**edited)} if edited else {}


# ============================================================
# Fan-out + Worker (7: token streaming)
# ============================================================
def fanout(state: State):
    return [
        Send("worker", {
            "task": t.model_dump(), "topic": state["topic"], "mode": state["mode"],
            "as_of": state["as_of"], "recency_days": state["recency_days"],
            "plan": state["plan"].model_dump(), "config": state.get("config"),
            "evidence": [e.model_dump() for e in state.get("evidence", [])],
        })
        for t in state["plan"].tasks
    ]


WORKER_SYSTEM = """You are a senior technical writer and developer advocate.
Write ONE section of a technical blog post in Markdown.

Constraints:
- Cover ALL bullets in order.
- Target words ±15%.
- Output only section markdown starting with "## <Section Title>".

Scope guard:
- If blog_kind=="news_roundup", do NOT drift into tutorials (scraping/RSS/how to fetch).
  Focus on events + implications.

Grounding:
- If mode=="open_book": do not introduce any specific event/company/model/funding/policy claim unless supported by provided Evidence URLs.
  For each supported claim, attach a Markdown link ([Source](URL)).
  If unsupported, write "Not found in provided sources."
- If requires_citations==true (hybrid tasks): cite Evidence URLs for external claims.

Code:
- If requires_code==true, include at least one minimal snippet.
"""


def _write_section(task: Task, plan: Plan, evidence: List[EvidenceItem], topic: str, mode: str,
                   as_of: str, recency_days: int, cfg: Optional[dict], note: str = "",
                   on_token: Optional[Callable[[str], None]] = None) -> str:
    bullets = "\n- " + "\n- ".join(task.bullets)
    ev = "\n".join(f"- {e.title} | {e.url} | {e.published_at or 'date:unknown'}" for e in evidence[:20])
    msgs = [
        SystemMessage(content=WORKER_SYSTEM),
        HumanMessage(content=(
            f"Blog title: {plan.blog_title}\nAudience: {plan.audience}\nTone: {plan.tone}\n"
            f"Blog kind: {plan.blog_kind}\nConstraints: {plan.constraints}\nTopic: {topic}\n"
            f"Mode: {mode}\nAs-of: {as_of} (recency_days={recency_days})\n\n"
            f"Section title: {task.title}\nGoal: {task.goal}\nTarget words: {task.target_words}\n"
            f"Tags: {task.tags}\nrequires_research: {task.requires_research}\n"
            f"requires_citations: {task.requires_citations}\nrequires_code: {task.requires_code}\n"
            f"Bullets:{bullets}\n\n"
            + (f"Editor instruction (follow it): {note}\n\n" if note else "")
            + f"Evidence (ONLY cite these URLs):\n{ev}\n")),
    ]
    parts: List[str] = []
    for chunk in get_llm(cfg, creative=True).stream(msgs):
        t = chunk.content if isinstance(chunk.content, str) else ""
        if t:
            parts.append(t)
            if on_token:
                on_token(t)
    return "".join(parts).strip()


def worker_node(payload: dict) -> dict:
    task, plan = Task(**payload["task"]), Plan(**payload["plan"])
    evidence = [EvidenceItem(**e) for e in payload.get("evidence", [])]
    try:
        writer = get_stream_writer()
    except Exception:
        writer = None
    md = _write_section(
        task, plan, evidence, payload["topic"], payload.get("mode", ""), payload.get("as_of", ""),
        payload.get("recency_days", 0), payload.get("config"),
        on_token=(lambda t: writer({"task_id": task.id, "chunk": t})) if writer else None,
    )
    return {"sections": [(task.id, md)]}


# ============================================================
# 2) Regenerate ONE section (called directly from the UI)
# ============================================================
def regenerate_section(task_id: int, data: dict, instruction: str = "") -> str:
    plan = Plan(**data["plan"])
    task = next(t for t in plan.tasks if t.id == task_id)
    ev = [EvidenceItem(**e) for e in data.get("evidence", [])]
    return _write_section(task, plan, ev, data.get("topic", ""), data.get("mode", "closed_book"),
                          data.get("as_of", date.today().isoformat()), data.get("recency_days", 3650),
                          data.get("config"), note=instruction)


def replace_section(md: str, old_section: str, new_section: str) -> Optional[str]:
    """Swap one '## ...' section for a new one. Returns None if the heading isn't found."""
    head = old_section.strip().splitlines()[0]
    i = md.find(head)
    if i < 0:
        return None
    j = md.find("\n## ", i + len(head))
    return md[:i] + new_section.strip() + ("\n" + md[j:] if j >= 0 else "\n")


# ============================================================
# Reducer: merge -> 3) fact-check -> images -> (5 SEO | 6 social)
# ============================================================
def merge_content(state: State) -> dict:
    plan = state["plan"]
    body = "\n\n".join(md for _, md in sorted(state["sections"], key=lambda x: x[0])).strip()
    return {"merged_md": f"# {plan.blog_title}\n\n{body}\n"}


FACT_SYSTEM = """You are a meticulous fact-checker.
You get a blog draft and the list of evidence sources the writers were allowed to use.
Flag specific EXTERNAL factual claims (events, numbers, dates, product features, quotes, policies) that are
(a) not supported by any evidence item, (b) contradict it, or (c) carry no citation link when one is required.
Do not flag opinions, general explanations or code. Quote the claim briefly and name its section.
If everything is fine, return no issues.
"""


def fact_check(state: State) -> dict:
    evidence = state.get("evidence") or []
    if not _cfg(state.get("config"))["fact_check"] or not evidence:
        return {"fact_report": {"summary": "Skipped (no web sources to check against).", "issues": [], "skipped": True}}
    ev = "\n".join(f"- {e.title} | {e.url} | {(e.snippet or '')[:300]}" for e in evidence[:30])
    rep = get_llm(state.get("config")).with_structured_output(FactCheckReport).invoke(
        [SystemMessage(content=FACT_SYSTEM),
         HumanMessage(content=f"Evidence:\n{ev}\n\nDraft:\n{state['merged_md'][:20000]}")]
    )
    return {"fact_report": rep.model_dump()}


def decide_images(state: State) -> dict:
    merged = state["merged_md"]
    n = int(_cfg(state.get("config"))["max_images"])
    if n <= 0:
        return {"md_with_placeholders": merged, "image_specs": []}
    system = f"""You are an expert technical editor.
Decide if images/diagrams are needed for THIS blog.

Rules:
- Max {n} images total.
- Each image must materially improve understanding (diagram/flow/table-like visual).
- Insert placeholders exactly: [[IMAGE_1]], [[IMAGE_2]], [[IMAGE_3]] (only as many as used).
- If no images needed: md_with_placeholders must equal input and images=[].
- Avoid decorative images; prefer technical diagrams with short labels.
Return strictly GlobalImagePlan.
"""
    plan = state["plan"]
    r = get_llm(state.get("config")).with_structured_output(GlobalImagePlan).invoke(
        [SystemMessage(content=system),
         HumanMessage(content=f"Blog kind: {plan.blog_kind}\nTopic: {state['topic']}\n\n"
                              f"Insert placeholders + propose image prompts.\n\n{merged}")]
    )
    return {"md_with_placeholders": r.md_with_placeholders,
            "image_specs": [i.model_dump() for i in r.images[:n]]}


def _gemini_generate_image_bytes(prompt: str) -> bytes:
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set.")
    resp = genai.Client(api_key=api_key).models.generate_content(
        model="gemini-2.5-flash-image", contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            safety_settings=[types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",
                                                 threshold="BLOCK_ONLY_HIGH")],
        ),
    )
    parts = getattr(resp, "parts", None)
    if not parts and getattr(resp, "candidates", None):
        try:
            parts = resp.candidates[0].content.parts
        except Exception:
            parts = None
    if not parts:
        raise RuntimeError("No image content returned (safety/quota/SDK change).")
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            return inline.data
    raise RuntimeError("No inline image bytes found in response.")


def _safe_slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9 _-]+", "", title.strip().lower())
    return re.sub(r"\s+", "_", s).strip("_") or "blog"


def generate_and_place_images(state: State) -> dict:
    plan = state["plan"]
    md = state.get("md_with_placeholders") or state["merged_md"]
    specs = state.get("image_specs", []) or []
    if specs:
        images_dir = Path("images")
        images_dir.mkdir(exist_ok=True)
        for spec in specs:
            out_path = images_dir / spec["filename"]
            if not out_path.exists():
                try:
                    out_path.write_bytes(_gemini_generate_image_bytes(spec["prompt"]))
                except Exception as e:
                    block = (f"> **[IMAGE GENERATION FAILED]** {spec.get('caption', '')}\n>\n"
                             f"> **Alt:** {spec.get('alt', '')}\n>\n> **Prompt:** {spec.get('prompt', '')}\n>\n"
                             f"> **Error:** {e}\n")
                    md = md.replace(spec["placeholder"], block)
                    continue
            md = md.replace(spec["placeholder"], f"![{spec['alt']}](images/{spec['filename']})\n*{spec['caption']}*")
    Path(f"{_safe_slug(plan.blog_title)}.md").write_text(md, encoding="utf-8")
    return {"final": md}


def seo_node(state: State) -> dict:
    if not _cfg(state.get("config"))["seo"]:
        return {"seo": {}}
    r = get_llm(state.get("config")).with_structured_output(SEOPack).invoke(
        [SystemMessage(content="You are an SEO editor for a developer blog. Produce a meta description "
                               "(<=160 chars), a URL slug, 5-10 keywords and 3-5 alternative titles."),
         HumanMessage(content=state["final"][:12000])]
    )
    return {"seo": r.model_dump()}


def social_node(state: State) -> dict:
    if not _cfg(state.get("config"))["social"]:
        return {"social": {}}
    r = get_llm(state.get("config"), creative=True).with_structured_output(SocialPack).invoke(
        [SystemMessage(content="You write social posts for a developer audience. Make a LinkedIn post "
                               "(hook, 3-5 short takeaways, call to read) and an X/Twitter thread of 4-8 "
                               "tweets (<=270 chars each). No hype, no emoji spam, no invented claims."),
         HumanMessage(content=state["final"][:12000])]
    )
    return {"social": r.model_dump()}


# ============================================================
# Graph
# ============================================================
g = StateGraph(State)
for name, fn in [("router", router_node), ("research", research_node), ("orchestrator", orchestrator_node),
                 ("plan_review", plan_review), ("worker", worker_node), ("merge_content", merge_content),
                 ("fact_check", fact_check), ("decide_images", decide_images),
                 ("generate_and_place_images", generate_and_place_images),
                 ("seo", seo_node), ("social", social_node)]:
    g.add_node(name, fn)

g.add_edge(START, "router")
g.add_conditional_edges("router", route_next, {"research": "research", "orchestrator": "orchestrator"})
g.add_edge("research", "orchestrator")
g.add_edge("orchestrator", "plan_review")
g.add_conditional_edges("plan_review", fanout, ["worker"])
g.add_edge("worker", "merge_content")
g.add_edge("merge_content", "fact_check")
g.add_edge("fact_check", "decide_images")
g.add_edge("decide_images", "generate_and_place_images")
g.add_edge("generate_and_place_images", "seo")
g.add_edge("generate_and_place_images", "social")
g.add_edge("seo", END)
g.add_edge("social", END)

# MemorySaver is required for interrupt(); swap for SqliteSaver to survive restarts.
app = g.compile(checkpointer=MemorySaver())