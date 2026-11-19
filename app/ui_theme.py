"""Visual layer for the Streamlit app: CSS theme, animated isometric (3D-style) illustration,
workflow stepper and supplier cards. Pure presentation - no business logic here."""
import html
import math

# ---------------------------------------------------------------- CSS theme
CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,500;12..96,700;12..96,800&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
:root {
  --paper: #F7F9FC; --surface: #FFFFFF; --ink: #14213D; --ink-2: #3D4A63; --muted: #66728A;
  --rule: #DDE3EC; --teal: #0E6E6B; --teal-2: #0B5855; --teal-tint: #E3F1F0;
  --pass: #1F7A4D; --pass-tint: #E4F3EA; --amber: #B26A00; --amber-tint: #FBF0DD;
  --red: #B42318; --red-tint: #FCE9E7;
}
html, body, .stApp, .stMarkdown, p, label, input, textarea, button, li, td, th {
  font-family: 'IBM Plex Sans', system-ui, sans-serif; font-variant-numeric: tabular-nums; }
h1, h2, h3, .display { font-family: 'Bricolage Grotesque', 'IBM Plex Sans', sans-serif !important;
  letter-spacing: -0.015em; color: var(--ink); }
h1 { font-weight: 800 !important; } h2, h3 { font-weight: 700 !important; }
/* Streamlit draws its icons with an icon font: never override it, or icon names show up as text */
[data-testid="stIconMaterial"], span[class*="material-symbols"], .material-icons, .material-symbols-rounded {
  font-family: 'Material Symbols Rounded' !important; }
.stApp { background: var(--paper); color: var(--ink); }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.4rem; max-width: 1240px; }

