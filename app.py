from __future__ import annotations

import difflib
import math
import os
import re
import time
import uuid
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.types import Command

import bwa_backend as be
import bwa_publish as pub
import bwa_store as store
from bwa_theme import CSS

app = be.app
ss = st.session_state

st.set_page_config(page_title="Inkwell · Blog Writing Agent", page_icon="✒️", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
store.init()

AUTH_ON = os.getenv("BWA_AUTH", "1") != "0"   # BWA_AUTH=0 disables login (single local user)
PRICES = {"gpt-4.1-mini": (0.40, 1.60), "gpt-4.1": (2.0, 8.0), "gpt-4o-mini": (0.15, 0.60), "gpt-4o": (2.5, 10.0)}  # $/1M tokens (estimates)
STAGES = [
    ("router", "Router", "Decides if research is needed", {"router"}),
    ("research", "Research", "Searches the web", {"research"}),
    ("plan", "Planner", "Builds and reviews the outline", {"plan_review"}),
    ("write", "Writers", "Drafts each section live", {"merge_content"}),
    ("edit", "Editor", "Fact-check and images", {"generate_and_place_images"}),
    ("extras", "Extras", "SEO and social posts", {"seo", "social"}),
]

for k, v in {"user": None if AUTH_ON else "local", "phase": "idle", "seen": set(), "timings": [], "usage": {},
             "logs": [], "last_out": None, "blog_id": None, "mode": "", "elapsed": 0.0, "pending": None}.items():
    ss.setdefault(k, v)


# ============================================================
# Helpers
# ============================================================
def safe_slug(t: str) -> str:
    return re.sub(r"\s+", "_", re.sub(r"[^a-z0-9 _-]+", "", t.strip().lower())).strip("_") or "blog"


def title_of(md: str, fallback: str = "blog") -> str:
    return next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), fallback)


def to_dict(o: Any) -> Any:
    return o.model_dump() if hasattr(o, "model_dump") else o


def est_cost(usage: Dict[str, Dict[str, int]]) -> float:
    total = 0.0
    for m, u in usage.items():
        key = next((k for k in sorted(PRICES, key=len, reverse=True) if m.startswith(k)), None)
        if key:
            total += u["input_tokens"] / 1e6 * PRICES[key][0] + u["output_tokens"] / 1e6 * PRICES[key][1]
    return total


_IMG = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<src>[^)]+)\)(?:\s*\n\*(?P<cap>[^*\n]+)\*)?")


def render_markdown(md: str) -> None:
    last = 0
    for m in _IMG.finditer(md):
        if md[last:m.start()].strip():
            st.markdown(md[last:m.start()])
        src, cap = m.group("src").strip(), m.group("cap") or m.group("alt") or None
        path = os.path.normpath(src)
        if src.startswith("http") or os.path.exists(path):
            st.image(src if src.startswith("http") else path, caption=cap, width="stretch")
        else:
            st.warning(f"Image not found: `{src}`")
        last = m.end()
    if md[last:].strip():
        st.markdown(md[last:])


def pipeline_html() -> str:
    skip = ss.mode == "closed_book"
    cur = next((k for k, _, _, t in STAGES if not t <= ss.seen and not (k == "research" and skip)), None) \
        if ss.phase in ("starting", "writing", "review") else None
    out = ["<div class='pipe'>"]
    for k, name, hint, term in STAGES:
        cls = "done" if term <= ss.seen else "active" if k == cur else ""
        if k == "research" and skip and cls != "done":
            cls, hint = "skip", "Skipped (evergreen topic)"
        if k == "plan" and ss.phase == "review":
            hint = "Waiting for your approval"
        out.append(f"<div class='step {cls}'><b>{name}</b><span>{hint}</span></div>")
    return "".join(out) + "</div>"


