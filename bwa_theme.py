"""Shared CSS theme for the Streamlit UI."""
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap');

:root{
  --ink:#0b1a20; --ink-2:#14303a; --deep:#071217;
  --field:#10272f;
  --card:rgba(255,255,255,.06); --card-strong:rgba(255,255,255,.10);
  --line:rgba(255,255,255,.14); --text:#e8f1f4; --muted:#a9c0c8;
  --accent:#f5a43a; --accent-2:#ff6b6b; --teal:#2dd4bf; --ok:#34d399;
}

html, body, [class*="css"], .stApp { font-family:'Plus Jakarta Sans', system-ui, sans-serif; }

/* ===== Eye-catching background ===== */
.stApp {
  color: var(--text);
  background:
    radial-gradient(900px 500px at 8% -5%,  rgba(245,164,58,.28), transparent 60%),
    radial-gradient(800px 600px at 95% 5%,  rgba(45,212,191,.22), transparent 60%),
    radial-gradient(900px 700px at 70% 105%, rgba(255,107,107,.16), transparent 60%),
    linear-gradient(160deg, #071217 0%, #0d2530 55%, #0a1a22 100%);
  background-attachment: fixed;
}
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 2rem; max-width: 1200px; }

/* ===== Readable text everywhere ===== */
.stApp label, .stApp label p, .stApp [data-testid="stWidgetLabel"] p,
.stApp .stMarkdown p, .stApp .stMarkdown li,
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { color: var(--text); }
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
.stApp [data-testid="stCheckbox"] p, .stApp [data-testid="stToggle"] p, .stApp [data-testid="stRadio"] p { color: var(--text) !important; }

