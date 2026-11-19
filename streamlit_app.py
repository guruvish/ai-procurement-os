"""Procurement RFQ Evaluator - web interface for buyers (no coding needed).
Start with:  python run.py   (or: streamlit run streamlit_app.py)"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402

st.set_page_config(page_title="RFQ Evaluator", page_icon="📑", layout="wide")

try:
    from app import config, db  # noqa: E402
    from app import ui_theme as T  # noqa: E402
    from app.agents import workflow  # noqa: E402
    from app.schemas import WorkflowStatus  # noqa: E402
    from app.services.clarifications import draft_clarification  # noqa: E402
    from app.services.document_parser import DocumentError, parse_document  # noqa: E402
    from app.services import report_service as R  # noqa: E402
    from app.integrations import google_sheets  # noqa: E402
    from app.services import analytics as A  # noqa: E402
except RuntimeError as e:  # e.g. missing GEMINI_API_KEY
    st.error(f"Setup problem: {e}")
    st.info("Add your Gemini or Claude API key to the `.env` file in the project folder, then restart the app.")
    st.stop()

st.markdown(T.CSS, unsafe_allow_html=True)

S = WorkflowStatus
STATUS_INFO = {
    "CREATED": ("🆕", "Created", "Add the RFQ and the quotes you received."),
    "DOCUMENTS_UPLOADED": ("📥", "Documents uploaded", "Everything is uploaded. Start reading the documents from the <b>📁 Documents</b> tab."),
    "EXTRACTING": ("⏳", "Processing", "Reading the documents now. Allow 10 to 15 seconds per file."),
    "EXTRACTION_REVIEW_REQUIRED": ("🔍", "Needs your review",
                                   "A few details are missing from the RFQ. Fill them in on the <b>🔍 Review</b> tab, then run it again."),
    "EVALUATING": ("⏳", "Evaluating", "Comparing the suppliers."),
    "READY_FOR_APPROVAL": ("📝", "Ready for your decision",
                           "Have a look at what was read in <b>🔍 Review</b> and how suppliers stack up in <b>⚖️ Compare</b>. When you're happy, decide in <b>✅ Decision</b>."),
    "APPROVED": ("✅", "Approved", "Approved. The final PDF and Excel reports are on the <b>✅ Decision</b> tab."),
    "REJECTED": ("↩️", "Rejected", "Correct the values on the <b>🔍 Review</b> tab and re-evaluate, or upload revised quotes."),
    "REPORT_GENERATED": ("📄", "Approved, reports ready", "All done. You can download the reports again from the <b>✅ Decision</b> tab."),
    "FAILED": ("❌", "Processing failed", "Some files couldn't be read. The <b>📁 Documents</b> tab says which ones and why."),
}
CHECK_ICON = {"PASS": "✅", "FAIL": "❌", "UNKNOWN": "❔", "REVIEW_REQUIRED": "🔍", "NOT_APPLICABLE": "➖"}
VERDICT_ICON = {"COMPLIANT": "✅ Compliant", "NEEDS_CLARIFICATION": "⚠️ Needs clarification",
                "NOT_COMPLIANT": "❌ Not compliant"}
SEVERITY_ICON = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}
DOC_ICON = {"pending": "⏸ waiting", "extracted": "✅ extracted", "validated": "✅ checked by human",
            "review_required": "🔍 please verify", "failed": "❌ failed"}
PAGES = ["🏠 Dashboard", "➕ New evaluation", "📂 Open evaluation", "📊 Analytics", "💡 How it works"]
VERDICT_COLORS = alt.Scale(domain=["✅ Compliant", "⚠️ Needs clarification", "❌ Not compliant"],
                           range=["#1F7A4D", "#B26A00", "#B42318"])
FILE_TYPES = ["pdf", "xlsx", "docx", "csv"]


@st.cache_resource
def _init_db():
    db.init_db()
    return True


_init_db()


# ---------- helpers ----------
def go(page: str, rid: str | None = None):
    st.session_state["nav"] = page
    if rid:
        st.session_state["rid"] = rid
    st.rerun()


def flash(kind: str, msg: str):
    st.session_state.setdefault("flash", []).append((kind, msg))


def show_flash():
    for kind, msg in st.session_state.pop("flash", []):
        if kind == "approved":
            supplier, reviewer, when = msg.split("|", 2)
            html(T.approval_card(supplier, reviewer, when))
            st.toast("Decision recorded", icon="✅")
        else:
            getattr(st, kind)(msg)


def actor() -> str:
    return st.session_state.get("user_name", "").strip()


def need_actor() -> bool:
    if not actor():
        st.error("Add your name in the sidebar first. Every change is logged under it.")
        return False
    return True


def money(v) -> str:
    return "-" if v is None else f"{v:,.2f}"


def html(s: str):
    st.markdown(s, unsafe_allow_html=True)


def save_uploads(rid: str, files, role: str) -> None:
    """Uploads files and reports ONE short summary instead of a message per file."""
    ok, rejected, dups, warns = [], [], [], []
    for f in files or []:
        data = f.getvalue()
        try:
            parsed = parse_document(f.name, data, config.MAX_FILE_MB)
        except DocumentError as e:
            rejected.append(str(e))
            continue
        _, dup = db.save_document(rid, f.name, data, parsed.sha256, parsed.file_type, role, actor() or "user")
        (dups if dup else ok).append(f.name)
        warns += [f"{f.name}: {w}" for w in parsed.warnings]
    if ok:
        flash("success", f"Uploaded {len(ok)} file(s): {', '.join(ok)}")
    if rejected:
        flash("error", "Not uploaded:\n\n" + "\n\n".join(f"- {r}" for r in rejected))
    if dups:
        flash("warning", f"Already uploaded, so skipped: {', '.join(dups)}")
    for w in warns:
        flash("warning", w)


def evidence_caption(ev_map: dict, field: str) -> str:
    ev = ev_map.get(field)
    if not ev:
        return "📄 no source text found for this value"
    page = f"p.{ev.page} " if ev.page else ""
    quote = f'"{ev.quote}"' if ev.quote else ""
    return f"📄 {page}{quote} · AI confidence {ev.confidence:.0%}"


FAILED = object()  # sentinel: distinguishes "action failed" from functions that return None


def run_with_errors(fn, *args, **kwargs):
    """Runs a user action; shows a friendly error instead of crashing. Returns FAILED on error."""
    try:
        return fn(*args, **kwargs)
    except (db.WorkflowStateError, ValueError) as e:
        st.error(str(e))
    except Exception as e:  # unexpected - keep the app alive, point to the log
        st.error(f"That didn't work ({type(e).__name__}). The full error is in data/logs/app.log.")
    return FAILED


# ---------- sidebar ----------
if "nav" in st.session_state:
    st.session_state["page"] = st.session_state.pop("nav")
if st.session_state.get("page") not in PAGES:
    st.session_state.pop("page", None)
if not st.session_state.get("user_name") and st.query_params.get("user"):
    st.session_state["user_name"] = st.query_params.get("user")
with st.sidebar:
    html(T.sidebar_brand())
    page = st.radio("Menu", PAGES, key="page", label_visibility="collapsed")
    st.text_input("Your name", key="user_name", placeholder="e.g. Priya Sharma")
    st.caption("Your name goes on every change and decision in the audit log.")
if actor() and st.query_params.get("user") != actor():
    st.query_params["user"] = actor()


# ---------- navigation: back button + always start a new page at the top ----------
def _scroll_to_top():
    """Streamlit keeps the scroll position between pages; reset it when the view changes."""
    nonce = st.session_state.get("_views", 0)
    components.html(f"""<script>/* view {nonce} */
      const d = window.parent.document;
      d.querySelectorAll('[data-testid="stMain"], section.main, [data-testid="stAppViewContainer"]')
       .forEach(el => el.scrollTo({{top: 0, behavior: "instant"}}));
      window.parent.scrollTo(0, 0);
    </script>""", height=0)


_view = (page, st.session_state.get("rid") if page == "📂 Open evaluation" else None)
_last = st.session_state.get("_last_view")
if _last != _view:
    if _last and not st.session_state.pop("_going_back", False):
        st.session_state.setdefault("history", []).append(_last)
        st.session_state["history"] = st.session_state["history"][-20:]
    st.session_state["_last_view"] = _view
    st.session_state["_views"] = st.session_state.get("_views", 0) + 1
    try:
        _scroll_to_top()
    except Exception:
        pass  # scrolling is a convenience; never break the page for it

if st.session_state.get("history"):
    if st.button("← Back", key="nav_back", help="Go back to the page you were on"):
        prev_page, prev_rid = st.session_state["history"].pop()
        st.session_state["_going_back"] = True
        go(prev_page, prev_rid)


# ---------- pages ----------
def page_dashboard():
    html(T.hero())
    show_flash()
    reqs = db.list_requests()
    by = lambda *states: sum(r["status"] in states for r in reqs)  # noqa: E731
    c = st.columns(4)
    c[0].metric("Evaluations", len(reqs))
    c[1].metric("To decide", by("READY_FOR_APPROVAL"), help="Evaluations waiting on your decision")
    c[2].metric("Need attention", by("EXTRACTION_REVIEW_REQUIRED", "FAILED", "REJECTED", "DOCUMENTS_UPLOADED"),
                help="Not read yet, failed, rejected, or waiting on RFQ details")
    c[3].metric("Approved", by("APPROVED", "REPORT_GENERATED"))
    if not reqs:
        html(T.features())
        if st.button("Start your first evaluation", type="primary"):
            go("➕ New evaluation")
        return

    st.subheader("Recent evaluations")
    rows = []
    for r in reqs:
        icon, label, _ = STATUS_INFO[r["status"]]
        rec = json.loads(r["recommendation_json"]).get("recommended_supplier") if r["recommendation_json"] else None
        rows.append({"RFQ": r["rfq_number"], "Title": r["title"], "Status": f"{icon} {label}",
                     "Recommended": rec or "-", "Last update": r["updated_at"].replace("T", " ")})
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    labels = {r["id"]: f"{r['rfq_number']} - {r['title'] or ''}" for r in reqs}
    col1, col2 = st.columns([4, 1], vertical_alignment="bottom")
    pick = col1.selectbox("Open an evaluation", list(labels), format_func=labels.get)
    if col2.button("Open ➜", type="primary"):
        go("📂 Open evaluation", pick)

    runs = [r for r in db.list_runs() if r["metrics_json"]]
    ms = [m for m in (json.loads(r["metrics_json"]) for r in runs) if "ai_calls" in m]
    if ms:
        st.subheader("How processing has gone")
        c = st.columns(4)
        c[0].metric("Processing runs", len(ms))
        c[1].metric("Avg. time", f"{sum(m['total_seconds'] for m in ms) / len(ms):.0f} s", help="Average processing time per run")
        c[2].metric("AI calls", sum(m["ai_calls"] for m in ms), help="Documents sent to an AI model to read")
        c[3].metric("Not read", sum(m.get("documents_failed", 0) for m in ms), help="Documents that could not be read")
    html(T.features())


def page_new():
    st.title("New evaluation")
    show_flash()
    st.write("Add the RFQ you sent out and the quotes that came back. PDF, Excel, Word and CSV all work.")
    with st.form("new_eval"):
        c1, c2 = st.columns(2)
        rfq_number = c1.text_input("RFQ number *", placeholder="RFQ-2026-001")
        title = c2.text_input("Title", placeholder="Paracetamol API - Q4")
        department = c1.text_input("Department", value="Purchase")
        buyer = c2.text_input("Buyer company", placeholder="Sunrise Pharma Pvt Ltd")
        rfq_file = st.file_uploader("RFQ document *", type=FILE_TYPES)
        quote_files = st.file_uploader("Supplier quotes * (you can pick several at once)", type=FILE_TYPES,
                                       accept_multiple_files=True)
        submitted = st.form_submit_button("Create evaluation", type="primary")
    if not submitted:
        return
    if not need_actor():
        return
    missing = [name for name, ok in (("RFQ number", rfq_number.strip()), ("RFQ document", rfq_file),
                                     ("Supplier quotations", quote_files)) if not ok]
    if missing:
        st.error("Still needed: **" + "**, **".join(missing) + "**")
        return
    try:
        parse_document(rfq_file.name, rfq_file.getvalue(), config.MAX_FILE_MB)
    except DocumentError as e:
        st.error(f"We couldn't use that RFQ file: {e}")
        return
    rid = run_with_errors(db.create_request, rfq_number, title, department, buyer, actor())
    if rid is FAILED:
        return
    save_uploads(rid, [rfq_file], "RFQ")
    save_uploads(rid, quote_files, "QUOTATION")
    flash("info", "Evaluation created. Start reading the documents below when you're ready.")
    go("📂 Open evaluation", rid)


def page_open():
    reqs = db.list_requests()
    if not reqs:
        st.info("Nothing here yet. Start a new evaluation from the sidebar.")
        return
    ids = [r["id"] for r in reqs]
    labels = {r["id"]: f"{r['rfq_number']} - {r['title'] or ''}" for r in reqs}
    current = st.session_state.get("rid")
    rid = st.selectbox("Evaluation", ids, index=ids.index(current) if current in ids else 0,
                       format_func=labels.get, label_visibility="collapsed")
    st.session_state["rid"] = rid
    req = db.get_request(rid)
    status = S(req["status"])
    icon, label, next_step = STATUS_INFO[status.value]
    j = workflow.job(rid)
    if status in workflow.PROCESSING and not (j and not j["done"]) and not workflow.is_running(rid):
        icon, label = "⏸", "Interrupted"
        next_step = "The last run stopped partway. Pick it up with <b>Resume processing</b> on the <b>📁 Documents</b> tab."
    html(T.workspace_header(req["rfq_number"], req["title"] or "", status.value, icon, label, next_step))
    show_flash()

    tabs = st.tabs(["📁 Documents", "🔍 Review", "⚖️ Compare", "⚠️ Risks", "📊 Insights", "✅ Decision", "🧾 Audit"])
    with tabs[0]:
        tab_documents(rid, status)
    with tabs[1]:
        tab_review(rid, status)
    with tabs[2]:
        tab_comparison(rid)
    with tabs[3]:
        tab_risks(rid, req)
    with tabs[4]:
        tab_insights(rid)
    with tabs[5]:
        tab_decision(rid, status)
    with tabs[6]:
        tab_audit(rid)


def tab_documents(rid: str, status: WorkflowStatus):
    docs = db.list_documents(rid)
    rows = [{"Type": d["doc_role"], "File": d["filename"], "Status": DOC_ICON.get(d["extraction_status"],
             d["extraction_status"]), "Problem": d["error"] or ""} for d in docs]
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    locked = status in (S.APPROVED, S.REPORT_GENERATED)
    if not locked:
        with st.expander("➕ Add more quotations or replace the RFQ"):
            new_q = st.file_uploader("Additional quotations", type=FILE_TYPES, accept_multiple_files=True,
                                     key=f"addq_{rid}")
            new_r = st.file_uploader("Replacement RFQ", type=FILE_TYPES, key=f"addr_{rid}")
            if st.button("Upload", key=f"up_{rid}") and need_actor():
                if new_r:
                    save_uploads(rid, [new_r], "RFQ")
                save_uploads(rid, new_q, "QUOTATION")
                st.rerun()

    st.subheader("Processing")
    _report_finished_job(rid)
    j = workflow.job(rid)
    running = bool(j and not j["done"]) or workflow.is_running(rid)
    if running:
        _live_progress(rid)
    else:
        stale = status in workflow.PROCESSING
        can_run = status in workflow.STARTABLE or stale
        read_ids = {x["document_id"] for x in db.list_quotations(rid)}
        unread = [d for d in docs if d["doc_role"] == "QUOTATION" and d["id"] not in read_ids]
        if stale:
            st.warning("The last run was interrupted. **Resume** picks up where it stopped, "
                       "and documents already read aren't read again.")
            label = "▶ Resume processing"
        elif read_ids and unread:
            label = f"🔁 Read the {len(unread)} remaining document(s)"
        else:
            label = "▶ Read documents and compare"
        force = st.checkbox("Read every document again from scratch (drops earlier results and your corrections)",
                            key=f"force_{rid}", disabled=not can_run)
        if st.button(label, type="primary", disabled=not can_run, key=f"run_{rid}") and need_actor():
            if run_with_errors(workflow.start_processing, rid, force, actor()) is not FAILED:
                st.rerun()
        if not can_run and not locked:
            st.caption("Add the RFQ and at least one quote to get started.")
        elif locked:
            st.caption("This evaluation is approved, so it can't be changed.")

    runs = db.list_runs(rid)
    if runs and runs[0]["metrics_json"]:
        m = json.loads(runs[0]["metrics_json"])
        if "ai_calls" in m:
            st.caption("Last run")
            c = st.columns(5)
            c[0].metric("Time", f"{m['total_seconds']:.0f} s", help="Total processing time of the last run")
            c[1].metric("AI calls", m["ai_calls"], help="Documents sent to an AI model")
            c[2].metric("Waits", m.get("rate_limit_waits", 0), help="Times the AI service asked us to slow down")
            c[3].metric("Reused", m.get("stages_reused", 0), help="Documents read in an earlier run, so no AI cost this time")
            c[4].metric("Not read", m.get("documents_failed", 0), help="Documents that could not be read")
            if m.get("models_used"):
                st.caption("Answered by: " + ", ".join(m["models_used"]))

    with st.expander("🗑 Delete this evaluation"):
        st.write("This removes the evaluation, its files and everything read from them. There's no undo.")
        sure = st.checkbox("Yes, delete it", key=f"del_ok_{rid}")
        if st.button("Delete", disabled=not sure, key=f"del_{rid}") and need_actor():
            db.delete_request(rid, actor())
            st.session_state.pop("rid", None)
            flash("success", "Evaluation deleted.")
            go("🏠 Dashboard")


def _live_progress(rid: str):
    """Re-draws itself every 2 s while the background job runs; the user can keep working meanwhile."""
    @st.fragment(run_every=2)
    def _panel():
        j = workflow.job(rid)
        if not j or j["done"]:
            st.rerun()  # job finished: refresh the whole page (status, tables, tabs)
            return
        secs = int(time.time() - j["started"])
        with st.container(border=True):
            st.markdown(f"**Reading documents ({secs}s so far).** Feel free to look around the other tabs meanwhile.")
            for m in j["messages"][-12:]:
                st.write(m)
    _panel()


def _report_finished_job(rid: str):
    j = workflow.pop_finished_job(rid)
    if not j:
        return
    if j["error"]:
        st.error(f"Processing stopped: {j['error']}")
        return
    res = j["result"]
    outcome = {"ok": ("success", "Suppliers evaluated."),
               "review": ("warning", "The RFQ is missing a few details. Fill them in on the **🔍 Review** tab."),
               "failed": ("error", f"Processing failed: {res['error']}")}
    kind, msg = outcome.get(res["outcome"], ("info", "Finished."))
    getattr(st, kind)(f"{msg} ({res['metrics']['total_seconds']:.0f}s)")
    if res["doc_errors"]:
        st.warning(f"{len(res['doc_errors'])} document(s) not read - see the table above. "
                   "Run it again to retry just those.")
    with st.expander("Processing log"):
        for m in j["messages"]:
            st.write(m)


def _rows_to_specs(rows: list, old_ev: dict, with_req_fields: bool) -> list:
    out = []
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        val = row.get("value")
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = val or None
        ev = old_ev.get(name)
        item = {"name": name, "value": val, "unit": row.get("unit") or None,
                "evidence": ev.model_dump() if ev else None}
        if with_req_fields:
            item.update(operator=row.get("operator") or ">=", mandatory=bool(row.get("mandatory")))
        out.append(item)
    return out


def tab_review(rid: str, status: WorkflowStatus):
    rfq = db.get_rfq(rid)
    if rfq is None:
        st.info("Nothing has been read yet. Start from the **📁 Documents** tab.")
        return
    locked = status in (S.APPROVED, S.REPORT_GENERATED)
    st.caption("Under each value you'll see the line it was taken from. If something looks off, "
               "correct it, save, and press **Re-evaluate**.")
    if not locked and status in workflow.REEVALUABLE:
        if st.button("🔁 Re-evaluate with my corrections", type="primary", key=f"reeval_{rid}") and need_actor():
            if run_with_errors(workflow.reevaluate, rid, actor()) is not FAILED:
                flash("success", "Re-evaluated with your corrections.")
                st.rerun()

    st.subheader("What you asked for")
    with st.form(f"rfq_form_{rid}"):
        c1, c2, c3 = st.columns(3)
        product = c1.text_input("Product", rfq.product_name or "")
        c1.caption(evidence_caption(rfq.evidence, "product_name"))
        qty = c2.number_input("Required quantity", value=rfq.required_quantity, min_value=0.0)
        c2.caption(evidence_caption(rfq.evidence, "required_quantity"))
        unit = c3.text_input("Unit", rfq.unit or "")
        delivery = c1.number_input("Max delivery (days)", value=rfq.max_delivery_days, min_value=0, step=1)
        c1.caption(evidence_caption(rfq.evidence, "max_delivery_days"))
        currency = c2.text_input("Currency", rfq.currency or "")
        payment = c3.text_input("Payment terms", rfq.payment_terms or "")
        certs = st.text_input("Required certificates (comma separated)", ", ".join(rfq.required_certificates))
        st.write("Technical requirements")
        tr = pd.DataFrame([{"name": r.name, "operator": r.operator, "value": "" if r.value is None else str(r.value),
                            "unit": r.unit or "", "mandatory": r.mandatory,
                            "source": (r.evidence.quote if r.evidence and r.evidence.quote else "")}
                           for r in rfq.technical_requirements],
                          columns=["name", "operator", "value", "unit", "mandatory", "source"])
        edited_tr = st.data_editor(
            tr, hide_index=True, num_rows="dynamic", disabled=["source"], key=f"tr_{rid}",
            column_config={"operator": st.column_config.SelectboxColumn(options=[">=", "<=", ">", "<", "==", "present"]),
                           "mandatory": st.column_config.CheckboxColumn()})
        if st.form_submit_button("Save RFQ corrections", disabled=locked) and need_actor():
            old_ev = {r.name: r.evidence for r in rfq.technical_requirements}
            changes = {"product_name": product or None, "required_quantity": qty, "unit": unit or None,
                       "max_delivery_days": int(delivery) if delivery is not None else None,
                       "currency": currency or None, "payment_terms": payment or None,
                       "required_certificates": [c.strip() for c in certs.split(",") if c.strip()],
                       "technical_requirements": _rows_to_specs(edited_tr.to_dict("records"), old_ev, True)}
            if run_with_errors(db.human_edit_rfq, rid, changes, actor()) is not FAILED:
                flash("success", "RFQ saved. Press **Re-evaluate** to apply it.")
                st.rerun()

    st.subheader("What suppliers offered")
    for item in db.list_quotations(rid):
        q, did = item["quotation"], item["document_id"]
        badge = " · ✏️ corrected by human" if item["edited_by_human"] else ""
        warn = " · 🔍 please verify" if q.extraction_status == "review_required" else ""
        with st.expander(f"{q.supplier_name}  ({q.source_document}){badge}{warn}"):
            with st.form(f"q_{did}"):
                c1, c2, c3 = st.columns(3)
                name = c1.text_input("Supplier", q.supplier_name)
                c1.caption(evidence_caption(q.evidence, "supplier_name"))
                price = c2.number_input("Unit price", value=q.unit_price, min_value=0.0, format="%.4f")
                c2.caption(evidence_caption(q.evidence, "unit_price"))
                price_per = c3.text_input("Price per (unit)", q.price_per or "")
                currency = c1.text_input("Currency", q.currency or "")
                c1.caption(evidence_caption(q.evidence, "currency"))
                tax_opts = ["exclusive", "inclusive", "unknown"]
                tax = c2.selectbox("Tax (GST)", tax_opts, index=tax_opts.index(q.tax_status))
                c2.caption(evidence_caption(q.evidence, "tax_status"))
                tax_rate = c3.number_input("Tax rate %", value=q.tax_rate_percent, min_value=0.0)
                delivery = c1.number_input("Delivery (days)", value=q.delivery_days, min_value=0, step=1)
                c1.caption(evidence_caption(q.evidence, "delivery_days"))
                valid = c2.date_input("Valid until", value=q.valid_until)
                c2.caption(evidence_caption(q.evidence, "valid_until"))
                freight = c3.number_input("Separate freight (total)", value=q.freight_cost, min_value=0.0)
                payment = st.text_input("Payment terms", q.payment_terms or "")
                st.caption(evidence_caption(q.evidence, "payment_terms"))
                certs = st.text_input("Certificates offered (comma separated)", ", ".join(q.certificates))
                st.write("Offered specifications")
                sp = pd.DataFrame([{"name": s.name, "value": "" if s.value is None else str(s.value),
                                    "unit": s.unit or "",
                                    "source": (s.evidence.quote if s.evidence and s.evidence.quote else "")}
                                   for s in q.specifications], columns=["name", "value", "unit", "source"])
                edited_sp = st.data_editor(sp, hide_index=True, num_rows="dynamic", disabled=["source"],
                                           key=f"sp_{did}")
                if q.conflicts:
                    st.warning("The document contradicts itself: " + "; ".join(q.conflicts))
                for w in q.verification_warnings:
                    st.error(f"{w}. Fix the value if it's wrong, then **Save corrections** to confirm it.")
                if st.form_submit_button("Save corrections", disabled=locked) and need_actor():
                    old_ev = {s.name: s.evidence for s in q.specifications}
                    changes = {"supplier_name": name, "unit_price": price, "price_per": price_per or None,
                               "currency": currency or None, "tax_status": tax, "tax_rate_percent": tax_rate,
                               "delivery_days": int(delivery) if delivery is not None else None,
                               "valid_until": valid, "freight_cost": freight, "payment_terms": payment or None,
                               "certificates": [c.strip() for c in certs.split(",") if c.strip()],
                               "specifications": _rows_to_specs(edited_sp.to_dict("records"), old_ev, False)}
                    if q.verification_warnings:
                        changes["verification_warnings"] = []   # explicit human confirmation, audited
                    if run_with_errors(db.human_edit_quotation, rid, did, changes, actor()) is not FAILED:
                        flash("success", f"Saved your corrections for {name}. Press **Re-evaluate** to update the results.")
                        st.rerun()


def _incomplete_banner(rec: dict):
    missing = rec.get("unprocessed_documents") or []
    if missing:
        st.error(f"**This comparison is missing {len(missing)} quote(s)** that couldn't be read: "
                 f"{', '.join(missing)}. Run it again from the **📁 Documents** tab to include them.")


def tab_comparison(rid: str):
    evals = db.get_evaluations(rid)
    if not evals:
        st.info("No results yet. Start from the **📁 Documents** tab.")
        return
    rec = db.get_recommendation(rid) or {}
    _incomplete_banner(rec)
    (st.success if rec.get("recommended_supplier") else st.warning)(
        f"**System recommendation:** {rec.get('explanation', '-')}")
    rfq = db.get_rfq(rid)
    unit, currency = (rfq.unit or "", rfq.currency or "") if rfq else ("", "")
    html(T.supplier_cards(evals, rec.get("recommended_supplier"), unit, currency))

    comparable = [e for e in evals if e.total_cost is not None]
    if comparable:
        st.subheader("What each order would cost")
        df = pd.DataFrame({"Supplier": [e.supplier_name for e in comparable],
                           "Total cost": [e.total_cost for e in comparable],
                           "Verdict": [VERDICT_ICON[e.overall_status] for e in comparable],
                           "Recommended": [e.supplier_name == rec.get("recommended_supplier") for e in comparable]})
        color = alt.Color("Verdict:N", scale=alt.Scale(
            domain=list(VERDICT_ICON.values()), range=["#1F7A4D", "#B26A00", "#B42318"]), legend=alt.Legend(orient="bottom"))
        chart = (alt.Chart(df).mark_bar(cornerRadiusEnd=8, height=28)
                 .encode(x=alt.X("Total cost:Q", title=f"Total comparable cost ({currency})"),
                         y=alt.Y("Supplier:N", sort="x", title=None), color=color,
                         tooltip=["Supplier", "Verdict", alt.Tooltip("Total cost:Q", format=",.0f")])
                 .properties(height=70 * len(df) + 40))
        st.altair_chart(chart)

    st.subheader("Compliance matrix")
    st.caption("✅ meets it, ❌ misses it, ❔ not stated, 🔍 worth a second look. Starred rows are must-haves.")
    reqs, seen = [], set()
    for e in evals:
        for c in e.checks:
            if c.requirement not in seen:
                seen.add(c.requirement)
                reqs.append((c.requirement, c.required, c.mandatory))
    matrix = []
    for name, required, mandatory in reqs:
        row = {"Requirement": f"{name}{' *' if mandatory else ''}", "Required": required}
        for e in evals:
            c = next((x for x in e.checks if x.requirement == name), None)
            row[e.supplier_name] = f"{CHECK_ICON[c.status.value]} {c.offered}" if c else "-"
        matrix.append(row)
    st.dataframe(pd.DataFrame(matrix), hide_index=True)

    with st.expander("How each price was made comparable"):
        for e in evals:
            st.write(f"**{e.supplier_name}:** " + ("; ".join(e.price_notes) if e.price_notes else "used as quoted"))
    with st.expander("Reason for every check"):
        for e in evals:
            st.write(f"**{e.supplier_name}**")
            st.dataframe(pd.DataFrame([{"Check": c.requirement, "Result": f"{CHECK_ICON[c.status.value]} {c.status.value}",
                                        "Required": c.required, "Offered": c.offered, "Reason": c.reason}
                                       for c in e.checks]), hide_index=True)


def tab_risks(rid: str, req: dict):
    evals = db.get_evaluations(rid)
    rfq = db.get_rfq(rid)
    if not evals or rfq is None:
        st.info("No evaluation yet.")
        return
    quotes = {x["quotation"].supplier_name: x["quotation"] for x in db.list_quotations(rid)}
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for e in evals:
        with st.expander(f"{VERDICT_ICON[e.overall_status]} · {e.supplier_name} · {len(e.findings)} finding(s)",
                         expanded=e.overall_status != "COMPLIANT"):
            if not e.findings:
                st.write("Nothing to flag.")
            for f in sorted(e.findings, key=lambda f: order[f.severity]):
                st.write(f"{SEVERITY_ICON[f.severity]} **{f.severity.capitalize()}** ({f.category}): {f.message}")
            q = quotes.get(e.supplier_name)
            draft = draft_clarification(rfq, q, e, buyer=req.get("buyer") or "") if q else None
            if draft:
                st.text_area("✉️ Draft clarification email (edit and copy into your email)", draft, height=260,
                             key=f"clar_{rid}_{e.supplier_name}")


@st.cache_data(max_entries=20, show_spinner=False)
def _report_files(rid: str, version: str):
    """Cached per evaluation state (version changes on every update/audit event)."""
    return R.pdf_report(rid), R.excel_report(rid)


def _mark_final(rid: str):
    try:
        if db.get_status(rid) == S.APPROVED:
            R.save_final_reports(rid, actor() or "user")
    except Exception:
        pass  # downloading must never fail because of bookkeeping


def reports_section(rid: str, status: WorkflowStatus):
    st.subheader("Reports")
    if not db.get_evaluations(rid):
        st.caption("Reports are ready once the suppliers have been compared.")
        return
    final = status in (S.APPROVED, S.REPORT_GENERATED)
    st.caption("These include the approval record." if final else
               "Until someone approves, reports are stamped as a draft.")
    req = db.get_request(rid)
    version = f"{req['updated_at']}|{len(db.list_audit(rid))}"
    try:
        pdf, xlsx = _report_files(rid, version)
    except Exception as e:
        st.error(f"Could not build the report ({type(e).__name__}). Details are in data/logs/app.log.")
        return
    stem = R.file_stem(rid) + ("" if final else "_DRAFT")
    c1, c2, c3 = st.columns(3)
    c1.download_button("⬇️ PDF report", pdf, f"{stem}.pdf", "application/pdf", type="primary",
                       on_click=_mark_final, args=(rid,), key=f"dl_pdf_{rid}")
    c2.download_button("⬇️ Excel workbook", xlsx, f"{stem}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       on_click=_mark_final, args=(rid,), key=f"dl_xlsx_{rid}")
    if google_sheets.is_configured():
        if c3.button("📤 Export to Google Sheets", key=f"gs_{rid}") and need_actor():
            with st.spinner("Sending to Google Sheets"):
                url = run_with_errors(google_sheets.export, rid, actor())
            if url is not FAILED:
                st.success(f"Sent to Google Sheets. [Open the spreadsheet]({url})")
    else:
        c3.caption("Google Sheets isn't connected. It's optional; `docs/google_sheets_setup.md` explains how.")


def tab_decision(rid: str, status: WorkflowStatus):
    approvals = db.list_approvals(rid)
    if approvals:
        st.subheader("Decision history")
        st.dataframe(pd.DataFrame([{"When": a["reviewed_at"].replace("T", " "), "Reviewer": a["reviewer"],
                                    "Decision": a["decision"], "Supplier": a["selected_supplier"] or "-",
                                    "Comments": a["comments"]} for a in approvals]), hide_index=True)
    if status != S.READY_FOR_APPROVAL:
        if status not in (S.APPROVED, S.REPORT_GENERATED):
            st.info("You can decide once the status reads **Ready for your decision**.")
        reports_section(rid, status)
        return
    evals = db.get_evaluations(rid)
    rec = db.get_recommendation(rid) or {}
    _incomplete_banner(rec)
    st.subheader("Your decision")
    st.caption("The recommendation is only a suggestion. Nothing is approved until you approve it.")
    names = [e.supplier_name for e in evals]
    verdicts = {e.supplier_name: e.overall_status for e in evals}
    default = names.index(rec["recommended_supplier"]) if rec.get("recommended_supplier") in names else 0
    missing = rec.get("unprocessed_documents") or []
    with st.form(f"decision_{rid}"):
        chosen = st.selectbox("Selected supplier", names, index=default,
                              format_func=lambda n: f"{n} - {VERDICT_ICON[verdicts[n]]}")
        reviewer = st.text_input("Reviewer", value=actor())
        comments = st.text_area("Notes (needed if you reject, pick a supplier that misses something, "
                                "or approve with quotes missing)")
        ack = (st.checkbox(f"I know {len(missing)} quote(s) weren't included") if missing else True)
        c1, c2 = st.columns(2)
        approve = c1.form_submit_button("✅ Approve", type="primary")
        reject = c2.form_submit_button("↩️ Reject")
    if approve:
        if missing and not (ack and comments.strip()):
            st.error("Some quotes are missing from this comparison. Tick the box and add a note to approve anyway, "
                     "or read the missing quotes first from the **📁 Documents** tab.")
        elif verdicts[chosen] != "COMPLIANT" and not comments.strip():
            st.error(f"{chosen} doesn't meet every requirement. Add a note on why you're choosing them.")
        elif run_with_errors(db.record_decision, rid, "APPROVED", reviewer, comments, chosen) is not FAILED:
            flash("approved", f"{chosen}|{reviewer.strip()}|{time.strftime('%d %b %Y, %H:%M')}")
            st.rerun()
    if reject:
        if run_with_errors(db.record_decision, rid, "REJECTED", reviewer, comments) is not FAILED:
            flash("warning", "Rejected. Correct what's wrong and re-evaluate when ready.")
            st.rerun()
    st.divider()
    reports_section(rid, status)


def _money(v, cur="") -> str:
    if v is None:
        return "-"
    sym = {"INR": "₹", "USD": "$", "EUR": "€"}.get((cur or "").upper(), "")
    return f"{sym}{v:,.0f}" if sym else f"{v:,.0f} {cur}".strip()


def tab_insights(rid: str):
    evals = db.get_evaluations(rid)
    if not evals:
        st.info("Insights show up once the suppliers have been compared.")
        return
    rfq = db.get_rfq(rid)
    rec = db.get_recommendation(rid) or {}
    quotes = {x["quotation"].supplier_name: x["quotation"] for x in db.list_quotations(rid)}
    cur, unit = (rfq.currency or "", rfq.unit or "") if rfq else ("", "")
    da = A.decision_analysis(evals, rec)
    _incomplete_banner(rec)

    c = st.columns(4)
    c[0].metric("Savings vs highest compliant", _money(da["savings_vs_highest"], cur),
                f"{da['savings_vs_highest_pct']}%" if da["savings_vs_highest_pct"] else None,
                help="Recommended supplier's total compared with the most expensive compliant quote")
    c[1].metric("Gap to runner-up", f"{da['gap_to_runner_up_pct']}%" if da["gap_to_runner_up_pct"] is not None else "-",
                _money(da["gap_to_runner_up"], cur) if da["gap_to_runner_up"] else None, delta_color="off",
                help="How much cheaper the recommendation is than the next compliant supplier")
    c[2].metric("Compliance premium", _money(da["compliance_premium"], cur) if da["compliance_premium"] else "none",
                f"{da['compliance_premium_pct']}% vs cheapest quote" if da["compliance_premium_pct"] else None,
                delta_color="off",
                help="Extra cost of the recommended supplier compared with the cheapest quote overall, "
                     "which does NOT meet all mandatory requirements")
    c[3].metric("Compliant suppliers", f"{da['n_compliant']} / {da['n_suppliers']}",
                help=f"{da['n_clarification']} need clarification, {da['n_not_compliant']} not compliant")
    html(T.insight(f"<b>Decision robustness.</b> {T._e(da['robustness'])}"))

    rows = A.scorecard(rfq, evals, quotes)
    df = pd.DataFrame(rows)
    df["Verdict"] = df["Verdict"].map(VERDICT_ICON)
    left, right = st.columns(2)
    with left:
        st.markdown("**Price against delivery time** (bigger bubbles have more open questions)")
        pts = df.dropna(subset=["Price / unit", "Delivery days"])
        if pts.empty:
            st.caption("There aren't enough prices and delivery times to plot yet.")
        else:
            base = alt.Chart(pts).encode(
                x=alt.X("Delivery days:Q", title="Delivery (days)", scale=alt.Scale(zero=False, padding=20)),
                y=alt.Y("Price / unit:Q", title=f"Price per {unit} excl. tax ({cur})", scale=alt.Scale(zero=False, padding=20)))
            layers = [base.mark_circle(opacity=.85, stroke="white", strokeWidth=2).encode(
                          size=alt.Size("Open items:Q", scale=alt.Scale(range=[250, 1400]), legend=None),
                          color=alt.Color("Verdict:N", scale=VERDICT_COLORS, legend=alt.Legend(orient="bottom", title=None)),
                          tooltip=["Supplier", "Verdict", "Price / unit", "Delivery days", "Open items", "Risk"]),
                      base.mark_text(dy=-20, fontSize=11, fontWeight=600, color="#334155").encode(text="Supplier:N")]
            if rfq and rfq.max_delivery_days:
                layers.append(alt.Chart(pd.DataFrame({"x": [rfq.max_delivery_days]})).mark_rule(
                    strokeDash=[6, 4], color="#B42318").encode(x="x:Q"))
            st.altair_chart(alt.layer(*layers).properties(height=320))
            st.caption("Bottom left is cheaper and faster. The red dashed line is the latest delivery you'll accept.")
    with right:
        st.markdown("**Issues found, by how serious they are**")
        rm = pd.DataFrame(A.risk_mix(evals))
        if rm.empty:
            st.caption("Nothing to flag.")
        else:
            st.altair_chart(alt.Chart(rm).mark_bar(cornerRadiusEnd=6, height=24).encode(
                x=alt.X("sum(Findings):Q", title="Findings"), y=alt.Y("Supplier:N", title=None),
                color=alt.Color("Severity:N", scale=alt.Scale(domain=["HIGH", "MEDIUM", "LOW"],
                                range=["#B42318", "#B26A00", "#CBD5E1"]), legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["Supplier", "Severity", "Findings"]).properties(height=320))

    st.markdown("**How each supplier did on your requirements**")
    cm = pd.DataFrame(A.check_mix(evals))
    if not cm.empty:
        st.altair_chart(alt.Chart(cm).mark_bar(cornerRadiusEnd=6, height=22).encode(
            x=alt.X("sum(Checks):Q", stack="normalize", title="Share of checks", axis=alt.Axis(format="%")),
            y=alt.Y("Supplier:N", title=None),
            color=alt.Color("Result:N", scale=alt.Scale(domain=["PASS", "FAIL", "UNKNOWN", "REVIEW_REQUIRED"],
                            range=["#1F7A4D", "#B42318", "#94A3B8", "#B26A00"]), legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["Supplier", "Result", "Checks"]).properties(height=60 * len(evals) + 40))

    st.markdown("**Scorecard** (the actual figures, no weighting or scores)")
    st.dataframe(df[["Supplier", "Verdict", "Price / unit", "Total cost", "Technical pass %", "Documents %",
                     "Delivery days", "Delivery headroom", "Payment days", "Open items", "High risks", "Risk"]],
                 hide_index=True,
                 column_config={
                     "Price / unit": st.column_config.NumberColumn(format="%.2f"),
                     "Total cost": st.column_config.NumberColumn(format="%.0f"),
                     "Technical pass %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                     "Documents %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
                     "Delivery headroom": st.column_config.NumberColumn(help="Days to spare before the delivery limit"),
                     "Payment days": st.column_config.NumberColumn(help="Credit days offered (0 = advance payment)")})


def page_analytics():
    st.title("Analytics")
    st.caption("Everything here comes from evaluations and decisions already on record.")
    P = A.portfolio(db)
    k = P["kpis"]
    if not P["rows"]:
        st.info("Nothing here yet. Start a new evaluation from the sidebar.")
        return
    c = st.columns(4)
    c[0].metric("Evaluations", k["evaluations"], help="All RFQ evaluations in the system")
    c[1].metric("Decided", k["decided"], help="Evaluations with an approved supplier")
    c[2].metric("Recommendation accepted", f"{k['acceptance_pct']:.0f}%" if k["acceptance_pct"] is not None else "-",
                help="Share of decisions where the approver chose the system's recommendation")
    c[3].metric("Savings identified", _money(k["savings_total"], "INR"),
                help="Sum over decided RFQs: most expensive compliant quote minus the recommended one")
    c = st.columns(4)
    c[0].metric("Avg. cycle time", f"{k['avg_cycle_h']} h" if k["avg_cycle_h"] is not None else "-",
                help="From creating the evaluation to the approved decision")
    c[1].metric("Suppliers per RFQ", k["avg_suppliers"] or "-")
    c[2].metric("Human corrections", k["corrections"], help="Values people had to correct. Fewer means the reading was more accurate.")
    c[3].metric("Avg. AI processing", f"{k['avg_processing_s']:.0f} s" if k["avg_processing_s"] else "-",
                help=f"{k['ai_calls']} AI calls in total")

    left, right = st.columns(2)
    with left:
        st.markdown("**Where suppliers fall short most often**")
        ic = pd.DataFrame(P["issue_categories"])
        if ic.empty:
            st.caption("Nothing to show yet.")
        else:
            st.altair_chart(alt.Chart(ic).mark_bar(cornerRadiusEnd=6, height=22, color="#0E6E6B").encode(
                x=alt.X("Findings:Q"), y=alt.Y("Category:N", sort="-x", title=None),
                tooltip=["Category", "Findings"]).properties(height=40 * len(ic) + 40))
    with right:
        st.markdown("**Savings on each decided RFQ**")
        sv = pd.DataFrame([r for r in P["rows"] if r["Selected"] and r["Savings vs highest compliant"]])
        if sv.empty:
            st.caption("Savings show up once an RFQ with two or more qualifying suppliers is approved.")
        else:
            st.altair_chart(alt.Chart(sv).mark_bar(cornerRadiusEnd=6, height=22, color="#1F7A4D").encode(
                x=alt.X("Savings vs highest compliant:Q", title="Savings"), y=alt.Y("RFQ:N", title=None),
                tooltip=["RFQ", "Selected", "Savings vs highest compliant"]).properties(height=40 * len(sv) + 40))

    st.markdown("**Suppliers across all RFQs**")
    st.dataframe(pd.DataFrame(P["suppliers"])[["Supplier", "Quotes", "Compliant", "Compliance rate %", "Recommended",
                                               "Selected", "High risks"]], hide_index=True,
                 column_config={"Compliance rate %": st.column_config.ProgressColumn(min_value=0, max_value=100,
                                                                                     format="%.0f%%")})
    st.markdown("**All evaluations**")
    ev = pd.DataFrame(P["rows"])
    ev["Status"] = ev["Status"].map(lambda x: f"{STATUS_INFO[x][0]} {STATUS_INFO[x][1]}")
    st.dataframe(ev, hide_index=True,
                 column_config={"Followed recommendation": st.column_config.CheckboxColumn(),
                                "Savings vs highest compliant": st.column_config.NumberColumn(format="%.0f"),
                                "Compliance premium": st.column_config.NumberColumn(format="%.0f")})


def tab_audit(rid: str):
    rows = db.list_audit(rid)
    st.dataframe(pd.DataFrame([{"When": a["created_at"].replace("T", " "), "Who": a["actor"],
                                "Event": a["event_type"], "Details": a["description"]} for a in rows]),
                 hide_index=True)


def page_help():
    html(T.hero())
    html(T.features())
    st.markdown("""