def persist(md: str, note: str) -> None:
    out = ss.last_out
    out["final"] = md
    data = {k: v for k, v in out.items() if k != "final"}
    ss.blog_id = store.save_blog(ss.user, title_of(md, out.get("plan", {}).get("blog_title", "blog")),
                                 md, data, ss.blog_id, note)


# ============================================================
# Run the graph (streams tokens + node progress)
# ============================================================
def run_stream(graph_input: Any, pipe_ph) -> None:
    cfg = {"configurable": {"thread_id": ss.thread_id}}
    bar, live = st.empty(), st.empty()
    buf: Dict[int, str] = {}
    n, t0, base = 0, time.perf_counter(), ss.elapsed
    pipe_ph.markdown(pipeline_html(), unsafe_allow_html=True)
    try:
        with get_usage_metadata_callback() as cb:
            for mode, payload in app.stream(graph_input, cfg, stream_mode=["updates", "custom", "values"]):
                if mode == "custom":
                    buf[payload["task_id"]] = buf.get(payload["task_id"], "") + payload["chunk"]
                    n += 1
                    if n % 6 == 0:
                        live.markdown("\n\n".join(buf[k] for k in sorted(buf)))
                elif mode == "updates":
                    for node in payload:
                        if not node.startswith("__"):
                            ss.seen.add(node)
                            ss.timings.append((node, round(base + time.perf_counter() - t0, 1)))
                            ss.logs.append(f"{time.strftime('%H:%M:%S')}  {node} finished")
                else:
                    ss.mode = payload.get("mode", ss.mode)
                    total = len((payload.get("plan") and payload["plan"].tasks) or [])
                    if total and payload.get("sections") is not None and "merge_content" not in ss.seen:
                        bar.progress(min(len(payload["sections"]) / total, 1.0),
                                     text=f"Sections written: {len(payload['sections'])}/{total}")
                pipe_ph.markdown(pipeline_html(), unsafe_allow_html=True)
        for m, u in cb.usage_metadata.items():
            d = ss.usage.setdefault(m, {"input_tokens": 0, "output_tokens": 0})
            d["input_tokens"] += u.get("input_tokens", 0)
            d["output_tokens"] += u.get("output_tokens", 0)
    except Exception as e:
        ss.phase = "idle"
        st.error(f"Generation failed: {e}. Check OPENAI_API_KEY (plus TAVILY_API_KEY / GOOGLE_API_KEY if used).")
        return
    ss.elapsed = base + time.perf_counter() - t0

    snap = app.get_state(cfg)
    if snap.next:                                    # paused at plan_review
        ss.phase, ss.plan_draft = "review", to_dict(snap.values["plan"])
    else:
        v = snap.values
        ss.last_out = {
            "topic": v["topic"], "mode": v.get("mode"), "as_of": v["as_of"], "recency_days": v["recency_days"],
            "config": v.get("config"), "plan": to_dict(v["plan"]), "evidence": [to_dict(e) for e in v.get("evidence", [])],
            "image_specs": v.get("image_specs", []), "sections": [list(s) for s in v.get("sections", [])],
            "fact_report": v.get("fact_report", {}), "seo": v.get("seo", {}), "social": v.get("social", {}),
            "final": v.get("final", ""), "usage": ss.usage, "timings": ss.timings, "elapsed": ss.elapsed,
        }
        ss.phase, ss.blog_id = "done", None
        persist(ss.last_out["final"], "Generated")
    st.rerun()


# ============================================================
# Login
# ============================================================
if not ss.user:
    st.markdown("<div class='hero'><div><h1>Inkwell</h1><p>Sign in to write and keep your blogs.</p></div></div>",
                unsafe_allow_html=True)
    t_in, t_new = st.tabs(["Log in", "Create account"])
    with t_in, st.form("login"):
        u, p = st.text_input("Username"), st.text_input("Password", type="password")
        if st.form_submit_button("Log in", type="primary"):
            if store.login(u, p):
                ss.user = u.strip().lower()
                st.rerun()
            st.error("Wrong username or password.")
    with t_new, st.form("register"):
        u, p = st.text_input("Choose a username"), st.text_input("Choose a password (8+ characters)", type="password")
        if st.form_submit_button("Create account", type="primary"):
            err = store.register(u, p)
            if err:
                st.error(err)
            else:
                ss.user = u.strip().lower()
                st.rerun()
    st.stop()