/* ---------- sidebar: solid ink, like the cover of a ledger ---------- */
section[data-testid="stSidebar"] { background: var(--ink); }
section[data-testid="stSidebar"] * { color: #D9E1EE !important; }
section[data-testid="stSidebar"] > div { overflow-x: hidden; }
section[data-testid="stSidebar"] input { color: var(--ink) !important; background: #fff !important; border-radius: 8px; }
section[data-testid="stSidebar"] [data-testid="InputInstructions"],
section[data-testid="stSidebar"] [data-testid="InputInstructions"] * { color: var(--muted) !important; }
section[data-testid="stSidebar"] input::placeholder { color: #98A2B3 !important; }
section[data-testid="stSidebar"] [role="radiogroup"] label { padding: .45rem .6rem; border-radius: 8px; margin-bottom: 1px; }
section[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(255,255,255,.07); }
.side-brand { display: flex; align-items: center; gap: .7rem; margin: .1rem 0 1.4rem; }
.side-mark { width: 36px; height: 36px; border-radius: 9px; background: var(--teal); display: grid; place-items: center; }
.side-mark svg { width: 20px; height: 20px; }
.side-title { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; font-size: 1.12rem; color: #fff !important; }
.side-sub { font-size: .78rem; opacity: .7; }

/* ---------- controls ---------- */
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 8px; font-weight: 600; border: 1px solid var(--rule); }
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: var(--teal); border-color: var(--teal); color: #fff; }
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover,
.stDownloadButton > button[kind="primary"]:hover { background: var(--teal-2); border-color: var(--teal-2); }
.stButton > button:disabled, .stFormSubmitButton > button:disabled, .stDownloadButton > button:disabled {
  opacity: .45; filter: grayscale(.7); cursor: not-allowed; }
:focus-visible { outline: 2px solid var(--teal) !important; outline-offset: 2px; }
.st-key-nav_back button { border: 0 !important; background: transparent !important; color: var(--teal) !important;
  padding: 0 .2rem !important; min-height: 0; font-weight: 600; }
.st-key-nav_back button:hover { text-decoration: underline; }
iframe[height="0"] { display: block; }
.element-container:has(> iframe[height="0"]) { display: none; }

/* ---------- metrics: a figure and its label, nothing more ---------- */
div[data-testid="stMetric"] { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 14px 18px; }
div[data-testid="stMetricValue"] { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 700; color: var(--ink); }
[data-testid="stMetricLabel"] p, [data-testid="stMetricLabel"] div { white-space: normal !important; overflow: visible !important; color: var(--muted); }

/* ---------- tabs: an underline, like section tabs in a binder ---------- */
.stTabs [data-baseweb="tab-list"] { gap: 4px; border-bottom: 1px solid var(--rule); }
.stTabs [data-baseweb="tab"] { padding: 10px 14px; font-weight: 600; color: var(--muted); height: auto; }
.stTabs [aria-selected="true"], .stTabs [aria-selected="true"] p { color: var(--ink) !important; }
.stTabs [data-baseweb="tab-highlight"] { background: var(--teal) !important; height: 3px; }

/* ---------- surfaces ---------- */
div[data-testid="stExpander"], div[data-testid="stForm"] { background: var(--surface); border-radius: 10px; border: 1px solid var(--rule); }
div[data-testid="stDataFrame"] { border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
div[data-testid="stAlert"] { border-radius: 10px; }
[data-testid="stHeaderActionElements"], h1 a[href^="#"], h2 a[href^="#"], h3 a[href^="#"] { display: none !important; }

/* ---------- hero: the one bold element ---------- */
.hero { display: grid; grid-template-columns: 1.1fr 1fr; align-items: center; gap: 12px; padding: 34px 38px;
  border-radius: 16px; background: var(--ink); color: #E8EDF5; margin-bottom: 1.4rem; overflow: hidden;
  animation: rise .6s ease-out both; }
@keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
.hero-title { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; font-size: 2.6rem; line-height: 1.05;
  color: #fff; margin: 0 0 14px; letter-spacing: -0.025em; max-width: 15ch; }
.hero-sub { font-size: 1.04rem; line-height: 1.6; color: #C5CFDD; margin: 0 0 18px; max-width: 54ch; }
.hero-note { font-size: .88rem; color: #8FA0B8; }
.hero-art svg { width: 100%; height: auto; }
.float-a { animation: floaty 5s ease-in-out infinite; } .float-b { animation: floaty 5s ease-in-out infinite .7s; }
.float-c { animation: floaty 5s ease-in-out infinite 1.4s; }
@keyframes floaty { 0%,100% { transform: translateY(0); } 50% { transform: translateY(-6px); } }
@media (max-width: 900px) { .hero { grid-template-columns: 1fr; } .hero-title { font-size: 2rem; } }
@media (prefers-reduced-motion: reduce) { .hero, .float-a, .float-b, .float-c, .approved-card * { animation: none !important; } }

/* ---------- how it works: a real sequence, so numbers are earned ---------- */
.steps { display: grid; grid-template-columns: repeat(3, 1fr); gap: 0; margin: .4rem 0 1.4rem;
  border: 1px solid var(--rule); border-radius: 12px; background: var(--surface); }
.steps > div { padding: 18px 20px; } .steps > div + div { border-left: 1px solid var(--rule); }
.steps .n { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; font-size: 1.5rem; color: var(--teal); }
.steps b { display: block; margin: 2px 0 4px; color: var(--ink); }
.steps span { color: var(--ink-2); font-size: .92rem; line-height: 1.5; }
@media (max-width: 900px) { .steps { grid-template-columns: 1fr; } .steps > div + div { border-left: 0; border-top: 1px solid var(--rule); } }

/* ---------- evaluation header + progress ---------- */
.ws-head { background: var(--surface); border: 1px solid var(--rule); border-radius: 12px; padding: 18px 22px 14px; margin-bottom: 1rem; }
.ws-title { display: flex; flex-wrap: wrap; align-items: baseline; gap: 12px; }
.ws-title .rfq { font-family: 'Bricolage Grotesque', sans-serif; font-size: 1.7rem; font-weight: 800; color: var(--ink); }
.ws-title .sub { color: var(--muted); }
.pill { display: inline-block; padding: 3px 10px; border-radius: 6px; font-weight: 600; font-size: .85rem; }
.pill.ok { background: var(--pass-tint); color: var(--pass); } .pill.warn { background: var(--amber-tint); color: var(--amber); }
.pill.bad { background: var(--red-tint); color: var(--red); } .pill.info { background: var(--teal-tint); color: var(--teal-2); }
.stepper { display: flex; align-items: flex-start; margin: 16px 0 4px; }
.step { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 74px; }
.dot { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font-weight: 700; font-size: .82rem;
  background: #fff; border: 2px solid var(--rule); color: var(--muted); }
.step.done .dot { background: var(--pass); border-color: var(--pass); color: #fff; }
.step.current .dot { background: var(--teal); border-color: var(--teal); color: #fff; box-shadow: 0 0 0 4px var(--teal-tint); }
.step.error .dot { background: var(--red); border-color: var(--red); color: #fff; }
.step .lbl { font-size: .78rem; color: var(--muted); text-align: center; }
.step.current .lbl { color: var(--ink); font-weight: 600; }
.bar { flex: 1; height: 2px; background: var(--rule); margin: 13px 4px 0; } .bar.done { background: var(--pass); }
.next { margin-top: 12px; padding: 10px 14px; border-left: 3px solid var(--teal); background: var(--teal-tint);
  color: var(--ink); border-radius: 0 8px 8px 0; font-size: .95rem; }

/* ---------- supplier sheets: verdict as a stamp, colour on the edge ---------- */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 12px; margin: .4rem 0 1.2rem; }
.card { background: var(--surface); border: 1px solid var(--rule); border-left-width: 5px; border-radius: 10px; padding: 16px 18px 14px; }
.card.ok { border-left-color: var(--pass); } .card.warn { border-left-color: var(--amber); } .card.bad { border-left-color: var(--red); }
.card.best { outline: 2px solid var(--teal); outline-offset: -1px; }
.card .top { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.stamp { display: inline-block; white-space: nowrap; padding: 2px 8px; border: 1.5px solid currentColor; border-radius: 4px; font-weight: 600; font-size: .8rem; }
.stamp.ok { color: var(--pass); } .stamp.warn { color: var(--amber); } .stamp.bad { color: var(--red); }
.best-tag { background: var(--teal); color: #fff; font-size: .78rem; font-weight: 600; padding: 3px 8px; border-radius: 4px; }
.card .name { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 700; font-size: 1.08rem; color: var(--ink); margin: 10px 0 6px; line-height: 1.25; }
.card .price { font-family: 'Bricolage Grotesque', sans-serif; font-size: 1.6rem; font-weight: 800; color: var(--ink); }
.card .price small { font-family: 'IBM Plex Sans', sans-serif; font-size: .82rem; color: var(--muted); font-weight: 500; }
.card .total { color: var(--ink-2); font-size: .9rem; margin: 2px 0 10px; }
.card .meta { font-size: .82rem; color: var(--muted); }

/* ---------- decision recorded ---------- */
.approved-card { display: flex; align-items: center; gap: 18px; padding: 18px 22px; border-radius: 12px; margin: 4px 0 14px;
  background: var(--pass-tint); border: 1px solid #B7DEC7; }
.approved-card svg { flex: 0 0 48px; width: 48px; height: 48px; }
.approved-card .ring { fill: none; stroke: var(--pass); stroke-width: 3; stroke-dasharray: 166; stroke-dashoffset: 166; animation: draw .7s ease forwards; }
.approved-card .tick { fill: none; stroke: var(--pass); stroke-width: 4.5; stroke-linecap: round; stroke-linejoin: round;
  stroke-dasharray: 48; stroke-dashoffset: 48; animation: draw .45s .55s ease forwards; }
@keyframes draw { to { stroke-dashoffset: 0; } }
.approved-card .t1 { font-family: 'Bricolage Grotesque', sans-serif; font-weight: 800; color: #12442C; font-size: 1.15rem; }
.approved-card .t2 { color: #1D5C3D; margin-top: 2px; } .approved-card .t3 { color: #2E6B4B; font-size: .85rem; margin-top: 4px; }

.insight { border-left: 3px solid var(--teal); background: var(--surface); border-radius: 0 10px 10px 0; padding: 12px 16px;
  color: var(--ink); margin: 6px 0 14px; line-height: 1.6; border-top: 1px solid var(--rule); border-right: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule); }
</style>
"""


# ---------------------------------------------------------------- isometric 3D illustration
_C, _S = math.cos(math.radians(30)), math.sin(math.radians(30))


def _iso(x, y, z, s=19.0, ox=185.0, oy=118.0):
    return ox + (x - y) * _C * s, oy + (x + y) * _S * s - z * s


def _poly(points, fill, extra=""):
    pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
    return f'<polygon points="{pts}" fill="{fill}" {extra}/>'


def _box(x, y, z, w, d, h, top, left, right, stroke="rgba(255,255,255,.35)"):
    P = lambda a, b, c: _iso(a, b, c)  # noqa: E731
    sw = f'stroke="{stroke}" stroke-width="0.8" stroke-linejoin="round"'
    return "".join([
        _poly([P(x, y + d, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x, y + d, z + h)], left, sw),
        _poly([P(x + w, y, z), P(x + w, y + d, z), P(x + w, y + d, z + h), P(x + w, y, z + h)], right, sw),
        _poly([P(x, y, z + h), P(x + w, y, z + h), P(x + w, y + d, z + h), P(x, y + d, z + h)], top, sw),
    ])


def _sheet(x, y, z, cls):
    """A document lying flat, with text lines on top."""
    out = _box(x, y, z, 3.2, 4.0, 0.18, "#ffffff", "#C9D3E0", "#9AA8BC")
    lines = ""
    for i, frac in enumerate((0.75, 0.55, 0.85, 0.6)):
        y0 = y + 0.7 + i * 0.75
        a, b = _iso(x + 0.45, y0, z + 0.19), _iso(x + 0.45 + 2.3 * frac, y0, z + 0.19)
        color = "#0E6E6B" if i == 0 else "#CBD5E1"
        lines += f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>'
    return f'<g class="{cls}">{out}{lines}</g>'


def hero_svg() -> str:
    defs = ('<defs>'
            '<linearGradient id="ct" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#E3F1F0"/><stop offset="1" stop-color="#9CCFCB"/></linearGradient>'
            '<linearGradient id="cl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#14857F"/><stop offset="1" stop-color="#0B4D4A"/></linearGradient>'
            '<linearGradient id="cr" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#0E6E6B"/><stop offset="1" stop-color="#073B39"/></linearGradient>'
            '<radialGradient id="glow"><stop offset="0" stop-color="#ffffff" stop-opacity=".6"/><stop offset="1" stop-color="#ffffff" stop-opacity="0"/></radialGradient>'
            '</defs>')
    # documents (left), AI cube (centre), cost bars (right) - laid out along the x axis
    docs = _sheet(-7.4, 0.2, 0.0, "float-a") + _sheet(-7.1, -0.1, 0.9, "float-b") + _sheet(-6.8, -0.4, 1.8, "float-c")
    gx, gy = _iso(1.3, 1.3, 2.6)
    cube = (f'<g class="pulse"><circle cx="{gx:.1f}" cy="{gy - 6:.1f}" r="58" fill="url(#glow)" opacity=".35"/>'
            + _box(0.0, 0.0, 0.0, 2.6, 2.6, 2.6, "url(#ct)", "url(#cl)", "url(#cr)")
            + f'<text x="{gx:.1f}" y="{gy + 2:.1f}" text-anchor="middle" font-size="20" font-weight="800" '
              f'fill="#0B4D4A" font-family="Bricolage Grotesque, sans-serif">AI</text></g>')
    bars = ""
    specs = [(2.3, "#CBD5E1", "#94A3B8", "#64748B"), (3.3, "#CBD5E1", "#94A3B8", "#64748B"),
             (1.5, "#BFE5CF", "#3FA16E", "#1F7A4D")]
    for i, (h, top, left, right) in enumerate(specs):
        bars += _box(4.6 + i * 1.05, -2.2 - i * 1.05, 0, 1.1, 1.1, h, top, left, right)
    bx, by = _iso(4.6 + 2 * 1.05 + 0.55, -2.2 - 2 * 1.05 + 0.55, 1.5 + 1.7)
    badge = (f'<g class="float-b"><circle cx="{bx:.1f}" cy="{by:.1f}" r="13" fill="#1F7A4D" stroke="#fff" stroke-width="3"/>'
             f'<path d="M{bx - 5.5:.1f},{by:.1f} l3.8,3.8 l7,-7.5" fill="none" stroke="#fff" stroke-width="2.8" '
             f'stroke-linecap="round" stroke-linejoin="round"/></g>')
    s1, s2 = _iso(-3.8, 1.6, 1.4), _iso(0.0, 1.3, 1.4)
    e1, e2 = _iso(2.6, 1.0, 1.6), _iso(4.6, -1.6, 1.4)
    flow = ""
    for path, delay in ((f"M{s1[0]:.1f},{s1[1]:.1f} Q{(s1[0] + s2[0]) / 2:.1f},{min(s1[1], s2[1]) - 34:.1f} {s2[0]:.1f},{s2[1]:.1f}", "0s"),
                        (f"M{e1[0]:.1f},{e1[1]:.1f} Q{(e1[0] + e2[0]) / 2:.1f},{min(e1[1], e2[1]) - 34:.1f} {e2[0]:.1f},{e2[1]:.1f}", "0.9s")):
        flow += (f'<path d="{path}" fill="none" stroke="rgba(156,207,203,.55)" stroke-width="2" stroke-dasharray="4 6"/>'
                 f'<circle r="4.5" fill="#F2C14E"><animateMotion dur="1.8s" begin="{delay}" repeatCount="indefinite" path="{path}"/></circle>')
    fx, fy = _iso(-0.8, 0.2, 0)
    floor = f'<ellipse cx="{fx + 4:.1f}" cy="{fy + 26:.1f}" rx="190" ry="34" fill="rgba(0,0,0,.28)"/>'
    return (f'<svg viewBox="-15 -25 420 270" xmlns="http://www.w3.org/2000/svg" role="img" '
            f'aria-label="Documents flow into an AI cube and become a comparison chart">'
            f'{defs}{floor}{docs}{flow}{cube}{bars}{badge}</svg>')


# ---------------------------------------------------------------- small HTML components
def _e(s) -> str:
    return html.escape(str(s))


def one_line(s: str) -> str:
    """Markdown treats indented lines as code: emit HTML as a single line."""
    return " ".join(line.strip() for line in s.splitlines() if line.strip())


MARK = ('<svg viewBox="0 0 20 20" fill="none" stroke="#fff" stroke-width="1.8" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M5 2.5h7l3 3v12H5z"/><path d="M8 10.5l2 2 3.5-4"/></svg>')


def sidebar_brand() -> str:
    return one_line(f"""<div class="side-brand"><div class="side-mark">{MARK}</div>
        <div><div class="side-title">RFQ Evaluator</div><div class="side-sub">Supplier quote comparison</div></div></div>""")


def hero() -> str:
    return one_line(f"""<div class="hero"><div class="hero-text">
        <div class="hero-title" role="heading" aria-level="1">Supplier quotes, side by side.</div>
        <p class="hero-sub">Drop in your RFQ and the quotes that came back. We pull out the price, tax,
        delivery and specs from each one, check them against what you asked for, and show you where
        every number came from. The decision stays with you.</p>
        <div class="hero-note">Works with PDF, Excel, Word and CSV files.</div>
        </div><div class="hero-art">{hero_svg()}</div></div>""")


def features() -> str:
    items = [("Upload your documents", "The RFQ and every supplier quote. Files we can't read are flagged straight away."),
             ("Check what was read", "Each price and spec is shown next to the line it came from, so you can correct it."),
             ("Compare and decide", "Suppliers are checked against your requirements. You approve, and it's logged.")]
    cells = "".join(f'<div><div class="n">{i}</div><b>{_e(t)}</b><span>{_e(d)}</span></div>'
                    for i, (t, d) in enumerate(items, 1))
    return f'<div class="steps">{cells}</div>'


STEPS = ["Upload", "AI reading", "Review", "Compare", "Decide"]
STATUS_STEP = {"CREATED": (0, ""), "DOCUMENTS_UPLOADED": (1, ""), "EXTRACTING": (1, ""),
               "EXTRACTION_REVIEW_REQUIRED": (2, ""), "EVALUATING": (3, ""), "READY_FOR_APPROVAL": (4, ""),
               "REJECTED": (2, ""), "FAILED": (1, "error"), "APPROVED": (5, ""), "REPORT_GENERATED": (5, "")}
PILL_KIND = {"APPROVED": "ok", "REPORT_GENERATED": "ok", "READY_FOR_APPROVAL": "info", "DOCUMENTS_UPLOADED": "info",
             "CREATED": "info", "EXTRACTING": "info", "EVALUATING": "info", "EXTRACTION_REVIEW_REQUIRED": "warn",
             "REJECTED": "warn", "FAILED": "bad"}


def workspace_header(rfq_number: str, title: str, status: str, icon: str, label: str, next_step_html: str) -> str:
    current, mode = STATUS_STEP.get(status, (0, ""))
    parts = []
    for i, name in enumerate(STEPS):
        if i < current:
            cls, mark = "done", "✓"
        elif i == current:
            cls, mark = ("error" if mode == "error" else "current"), ("!" if mode == "error" else str(i + 1))
        else:
            cls, mark = "", str(i + 1)
        parts.append(f'<div class="step {cls}"><div class="dot">{mark}</div><div class="lbl">{name}</div></div>')
        if i < len(STEPS) - 1:
            parts.append(f'<div class="bar {"done" if i < current else ""}"></div>')
    sub = f'<span class="sub">{_e(title)}</span>' if title else ""
    return one_line(f"""<div class="ws-head"><div class="ws-title"><span class="rfq">{_e(rfq_number)}</span>{sub}
        <span class="pill {PILL_KIND.get(status, 'info')}">{icon} {_e(label)}</span></div>
        <div class="stepper">{''.join(parts)}</div>
        <div class="next">{next_step_html}</div></div>""")


def _meta(e) -> str:
    bits = [f"{e.risk_level.capitalize()} risk"]
    if e.mandatory_failures:
        bits.append(f"{e.mandatory_failures} requirement{'s' if e.mandatory_failures != 1 else ''} missed")
    if e.unknowns:
        bits.append(f"{e.unknowns} question{'s' if e.unknowns != 1 else ''} open")
    if len(bits) == 1:
        bits.append("nothing open")
    return ", ".join(bits)


def supplier_cards(evals, recommended: str | None, unit: str, currency: str = "") -> str:
    sym = {"INR": "₹", "USD": "$", "EUR": "€"}.get((currency or "").upper(), (currency or "") + " ")
    kind = {"COMPLIANT": "ok", "NEEDS_CLARIFICATION": "warn", "NOT_COMPLIANT": "bad"}
    label = {"COMPLIANT": "Qualifies", "NEEDS_CLARIFICATION": "Needs a reply", "NOT_COMPLIANT": "Doesn't qualify"}
    out = []
    for e in evals:
        best = e.supplier_name == recommended
        price = (f'{sym}{e.normalized_unit_price:,.2f}<small> / {_e(unit)} excl. tax</small>'
                 if e.normalized_unit_price is not None else '<small>No comparable price yet</small>')
        total = f"{sym}{e.total_cost:,.0f} for the full order" if e.total_cost is not None else "Order total unknown"
        out.append(
            f'<div class="card {kind[e.overall_status]} {"best" if best else ""}">'
            f'<div class="top"><span class="stamp {kind[e.overall_status]}">{label[e.overall_status]}</span>'
            f'{"<span class=best-tag>Recommended</span>" if best else ""}</div>'
            f'<div class="name">{_e(e.supplier_name)}</div><div class="price">{price}</div>'
            f'<div class="total">{total}</div><div class="meta">{_meta(e)}</div></div>')
    return f'<div class="cards">{"".join(out)}</div>'


def approval_card(supplier: str, reviewer: str, when: str) -> str:
    return one_line(f"""<div class="approved-card">
        <svg viewBox="0 0 52 52"><circle class="ring" cx="26" cy="26" r="24"/><path class="tick" d="M15 27 l7 7 l15 -15"/></svg>
        <div><div class="t1">Decision recorded</div>
        <div class="t2">{_e(reviewer)} approved <b>{_e(supplier)}</b> on {_e(when)}.</div>
        <div class="t3">It's in the audit log, and the final PDF and Excel reports are ready below.</div></div></div>""")


def insight(html_text: str) -> str:
    return f'<div class="insight">{html_text}</div>'
