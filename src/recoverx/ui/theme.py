"""RecoverX v0.4 visual identity: tokens, CSS and small HTML helpers.

All helpers escape their text. Decorative HTML never carries controls; every
interactive element on the page is a real Streamlit widget.
"""
from __future__ import annotations

from html import escape

LOGO_SVG = """<svg viewBox="0 0 48 48" width="{size}" height="{size}" aria-hidden="true">
<defs><linearGradient id="rxg" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#22d3ee"/><stop offset=".55" stop-color="#3b82f6"/><stop offset="1" stop-color="#8b5cf6"/></linearGradient></defs>
<rect x="2" y="2" width="44" height="44" rx="12" fill="#0b1324" stroke="url(#rxg)" stroke-width="2"/>
<path d="M15 33V15h9.5a5.5 5.5 0 0 1 0 11H15m9-0 7.5 7" fill="none" stroke="url(#rxg)" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="34" cy="15" r="2.6" fill="#22d3ee"/></svg>"""

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root {
  --rx-bg:#070b14; --rx-bg2:#0a1120; --rx-card:#0e1628; --rx-card2:#111b30; --rx-border:#1d2a45; --rx-border2:#2a3a5c;
  --rx-text:#e6edf7; --rx-muted:#93a3bf; --rx-dim:#6b7b98;
  --rx-cyan:#22d3ee; --rx-blue:#3b82f6; --rx-purple:#8b5cf6;
  --rx-ok:#34d399; --rx-warn:#fbbf24; --rx-bad:#f87171;
  --rx-grad:linear-gradient(120deg,#22d3ee 0%,#3b82f6 55%,#8b5cf6 100%);
  --rx-radius:16px;
}
html, body, .stApp, [class*="css"] { font-family:'Inter','Segoe UI Variable','Segoe UI',system-ui,sans-serif; }
.stApp { background:
  radial-gradient(1200px 600px at 100% -10%, rgba(59,130,246,.13), transparent 60%),
  radial-gradient(900px 500px at -10% 10%, rgba(139,92,246,.10), transparent 55%),
  linear-gradient(180deg,#070b14 0%,#080d18 100%); color:var(--rx-text); }
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="collapsedControl"] { display:none !important; }
header[data-testid="stHeader"] { background:transparent; height:0; }
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"] { display:none !important; }
.block-container { max-width:1180px; padding:1.4rem 1.6rem 4rem; }
h1,h2,h3,h4 { letter-spacing:-.02em; color:var(--rx-text); }
code, pre, .rx-mono { font-family:'JetBrains Mono',Consolas,monospace !important; }
p, li, label, .stMarkdown { color:var(--rx-text); }
[data-testid="stCaptionContainer"], .stCaption { color:var(--rx-muted) !important; }

/* header */
.rx-top { display:flex; align-items:center; justify-content:space-between; gap:18px; flex-wrap:wrap;
  padding:16px 20px; margin:4px 0 18px; border:1px solid var(--rx-border); border-radius:20px;
  background:linear-gradient(135deg,rgba(17,27,48,.92),rgba(11,18,34,.92)); box-shadow:0 10px 40px rgba(0,0,0,.35);
  animation:rxFade .45s ease both; }
.rx-brand { display:flex; align-items:center; gap:14px; }
.rx-brand h1 { margin:0; font-size:1.55rem; font-weight:700; line-height:1.1; padding:0; }
.rx-brand h1 span { background:var(--rx-grad); -webkit-background-clip:text; background-clip:text; color:transparent; }
.rx-brand small { display:block; color:var(--rx-muted); font-size:.78rem; letter-spacing:.14em; text-transform:uppercase; margin-top:3px; }
.rx-chips { display:flex; flex-wrap:wrap; gap:8px; }
.rx-chip { display:inline-flex; align-items:center; gap:7px; padding:6px 11px; border-radius:999px; font-size:.78rem;
  font-weight:600; border:1px solid var(--rx-border2); background:rgba(14,22,40,.8); color:var(--rx-muted); }
.rx-chip i { width:8px; height:8px; border-radius:50%; display:inline-block; background:var(--rx-dim); }
.rx-chip.ok i { background:var(--rx-ok); box-shadow:0 0 8px rgba(52,211,153,.7); }
.rx-chip.warn i { background:var(--rx-warn); } .rx-chip.bad i { background:var(--rx-bad); }
.rx-chip.ver { color:var(--rx-cyan); border-color:rgba(34,211,238,.35); }

/* step cards = keyed Streamlit containers */
div[class*="st-key-rx-step-"] { border:1px solid var(--rx-border) !important; border-radius:var(--rx-radius) !important;
  background:linear-gradient(180deg,rgba(17,27,48,.86),rgba(13,20,37,.86)); padding:18px 20px 14px !important;
  margin-bottom:14px; transition:border-color .25s ease, box-shadow .25s ease, transform .25s ease;
  animation:rxFade .5s ease both; }
div[class*="st-key-rx-step-"]:hover { border-color:var(--rx-border2) !important; box-shadow:0 0 0 1px rgba(34,211,238,.10), 0 12px 32px rgba(0,0,0,.28); }
div.st-key-rx-step-4 { border-color:rgba(59,130,246,.35) !important; }
.rx-step { display:flex; align-items:flex-start; gap:14px; margin-bottom:6px; }
.rx-num { flex:0 0 34px; height:34px; border-radius:11px; display:grid; place-items:center; font-weight:700; font-size:.95rem;
  color:#04111c; background:var(--rx-grad); box-shadow:0 4px 18px rgba(59,130,246,.35); }
.rx-num.done { background:#123b31; color:var(--rx-ok); box-shadow:none; border:1px solid rgba(52,211,153,.45); }
.rx-step h3 { margin:0 !important; padding:0 !important; font-size:1.08rem; font-weight:650; }
.rx-step p { margin:2px 0 0; color:var(--rx-muted); font-size:.86rem; }

/* device and info cards (display only) */
.rx-grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:10px; margin:6px 0 4px; }
.rx-dev { border:1px solid var(--rx-border); border-radius:13px; padding:12px 14px; background:rgba(9,15,28,.7); font-size:.83rem; }
.rx-dev b { color:var(--rx-text); font-size:.9rem; } .rx-dev .m { color:var(--rx-muted); }
.rx-dev.blocked { opacity:.72; border-style:dashed; }
.rx-dev .why { color:#f5b8b8; font-size:.78rem; margin-top:6px; }
.rx-kv { display:grid; grid-template-columns:auto 1fr; gap:4px 14px; font-size:.84rem; }
.rx-kv span:nth-child(odd) { color:var(--rx-muted); } .rx-kv span:nth-child(even) { color:var(--rx-text); word-break:break-all; }

/* radio as selectable cards (Streamlit 1.5x+: radiogroup > div[data-selected] > label + caption) */
div[class*="st-key-rx-pick"] .stElementContainer, div[class*="st-key-rx-pick"] .stRadio { width:100% !important; }
div[class*="st-key-rx-pick"] div[role="radiogroup"] { display:grid !important; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:10px; width:100%; }
div[class*="st-key-rx-pick"] div[role="radiogroup"] > div { margin:0 !important; padding:12px 14px 10px; border-radius:13px; cursor:pointer;
  border:1px solid var(--rx-border); background:rgba(9,15,28,.65); transition:border-color .18s ease, background .18s ease, transform .18s ease, box-shadow .18s ease; }
div[class*="st-key-rx-pick"] div[role="radiogroup"] > div:hover { border-color:rgba(34,211,238,.55); background:rgba(17,30,52,.8); transform:translateY(-1px); }
div[class*="st-key-rx-pick"] div[role="radiogroup"] > div[data-selected="true"] { border-color:var(--rx-cyan);
  background:linear-gradient(135deg,rgba(34,211,238,.10),rgba(139,92,246,.12)); box-shadow:0 0 0 1px rgba(34,211,238,.35), 0 8px 24px rgba(34,211,238,.08); }
div[class*="st-key-rx-pick"] div[role="radiogroup"] label p { font-weight:650; font-size:.95rem; }
div[class*="st-key-rx-pick"] [data-testid="stRadioCaption"] p { font-size:.8rem; line-height:1.4; }

/* buttons */
.stButton > button, .stDownloadButton > button { border-radius:11px; font-weight:600; border:1px solid var(--rx-border2);
  transition:transform .15s ease, box-shadow .2s ease, border-color .2s ease; }
.stButton > button:hover, .stDownloadButton > button:hover { transform:translateY(-1px); border-color:var(--rx-cyan); }
.stButton > button[kind="primary"] { background:var(--rx-grad); color:#04111c; border:0; box-shadow:0 6px 22px rgba(59,130,246,.35); }
.stButton > button[kind="primary"]:disabled { background:#1a2540; color:#6b7b98; box-shadow:none; }
.stButton > button:focus-visible { outline:2px solid var(--rx-cyan); outline-offset:2px; }

/* inputs */
[data-baseweb="input"], [data-baseweb="select"] > div, textarea { border-radius:10px !important; }
[data-testid="stExpander"] { border:1px solid var(--rx-border) !important; border-radius:13px !important; background:rgba(9,15,28,.55); }
[data-testid="stMetric"] { background:rgba(9,15,28,.7); border:1px solid var(--rx-border); border-radius:13px; padding:12px 14px; }
[data-testid="stMetricLabel"] p { color:var(--rx-muted) !important; font-size:.78rem; }
[data-testid="stMetricValue"] { font-variant-numeric:tabular-nums; font-size:1.45rem; }
[data-testid="stDataFrame"] { border:1px solid var(--rx-border); border-radius:12px; overflow:hidden; }
[data-testid="stAlert"] { border-radius:12px; }

/* pipeline + progress */
.rx-pipe { display:flex; flex-wrap:wrap; gap:6px; margin:8px 0 12px; }
.rx-pipe div { flex:1 1 110px; padding:9px 10px; border-radius:11px; border:1px solid var(--rx-border); font-size:.8rem;
  color:var(--rx-dim); background:rgba(9,15,28,.6); text-align:center; font-weight:600; }
.rx-pipe div.done { color:var(--rx-ok); border-color:rgba(52,211,153,.4); background:rgba(18,59,49,.35); }
.rx-pipe div.active { color:var(--rx-cyan); border-color:rgba(34,211,238,.6); background:rgba(34,211,238,.08);
  box-shadow:0 0 0 1px rgba(34,211,238,.2); animation:rxPulse 1.8s ease-in-out infinite; }
.rx-pipe div.fail { color:var(--rx-bad); border-color:rgba(248,113,113,.5); }
.rx-bar { height:10px; border-radius:999px; background:#121c31; overflow:hidden; border:1px solid var(--rx-border); }
.rx-bar > span { display:block; height:100%; background:var(--rx-grad); border-radius:999px; transition:width .6s ease; }
.rx-bar.indet > span { width:30% !important; animation:rxSlide 1.6s ease-in-out infinite; }
.rx-stats { display:flex; flex-wrap:wrap; gap:18px; margin-top:8px; color:var(--rx-muted); font-size:.82rem; }
.rx-stats b { color:var(--rx-text); font-variant-numeric:tabular-nums; }

/* outcome banner */
.rx-banner { border-radius:14px; padding:14px 16px; border:1px solid; margin:4px 0 12px; display:flex; gap:12px; align-items:flex-start; }
.rx-banner b { display:block; font-size:1rem; margin-bottom:2px; }
.rx-banner.success { border-color:rgba(52,211,153,.5); background:rgba(18,59,49,.35); }
.rx-banner.partial, .rx-banner.no_files, .rx-banner.acquired_with_errors, .rx-banner.cancelled { border-color:rgba(251,191,36,.5); background:rgba(66,52,20,.35); }
.rx-banner.failed, .rx-banner.blocked, .rx-banner.disconnected { border-color:rgba(248,113,113,.5); background:rgba(70,26,30,.35); }
.rx-empty { border:1px dashed var(--rx-border2); border-radius:13px; padding:18px; color:var(--rx-muted); text-align:center; font-size:.88rem; }
.rx-foot { color:var(--rx-dim); font-size:.76rem; text-align:center; margin-top:26px; }

@keyframes rxFade { from { opacity:0; transform:translateY(6px); } to { opacity:1; transform:none; } }
@keyframes rxPulse { 0%,100% { box-shadow:0 0 0 1px rgba(34,211,238,.15); } 50% { box-shadow:0 0 0 4px rgba(34,211,238,.10); } }
@keyframes rxSlide { 0% { transform:translateX(-110%); } 100% { transform:translateX(360%); } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation:none !important; transition:none !important; } }
@media (max-width: 760px) { .block-container { padding:1rem .8rem 3rem; } .rx-top { padding:14px; } }
</style>
"""


def e(text) -> str:
    return escape("" if text is None else str(text))


def header_html(version: str, chips: list[tuple[str, str]]) -> str:
    chip_html = "".join(f'<span class="rx-chip {e(state)}"><i></i>{e(label)}</span>' for label, state in chips)
    return (f'<div class="rx-top"><div class="rx-brand">{LOGO_SVG.format(size=46)}<div><h1>Recover<span>X</span></h1>'
            f'<small>Forensic file recovery · Quick Recovery</small></div></div>'
            f'<div class="rx-chips"><span class="rx-chip ver">v{e(version)}</span>{chip_html}</div></div>')


def step_html(n: int, title: str, subtitle: str, done: bool = False) -> str:
    return (f'<div class="rx-step"><div class="rx-num{" done" if done else ""}">{"✓" if done else n}</div>'
            f'<div><h3>{e(title)}</h3><p>{e(subtitle)}</p></div></div>')


def kv_html(rows: list[tuple[str, object]]) -> str:
    return '<div class="rx-kv">' + "".join(f"<span>{e(k)}</span><span>{e(v)}</span>" for k, v in rows) + "</div>"


def pipeline_html(steps: list[tuple[str, str]]) -> str:
    return '<div class="rx-pipe">' + "".join(f'<div class="{e(s)}">{e(label)}</div>' for label, s in steps) + "</div>"


def bar_html(fraction: float | None) -> str:
    if fraction is None:
        return '<div class="rx-bar indet" role="progressbar" aria-label="Working"><span></span></div>'
    pct = max(0.0, min(1.0, fraction)) * 100
    return (f'<div class="rx-bar" role="progressbar" aria-valuenow="{pct:.0f}" aria-valuemin="0" aria-valuemax="100">'
            f'<span style="width:{pct:.2f}%"></span></div>')


def stats_html(items: list[tuple[str, object]]) -> str:
    return '<div class="rx-stats">' + "".join(f"<span>{e(k)} <b>{e(v)}</b></span>" for k, v in items) + "</div>"


def banner_html(kind: str, title: str, message: str) -> str:
    return f'<div class="rx-banner {e(kind)}"><div><b>{e(title)}</b>{e(message)}</div></div>'