# ============================================================
# Sidebar
# ============================================================
with st.sidebar:
    if AUTH_ON:
        c1, c2 = st.columns([3, 1])
        c1.caption(f"Signed in as **{ss.user}**")
        if c2.button("Out"):
            ss.clear()
            st.rerun()
    st.header("✒️ New blog")
    topic = st.text_area("Topic", height=100, placeholder="e.g. How RAG pipelines work, for backend engineers")
    as_of = st.date_input("As-of date", value=date.today())
    with st.expander("Style and options"):
        model = st.selectbox("Model", list(PRICES), index=0)
        temp = st.slider("Creativity", 0.0, 1.2, 0.7, 0.1)
        tone = st.selectbox("Tone", ["Let the planner choose", "Friendly and practical", "Formal and precise",
                                     "Conversational", "Opinionated", "Beginner-friendly"])
        audience = st.text_input("Audience", placeholder="e.g. junior Python developers")
        length = st.radio("Length", ["short", "medium", "long"], index=1, horizontal=True)
        max_images = st.slider("Images", 0, 3, 3)
        approve = st.toggle("Review outline before writing", True)
        do_fact = st.toggle("Fact-check against sources", True)
        do_seo = st.toggle("SEO pack", True)
        do_social = st.toggle("Social posts", True)
    run_btn = st.button("Generate blog", type="primary", width="stretch")

    st.divider()
    st.subheader("Past blogs")
    q = st.text_input("Search", placeholder="Filter by title", label_visibility="collapsed")
    rows = store.list_blogs(ss.user, q)
    if not rows:
        st.caption("No saved blogs yet.")
    else:
        titles = {r["id"]: r["title"] for r in rows}
        pick = st.selectbox("Blog", list(titles), format_func=titles.get, label_visibility="collapsed")
        c1, c2 = st.columns(2)
        if c1.button("Open", width="stretch"):
            b = store.get_blog(pick, ss.user)
            ss.last_out, ss.blog_id, ss.phase = {**b["data"], "final": b["md"]}, b["id"], "done"
            ss.seen, ss.mode, ss.pending = set(), "", None
            st.rerun()
        if c2.button("Delete", width="stretch"):
            store.delete_blog(pick, ss.user)
            if ss.blog_id == pick:
                ss.last_out, ss.blog_id = None, None
            st.rerun()

if run_btn:
    if not topic.strip():
        st.sidebar.warning("Enter a topic first.")
    else:
        ss.update(seen=set(), timings=[], usage={}, logs=[], last_out=None, blog_id=None, mode="", elapsed=0.0,
                  thread_id=str(uuid.uuid4()), phase="starting")
        ss.pending = {
            "topic": topic.strip(), "as_of": as_of.isoformat(), "recency_days": 7, "sections": [],
            "config": {"model": model, "temperature": temp,
                       "tone": "" if tone.startswith("Let") else tone, "audience": audience.strip(),
                       "length": length, "max_images": max_images, "require_approval": approve,
                       "fact_check": do_fact, "seo": do_seo, "social": do_social},
        }

# ============================================================
# Hero + pipeline
# ============================================================
st.markdown("<div class='hero'><div><h1>Inkwell</h1>"
            "<p>Give it a topic. It researches, plans, writes, checks and illustrates a full technical blog post.</p></div>"
            "<div class='badge'>LangGraph · Tavily · Gemini</div></div>", unsafe_allow_html=True)
pipe_ph = st.empty()
if ss.seen or ss.phase != "idle":
    pipe_ph.markdown(pipeline_html(), unsafe_allow_html=True)