/* ===== Sidebar ===== */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #0a1a21 0%, #0f2a34 100%);
  border-right: 1px solid var(--line);
}
section[data-testid="stSidebar"] * { color:#e6eef0; }
section[data-testid="stSidebar"] h1, section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3 { color:#fff; font-weight:700; }
section[data-testid="stSidebar"] hr { border-color: var(--line); }

/* ===== Hero ===== */
.hero { padding: 1.6rem 1.8rem; border-radius: 20px; color:#fff;
        background:
          radial-gradient(500px 200px at 100% 0%, rgba(45,212,191,.35), transparent 70%),
          radial-gradient(500px 220px at 0% 100%, rgba(245,164,58,.30), transparent 70%),
          linear-gradient(135deg, #10303b, #0b1d25);
        border:1px solid var(--line);
        box-shadow: 0 10px 40px rgba(0,0,0,.35);
        display:flex; justify-content:space-between; align-items:center; gap:1rem; margin-bottom:1.1rem; }
.hero h1 { font-family:'Newsreader', Georgia, serif; font-weight:600; font-size:2.3rem; margin:0; color:#fff; }
.hero p  { margin:.25rem 0 0; color:#b9ced5; font-size:.95rem; }
.hero .badge { background:rgba(255,255,255,.08); border:1px solid rgba(255,255,255,.22); border-radius:999px;
               padding:.35rem .8rem; font-size:.8rem; color:#e3f0f3; white-space:nowrap; backdrop-filter: blur(6px); }

/* ===== Pipeline tracker ===== */
.pipe { display:flex; gap:.5rem; flex-wrap:wrap; margin:.2rem 0 1rem; }
.step { flex:1 1 140px; background:var(--card); border:1px solid var(--line); border-radius:14px;
        padding:.7rem .85rem; backdrop-filter: blur(8px); }
.step b { display:block; font-size:.9rem; color:#fff; }
.step span { font-size:.78rem; color:var(--muted); }
.step.done   { border-color:var(--ok); background:rgba(52,211,153,.12); }
.step.done b::before { content:"✓ "; color:var(--ok); }
.step.active { border-color:var(--accent); background:rgba(245,164,58,.16);
               box-shadow:0 0 0 3px rgba(245,164,58,.18), 0 0 24px rgba(245,164,58,.25); }
.step.active b::before { content:"● "; color:var(--accent); }
.step.skip   { opacity:.5; border-style:dashed; }

/* ===== Metrics ===== */
[data-testid="stMetric"] { background:var(--card); border:1px solid var(--line);
                           border-radius:16px; padding:.9rem 1.1rem; backdrop-filter: blur(8px);
                           border-top: 3px solid var(--accent); }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p { color:var(--muted) !important; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] * { color:#fff !important; font-weight:700; }

/* ===== Tabs (Read, Edit, Sections, Plan ...) ===== */
.stTabs [data-baseweb="tab-list"] { gap:.25rem; border-bottom:1px solid var(--line); }
.stTabs button[role="tab"], .stTabs [data-baseweb="tab"] {
  border-radius:10px 10px 0 0; padding:.5rem 1rem; font-weight:600;
  color:#b6cbd2 !important; background:transparent; }
.stTabs button[role="tab"] p, .stTabs button[role="tab"] div,
.stTabs [data-baseweb="tab"] p { color: inherit !important; }
.stTabs button[role="tab"]:hover { color:#fff !important; background:rgba(255,255,255,.07); }
.stTabs button[role="tab"][aria-selected="true"] { color:#fff !important; background:rgba(255,255,255,.10); }
.stTabs [data-baseweb="tab-highlight"] { background-color: var(--accent) !important; }
.stTabs [data-baseweb="tab-border"] { background-color: var(--line) !important; }

/* ===== Text inputs, text areas, number inputs, selects ===== */
.stApp [data-baseweb="input"], .stApp [data-baseweb="base-input"],
.stApp [data-baseweb="textarea"], .stApp [data-baseweb="select"] > div {
  background: var(--field) !important;
  border: 1px solid rgba(255,255,255,.22) !important;
  border-radius: 10px !important;
}
.stApp [data-baseweb="input"]:focus-within, .stApp [data-baseweb="textarea"]:focus-within,
.stApp [data-baseweb="select"]:focus-within > div { border-color: var(--accent) !important; }
.stApp input, .stApp textarea {
  background: transparent !important;
  color:#fff !important; -webkit-text-fill-color:#fff !important; caret-color: var(--accent);
}
.stApp input::placeholder, .stApp textarea::placeholder {
  color:#7f9aa3 !important; -webkit-text-fill-color:#7f9aa3 !important; opacity:1; }
.stApp input:disabled, .stApp textarea:disabled {
  color:#d6e5ea !important; -webkit-text-fill-color:#d6e5ea !important; opacity:1; }
.stApp [data-baseweb="input"] svg, .stApp [data-baseweb="select"] svg { fill:#d6e5ea !important; color:#d6e5ea !important; }
.stApp [data-baseweb="select"] div, .stApp [data-baseweb="select"] span { color:#fff !important; }
.stApp [data-testid="stNumberInput"] button { background: rgba(255,255,255,.08) !important; color:#fff !important; border-color: transparent !important; }
.stApp [data-testid="stDateInput"] input { color:#fff !important; -webkit-text-fill-color:#fff !important; }

/* Dropdown menus (selectbox lists, date picker) */
[data-baseweb="popover"], [data-baseweb="popover"] > div, [data-baseweb="menu"],
[data-baseweb="popover"] ul { background:#10272f !important; color:#fff !important; }
[data-baseweb="popover"] li, [data-baseweb="popover"] li * { color:#fff !important; background:transparent; }
[data-baseweb="popover"] li:hover, [data-baseweb="popover"] li[aria-selected="true"] { background: rgba(245,164,58,.22) !important; }

/* Expanders, forms, alerts */
.stApp [data-testid="stExpander"] { background:var(--card); border:1px solid var(--line); border-radius:14px; }
.stApp [data-testid="stExpander"] summary, .stApp [data-testid="stExpander"] summary p { color:#fff !important; }
.stApp [data-testid="stForm"] { background:var(--card); border:1px solid var(--line); border-radius:16px; }
.stApp [data-testid="stAlert"] { border-radius:12px; }
.stApp [data-testid="stAlert"] p, .stApp [data-testid="stAlert"] li { color:#eef6f8 !important; }

/* ===== Buttons (normal, download, form submit) ===== */
.stApp .stButton > button,
.stApp [data-testid="stDownloadButton"] > button,
.stApp [data-testid="stFormSubmitButton"] > button,
.stApp button[data-testid="stBaseButton-secondary"] {
  background: rgba(255,255,255,.09) !important;
  color:#fff !important;
  border:1px solid rgba(255,255,255,.25) !important;
  border-radius:10px !important;
  font-weight:600;
}
.stApp .stButton > button *, .stApp [data-testid="stDownloadButton"] > button *,
.stApp [data-testid="stFormSubmitButton"] > button *,
.stApp button[data-testid="stBaseButton-secondary"] * { color:#fff !important; }
.stApp .stButton > button:hover,
.stApp [data-testid="stDownloadButton"] > button:hover,
.stApp [data-testid="stFormSubmitButton"] > button:hover,
.stApp button[data-testid="stBaseButton-secondary"]:hover {
  background: rgba(245,164,58,.20) !important;
  border-color: var(--accent) !important;
  box-shadow: 0 0 16px rgba(245,164,58,.25);
}

/* Primary buttons: orange gradient, dark text */
.stApp .stButton > button[kind="primary"],
.stApp [data-testid="stFormSubmitButton"] > button[kind="primary"],
.stApp button[data-testid="stBaseButton-primary"],
.stApp button[data-testid="stBaseButton-primaryFormSubmit"] {
  background: linear-gradient(135deg, #f5a43a, #ff7a3d) !important;
  border:none !important; color:#1a1205 !important; font-weight:700;
  box-shadow: 0 6px 20px rgba(245,164,58,.35);
}
.stApp .stButton > button[kind="primary"] *,
.stApp [data-testid="stFormSubmitButton"] > button[kind="primary"] *,
.stApp button[data-testid="stBaseButton-primary"] *,
.stApp button[data-testid="stBaseButton-primaryFormSubmit"] * { color:#1a1205 !important; }
.stApp .stButton > button[kind="primary"]:hover,
.stApp button[data-testid="stBaseButton-primary"]:hover,
.stApp button[data-testid="stBaseButton-primaryFormSubmit"]:hover {
  filter: brightness(1.08); box-shadow: 0 8px 26px rgba(245,164,58,.5);
}
.stApp button:disabled { opacity:.45 !important; }

/* ===== Reading view (dark glass card, light text) ===== */
.stApp .st-key-reader { background: rgba(8,24,31,.80); border:1px solid var(--line); border-radius:18px;
                 padding:2.2rem 3rem; max-width:820px; margin:auto;
                 box-shadow: 0 20px 60px rgba(0,0,0,.45); backdrop-filter: blur(10px); }
.stApp .st-key-reader p, .stApp .st-key-reader li { font-family:'Newsreader', Georgia, serif;
                 font-size:1.14rem; line-height:1.75; color:#dbe8ec !important; }
.stApp .st-key-reader h1, .stApp .st-key-reader h2, .stApp .st-key-reader h3, .stApp .st-key-reader h4 {
                 font-family:'Newsreader', Georgia, serif; color:#ffffff !important; letter-spacing:-.01em; }
.stApp .st-key-reader h2 { border-bottom:1px solid var(--line); padding-bottom:.3rem; }
.stApp .st-key-reader strong { color:#ffffff !important; }
.stApp .st-key-reader em, .stApp .st-key-reader td, .stApp .st-key-reader th { color:#dbe8ec !important; }
.stApp .st-key-reader blockquote { border-left:3px solid var(--accent); color:#c4d8de !important; background: rgba(255,255,255,.04); }
.stApp .st-key-reader a { color:#ffb35c !important; }
.stApp .st-key-reader [data-testid="stCaptionContainer"],
.stApp .st-key-reader [data-testid="stCaptionContainer"] p { color:#9fb6be !important; }
.stApp .st-key-reader code { font-size:.9rem; background: rgba(255,255,255,.10); color:#ffd9a3; border-radius:6px; padding:.1rem .35rem; }
.stApp .st-key-reader pre code { background:transparent; color:#e8f1f4; }

/* ===== Empty state ===== */
.empty { text-align:center; padding:3.5rem 1rem; color:var(--muted); background:var(--card);
         border:1px dashed rgba(255,255,255,.25); border-radius:18px; backdrop-filter: blur(8px); }
.empty h3 { color:#fff; font-family:'Newsreader', serif; }

/* Review / fact-check severity chips */
.sev-high{color:#ff7b7b;font-weight:700} .sev-medium{color:#f5a43a;font-weight:700} .sev-low{color:#7dd3fc;font-weight:700}
.chip { display:inline-block; background:rgba(245,164,58,.15); border:1px solid rgba(245,164,58,.5);
        color:#ffd9a3; border-radius:999px; padding:.15rem .65rem; margin:0 .3rem .3rem 0; font-size:.8rem; }

@media (max-width:700px){ .stApp .st-key-reader{ padding:1.2rem; } .hero{flex-direction:column; align-items:flex-start;} }
</style>
"""