#### What happens to your documents

**You upload them.** The RFQ you sent and every quote you got back, as PDF, Excel, Word or CSV.
If a file is broken or in a format we can't read, you'll know right away and why.

**An AI model reads them.** It fills in the same form for every quote: price, currency, tax,
delivery, validity, certificates and the technical specs. Next to each value it keeps the exact line
it came from. If something isn't in the document, the field stays blank. It doesn't guess.

**Plain rules do the comparing.** No AI here. Prices are put on the same unit and tax basis, and every
requirement gets marked as met, missed, not stated, or worth a second look, with a reason. A cheap
quote that misses a must-have can't come out on top, and "not stated" never counts as a pass. If a
quote couldn't be read, the comparison says so in plain view.

**You check the details.** Compare the values with their source lines and fix anything that's off.
Suppliers with open questions get a ready-to-send clarification email.

**You decide.** Approve or reject. The tool only suggests; every step is logged with your name.
""")

    from app.agents.llm import backends
    chain = " → ".join(b.label for b in backends())
    st.caption(f"AI services, in the order they're tried: {chain}. Your data stays on this machine in {config.DB_PATH.name}.")


{"🏠 Dashboard": page_dashboard, "➕ New evaluation": page_new, "📂 Open evaluation": page_open,
 "📊 Analytics": page_analytics, "💡 How it works": page_help}[page]()