if ss.phase in ("starting", "writing"):
    run_stream(ss.pending, pipe_ph)

# ============================================================
# Outline review (human approval)
# ============================================================
if ss.phase == "review":
    st.subheader("Review the outline")
    st.caption("Edit titles, goals, word counts and bullets (3 to 6 per section), remove sections, then approve.")
    d = ss.plan_draft
    d["blog_title"] = st.text_input("Blog title", d["blog_title"])
    c1, c2 = st.columns(2)
    d["audience"], d["tone"] = c1.text_input("Audience", d["audience"]), c2.text_input("Tone", d["tone"])
    kept, errors = [], []
    for t in sorted(d["tasks"], key=lambda x: x["id"]):
        i = t["id"]
        with st.expander(f"{i}. {t['title']}  ·  {t['target_words']} words"):
            if st.checkbox("Remove this section", key=f"del{i}"):
                continue
            t["title"] = st.text_input("Title", t["title"], key=f"ti{i}")
            t["goal"] = st.text_area("Goal", t["goal"], key=f"go{i}", height=70)
            t["target_words"] = st.number_input("Target words", 20, 1500, min(max(int(t["target_words"]), 20), 1500), 20, key=f"wo{i}")
            raw = st.text_area("Bullets (one per line)", "\n".join(t["bullets"]), key=f"bu{i}", height=130)
            t["bullets"] = [b.strip() for b in raw.splitlines() if b.strip()]
            if not 3 <= len(t["bullets"]) <= 6:
                errors.append(f"Section {i} needs 3 to 6 bullets.")
            kept.append(t)
    a, b, _ = st.columns([1, 1, 4])
    if a.button("Approve and write", type="primary", disabled=bool(errors) or not kept):
        ss.pending, ss.phase = Command(resume={**d, "tasks": kept}), "writing"
        st.rerun()
    if b.button("Cancel"):
        ss.phase = "idle"
        st.rerun()
    for e in errors:
        st.warning(e)
    st.stop()

# ============================================================
# Results
# ============================================================
out: Optional[dict] = ss.last_out
if not out:
    st.markdown("<div class='empty'><h3>Nothing written yet</h3>Enter a topic in the sidebar and press "
                "<b>Generate blog</b>, or open a past post.</div>", unsafe_allow_html=True)
    st.stop()

final_md = out.get("final", "")
plan = out.get("plan")
evidence = out.get("evidence") or []
words = len(final_md.split())
title = title_of(final_md, (plan or {}).get("blog_title", "blog"))

m = st.columns(5)
m[0].metric("Words", f"{words:,}")
m[1].metric("Reading time", f"{max(1, math.ceil(words / 220))} min")
m[2].metric("Sections", len((plan or {}).get("tasks", [])) or final_md.count("\n## "))
m[3].metric("Sources", len(evidence))
m[4].metric("Est. cost", f"${est_cost(out.get('usage', {})):.3f}")

tabs = st.tabs(["Read", "Edit", "Sections", "Plan", "Sources", "Fact-check", "SEO and social",
                "Images", "Publish", "History", "Run stats"])
(t_read, t_edit, t_sec, t_plan, t_src, t_fact, t_seo, t_img, t_pub, t_hist, t_run) = tabs

with t_read:
    with st.container(key="reader"):
        render_markdown(final_md)
    a, b, _ = st.columns([1, 1, 3])
    a.download_button("Download .md", final_md.encode(), f"{safe_slug(title)}.md", "text/markdown", width="stretch")
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{safe_slug(title)}.md", final_md)
        if os.path.isdir("images"):
            for root, _, fs in os.walk("images"):
                for f in fs:
                    z.write(os.path.join(root, f))
    b.download_button("Download bundle", buf.getvalue(), f"{safe_slug(title)}_bundle.zip", "application/zip", width="stretch")

with t_edit:
    edited = st.text_area("Markdown", final_md, height=520, key=f"edit_{ss.blog_id}_{len(final_md)}", label_visibility="collapsed")
    if st.button("Save changes", type="primary"):
        persist(edited, "Edited by hand")
        st.toast("Saved as a new version", icon="💾")
        st.rerun()

with t_sec:
    if not plan or not out.get("sections"):
        st.info("Section regeneration needs a blog generated with this version of Inkwell.")
    else:
        st.caption("Rewrite one section without re-running the whole blog. Images inside that section are dropped.")
        for idx, (tid, sec_md) in enumerate(sorted(out["sections"], key=lambda x: x[0])):
            with st.expander(sec_md.strip().splitlines()[0].lstrip("# ")):
                note = st.text_input("Instruction (optional)", key=f"ins{tid}", placeholder="e.g. add a code example, shorter, simpler")
                if st.button("Regenerate this section", key=f"rg{tid}"):
                    with st.spinner("Rewriting…"):
                        new = be.regenerate_section(tid, out, note)
                    swapped = be.replace_section(final_md, sec_md, new)
                    if swapped is None:
                        st.error("Could not find this section in the text (heading was edited). Edit it by hand instead.")
                    else:
                        out["sections"] = [[i, new if i == tid else s] for i, s in out["sections"]]
                        persist(swapped, f"Regenerated section {tid}")
                        st.rerun()

with t_plan:
    if not plan:
        st.info("No plan saved for this blog.")
    else:
        c = st.columns(3)
        c[0].write(f"**Audience**  \n{plan['audience']}")
        c[1].write(f"**Tone**  \n{plan['tone']}")
        c[2].write(f"**Kind**  \n{plan['blog_kind']}")
        st.dataframe(pd.DataFrame([{"#": t["id"], "Section": t["title"], "Words": t["target_words"],
                                    "Research": t["requires_research"], "Citations": t["requires_citations"],
                                    "Code": t["requires_code"]} for t in plan["tasks"]]),
                     width="stretch", hide_index=True)

with t_src:
    if not evidence:
        st.info("No sources. The topic ran closed-book, or no Tavily key/results were available.")
    else:
        st.dataframe(pd.DataFrame(evidence)[["title", "published_at", "source", "url"]], width="stretch",
                     hide_index=True, column_config={"url": st.column_config.LinkColumn("Link")})

with t_fact:
    fr = out.get("fact_report") or {}
    if not fr:
        st.info("No fact-check ran for this blog.")
    else:
        st.write(fr.get("summary", ""))
        for i in fr.get("issues", []):
            st.markdown(f"<span class='sev-{i['severity']}'>{i['severity'].title()}</span> · **{i['section']}**  \n"
                        f"“{i['claim']}”  \n{i['problem']}", unsafe_allow_html=True)
            st.divider()
        if not fr.get("issues") and not fr.get("skipped"):
            st.success("No unsupported claims found.")

with t_seo:
    seo, soc = out.get("seo") or {}, out.get("social") or {}
    if not seo and not soc:
        st.info("SEO and social posts were turned off for this blog.")
    if seo:
        st.subheader("SEO")
        st.text_input("Meta description", seo.get("meta_description", ""), disabled=True)
        st.text_input("Slug", seo.get("slug", ""), disabled=True)
        st.markdown("".join(f"<span class='chip'>{k}</span>" for k in seo.get("keywords", [])), unsafe_allow_html=True)
        st.write("**Alternative titles**")
        for t in seo.get("title_options", []):
            st.code(t, language=None)
    if soc:
        st.subheader("LinkedIn post")
        st.code(soc.get("linkedin_post", ""), language=None)
        st.subheader("X / Twitter thread")
        for n, tw in enumerate(soc.get("tweet_thread", []), 1):
            st.code(f"{n}/ {tw}", language=None)

with t_img:
    files = sorted(os.path.join("images", f) for f in os.listdir("images")) if os.path.isdir("images") else []
    used = [s["filename"] for s in out.get("image_specs", [])]
    files = [f for f in files if os.path.basename(f) in used] or ([] if used else files)
    if not files:
        st.info("No images for this blog.")
    cols = st.columns(2)
    for i, f in enumerate(files):
        cols[i % 2].image(f, caption=os.path.basename(f), width="stretch")
    if out.get("image_specs"):
        with st.expander("Image prompts"):
            st.json(out["image_specs"])

with t_pub:
    miss = pub.status()
    platform = st.selectbox("Platform", list(miss))
    if miss[platform]:
        st.warning(f"Add {', '.join(miss[platform])} to your .env file to enable {platform}.")
    seo = out.get("seo") or {}
    p_title = st.text_input("Title", title)
    p_tags = st.text_input("Tags (comma separated)", ", ".join((seo.get("keywords") or [])[:4]))
    p_desc = st.text_input("Description", seo.get("meta_description", ""))
    live = st.checkbox("Publish live (otherwise save as draft where supported)")
    if platform == "Hashnode":
        st.caption("Hashnode publishes immediately through this API.")
    if platform == "Medium":
        st.caption("Medium no longer issues new API tokens; this works only with an existing one.")
    if "](images/" in final_md:
        st.caption("Local images are not uploaded. Host them first or the posted article will show broken images.")
    if st.button(f"Send to {platform}", type="primary", disabled=bool(miss[platform])):
        try:
            with st.spinner("Publishing…"):
                url = pub.publish(platform, p_title, final_md, [t for t in p_tags.split(",") if t.strip()],
                                  p_desc, seo.get("slug") or safe_slug(p_title), live)
            st.success(f"Done: {url}")
        except Exception as e:
            st.error(f"Publishing failed: {e}")

with t_hist:
    vers = store.list_versions(ss.blog_id) if ss.blog_id else []
    if len(vers) < 2:
        st.info("History appears after your second saved version (edit, regenerate a section, or restore).")
    else:
        lab = {v["id"]: f"{time.strftime('%d %b %H:%M', time.localtime(v['created']))} · {v['note']}" for v in vers}
        ids = list(lab)
        c1, c2 = st.columns(2)
        old_id = c1.selectbox("Older", ids, index=min(1, len(ids) - 1), format_func=lab.get)
        new_id = c2.selectbox("Newer", ids, index=0, format_func=lab.get)
        by_id = {v["id"]: v["md"] for v in vers}
        diff = "\n".join(difflib.unified_diff(by_id[old_id].splitlines(), by_id[new_id].splitlines(),
                                              "older", "newer", lineterm="", n=2))
        st.code(diff or "No differences.", language="diff")
        if st.button("Restore the older version"):
            persist(by_id[old_id], f"Restored: {lab[old_id]}")
            st.rerun()

with t_run:
    u = out.get("usage") or {}
    c = st.columns(3)
    c[0].metric("Input tokens", f"{sum(x['input_tokens'] for x in u.values()):,}")
    c[1].metric("Output tokens", f"{sum(x['output_tokens'] for x in u.values()):,}")
    c[2].metric("Total time", f"{out.get('elapsed', 0):.0f}s")
    st.caption("Cost is an estimate from list prices set in PRICES at the top of bwa_frontend.py.")
    if out.get("timings"):
        st.dataframe(pd.DataFrame(out["timings"], columns=["Step finished", "Seconds since start"]),
                     width="stretch", hide_index=True)
    if os.getenv("LANGSMITH_TRACING") == "true" or os.getenv("LANGCHAIN_TRACING_V2") == "true":
        st.success("LangSmith tracing is on. Open smith.langchain.com to see every call, token and latency.")
    else:
        st.info("For full traces, add LANGSMITH_TRACING=true, LANGSMITH_API_KEY=... and LANGSMITH_PROJECT=inkwell to .env.")
    st.text_area("Event log", "\n".join(ss.logs[-80:]), height=240)