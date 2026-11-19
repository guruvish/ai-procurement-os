"""Evaluation reports: Excel workbook + PDF, built from ONE set of tables so every format agrees.
Reports before approval are watermarked DRAFT; after approval they carry the human decision record."""
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

from app import config, db
from app.services import analytics as A

VERDICT = {"COMPLIANT": "Compliant", "NEEDS_CLARIFICATION": "Needs clarification", "NOT_COMPLIANT": "Not compliant"}
STATUS_FILL = {"PASS": "DCFCE7", "FAIL": "FFE4E6", "UNKNOWN": "F1F5F9", "REVIEW_REQUIRED": "FEF3C7",
               "NOT_APPLICABLE": "F8FAFC", "COMPLIANT": "DCFCE7", "NEEDS_CLARIFICATION": "FEF3C7",
               "NOT_COMPLIANT": "FFE4E6", "HIGH": "FFE4E6", "MEDIUM": "FEF3C7", "LOW": "F1F5F9"}
EVIDENCE_FIELDS = ["unit_price", "currency", "tax_status", "delivery_days", "valid_until", "payment_terms"]


def _num(v, digits=2):
    return "" if v is None else (f"{v:,.{digits}f}" if isinstance(v, (int, float)) else str(v))


# ---------------------------------------------------------------- shared data + tables
def collect(rid: str) -> dict:
    req = db.get_request(rid)
    if req is None:
        raise ValueError("Evaluation not found.")
    approvals = db.list_approvals(rid)
    final = next((a for a in reversed(approvals) if a["decision"] == "APPROVED"), None)
    return {"req": req, "rfq": db.get_rfq(rid), "quotes": db.list_quotations(rid),
            "evals": db.get_evaluations(rid), "rec": db.get_recommendation(rid) or {},
            "approvals": approvals, "final": final, "audit": db.list_audit(rid),
            "docs": db.list_documents(rid), "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def tables(d: dict) -> dict:
    """name -> list of rows (first row = header). Used by Excel, PDF and Google Sheets."""
    req, rfq, evals, rec, final = d["req"], d["rfq"], d["evals"], d["rec"], d["final"]
    unit, cur = (rfq.unit or "", rfq.currency or "") if rfq else ("", "")
    status = (f"APPROVED by {final['reviewer']} on {final['reviewed_at'][:16].replace('T', ' ')}"
              if final else "DRAFT - NOT APPROVED")
    summary = [["Field", "Value"],
               ["RFQ number", req["rfq_number"]], ["Title", req["title"] or ""],
               ["Buyer", req["buyer"] or ""], ["Department", req["department"] or ""],
               ["Report status", status], ["Generated", d["generated_at"]]]
    if rfq:
        summary += [["Product", rfq.product_name or ""], ["Required quantity", f"{_num(rfq.required_quantity, 0)} {unit}"],
                    ["Max delivery", f"{rfq.max_delivery_days} days" if rfq.max_delivery_days is not None else ""],
                    ["Payment terms", rfq.payment_terms or ""], ["Currency", cur],
                    ["Required certificates", ", ".join(rfq.required_certificates)]]
    summary += [["System recommendation", rec.get("explanation", "")],
                ["Selected supplier (human)", final["selected_supplier"] if final else ""],
                ["Reviewer comments", final["comments"] if final else ""]]
    if rec.get("unprocessed_documents"):
        summary.append(["NOT EVALUATED", ", ".join(rec["unprocessed_documents"])])

    comparison = [["Rank", "Supplier", "Verdict", "Risk", f"Price per {unit} excl. tax ({cur})",
                   f"Total cost ({cur})", "Mandatory failures", "Open items", "How the price was normalized"]]
    for i, e in enumerate(evals, 1):
        comparison.append([i, e.supplier_name, VERDICT[e.overall_status], e.risk_level, _num(e.normalized_unit_price),
                           _num(e.total_cost), e.mandatory_failures, e.unknowns,
                           "; ".join(e.price_notes) or "used as quoted"])

    reqs, seen = [], set()
    for e in evals:
        for c in e.checks:
            if c.requirement not in seen:
                seen.add(c.requirement)
                reqs.append((c.requirement, c.required, c.mandatory))
    matrix = [["Requirement", "Mandatory", "Required"] + [e.supplier_name for e in evals]]
    for name, required, mandatory in reqs:
        row = [name, "yes" if mandatory else "no", required]
        for e in evals:
            c = next((x for x in e.checks if x.requirement == name), None)
            row.append(f"{c.status.value}: {c.offered}" if c else "")
        matrix.append(row)

    checks = [["Supplier", "Check", "Result", "Mandatory", "Required", "Offered", "Reason"]]
    findings = [["Supplier", "Severity", "Category", "Finding"]]
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    for e in evals:
        checks += [[e.supplier_name, c.requirement, c.status.value, "yes" if c.mandatory else "no",
                    c.required, c.offered, c.reason] for c in e.checks]
        findings += [[e.supplier_name, f.severity, f.category, f.message]
                     for f in sorted(e.findings, key=lambda f: order[f.severity])]

    evidence = [["Supplier", "Field", "Value", "Source document", "Page", "Source text", "Confidence",
                 "Human edited"]]
    for item in d["quotes"]:
        q = item["quotation"]
        for f in EVIDENCE_FIELDS:
            ev = q.evidence.get(f)
            evidence.append([q.supplier_name, f, str(getattr(q, f) if getattr(q, f) is not None else "not stated"),
                             q.source_document, ev.page if ev and ev.page else "", ev.quote if ev and ev.quote else "",
                             f"{ev.confidence:.0%}" if ev else "", "yes" if item["edited_by_human"] else "no"])
        for s in q.specifications:
            ev = s.evidence
            evidence.append([q.supplier_name, s.name, f"{s.value} {s.unit or ''}".strip(), q.source_document,
                             ev.page if ev and ev.page else "", ev.quote if ev and ev.quote else "",
                             f"{ev.confidence:.0%}" if ev else "", "yes" if item["edited_by_human"] else "no"])

    da = A.decision_analysis(evals, rec)

    def money(v):
        return "-" if v is None else f"{v:,.2f} {cur}".strip()

    analysis = [["Measure", "Value", "Meaning"],
                ["Compliant suppliers", f"{da['n_compliant']} of {da['n_suppliers']}",
                 f"{da['n_clarification']} need clarification, {da['n_not_compliant']} not compliant"],
                ["Savings vs highest compliant quote", money(da["savings_vs_highest"]) +
                 (f" ({da['savings_vs_highest_pct']}%)" if da["savings_vs_highest_pct"] else ""),
                 "Recommended total compared with the most expensive compliant quote"],
                ["Savings vs average compliant quote", money(da["savings_vs_average"]), "Recommended total vs the average"],
                ["Gap to runner-up", money(da["gap_to_runner_up"]) +
                 (f" ({da['gap_to_runner_up_pct']}%)" if da["gap_to_runner_up_pct"] is not None else ""),
                 f"Next compliant supplier: {da['runner_up'] or '-'}"],
                ["Compliance premium", money(da["compliance_premium"]) if da["compliance_premium"] else "none",
                 f"Extra cost vs the cheapest quote ({da['cheapest_overall'] or '-'}), which fails a mandatory requirement"
                 if da["compliance_premium"] else "The cheapest quote is also compliant"],
                ["Decision robustness", da["robustness"], ""]]
    quotes_by_name = {x["quotation"].supplier_name: x["quotation"] for x in d["quotes"]}
    sc_rows = A.scorecard(rfq, evals, quotes_by_name)
    sc_cols = ["Supplier", "Verdict", "Price / unit", "Total cost", "Technical pass %", "Documents %", "Delivery days",
               "Delivery headroom", "Payment days", "Open items", "High risks", "Risk"]
    scorecard = [sc_cols] + [[("" if r[c] is None else (VERDICT.get(r[c], r[c]) if c == "Verdict" else
                               (_num(r[c]) if isinstance(r[c], float) else r[c]))) for c in sc_cols] for r in sc_rows]

    approvals = [["When", "Reviewer", "Decision", "Selected supplier", "Comments"]] + [
        [a["reviewed_at"].replace("T", " "), a["reviewer"], a["decision"], a["selected_supplier"] or "", a["comments"] or ""]
        for a in d["approvals"]]
    audit = [["When", "Who", "Event", "Details"]] + [
        [a["created_at"].replace("T", " "), a["actor"], a["event_type"], a["description"]] for a in d["audit"]]
    return {"Summary": summary, "Decision analysis": analysis, "Comparison": comparison, "Scorecard": scorecard,
            "Compliance matrix": matrix, "Checks": checks,
            "Findings": findings, "Evidence": evidence, "Approvals": approvals, "Audit trail": audit}


# ---------------------------------------------------------------- Excel
def excel_report(rid: str) -> bytes:
    d = collect(rid)
    wb = Workbook()
    wb.remove(wb.active)
    head_fill, head_font = PatternFill("solid", fgColor="4F46E5"), Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="E2E8F0")
    for name, rows in tables(d).items():
        ws = wb.create_sheet(name[:31])
        for r in rows:
            ws.append(list(r))
        for cell in ws[1]:
            cell.fill, cell.font = head_fill, head_font
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        widths = {}
        for row in ws.iter_rows(min_row=1):
            for cell in row:
                cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
                if cell.row > 1:
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
                    key = str(cell.value or "").split(":")[0].upper().replace(" ", "_")
                    if key in STATUS_FILL or str(cell.value or "").upper().replace(" ", "_") in STATUS_FILL:
                        k = key if key in STATUS_FILL else str(cell.value).upper().replace(" ", "_")
                        cell.fill = PatternFill("solid", fgColor=STATUS_FILL[k])
                widths[cell.column] = max(widths.get(cell.column, 8), min(len(str(cell.value or "")) + 2, 60))
        for col, w in widths.items():
            ws.column_dimensions[get_column_letter(col)].width = w
        ws.freeze_panes = "A2" if name != "Summary" else None
        if name not in ("Summary",) and ws.max_row > 1:
            ws.auto_filter.ref = ws.dimensions
        if name == "Summary":
            ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 100
            for row in ws.iter_rows(min_row=2):
                row[0].font = Font(bold=True)
            if d["final"] is None:
                ws.insert_rows(1)
                ws["A1"] = "DRAFT - NOT APPROVED. The system recommends; a human reviewer has not approved this evaluation."
                ws["A1"].font = Font(bold=True, color="B91C1C")
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ---------------------------------------------------------------- PDF
_INK, _MUTED, _BRAND = colors.HexColor("#14213D"), colors.HexColor("#66728A"), colors.HexColor("#0E6E6B")


def _styles():
    ss = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=ss["Title"], fontSize=20, textColor=_INK, alignment=0, spaceAfter=2),
        "sub": ParagraphStyle("s", parent=ss["Normal"], fontSize=10, textColor=_MUTED),
        "h2": ParagraphStyle("h", parent=ss["Heading2"], fontSize=13, textColor=_BRAND, spaceBefore=10, spaceAfter=4),
        "body": ParagraphStyle("b", parent=ss["Normal"], fontSize=9, leading=12, textColor=_INK),
        "cell": ParagraphStyle("c", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=_INK),
        "head": ParagraphStyle("hd", parent=ss["Normal"], fontSize=7.5, leading=9.5, textColor=colors.white,
                               fontName="Helvetica-Bold"),
        "badge": ParagraphStyle("bd", parent=ss["Normal"], fontSize=10, fontName="Helvetica-Bold",
                                alignment=TA_CENTER, textColor=colors.white),
    }


def _esc(v) -> str:
    return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("₹", "INR ")


def _table(rows, st, widths=None, colorize=True):
    data = [[Paragraph(_esc(c), st["head"]) for c in rows[0]]]
    data += [[Paragraph(_esc(c), st["cell"]) for c in r] for r in rows[1:]]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), _BRAND), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
             ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
             ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if colorize:
        for ri, r in enumerate(rows[1:], 1):
            for ci, c in enumerate(r):
                key = str(c).split(":")[0].upper().replace(" ", "_")
                if key in STATUS_FILL:
                    style.append(("BACKGROUND", (ci, ri), (ci, ri), colors.HexColor("#" + STATUS_FILL[key])))
    t.setStyle(TableStyle(style))
    return t


def pdf_report(rid: str) -> bytes:
    d = collect(rid)
    tb, st = tables(d), _styles()
    req, final, rec = d["req"], d["final"], d["rec"]
    buf = BytesIO()
    page_w = landscape(A4)[0] - 30 * mm

    def _decorate(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(15 * mm, 8 * mm, f"{req['rfq_number']} - Supplier evaluation report - generated {d['generated_at']} "
                                           "by AI Procurement OS (AI extraction + rule-based evaluation; decision by a human reviewer)")
        canvas.drawRightString(landscape(A4)[0] - 15 * mm, 8 * mm, f"Page {doc.page}")
        if final is None:
            canvas.setFont("Helvetica-Bold", 70)
            canvas.setFillColor(colors.Color(0.86, 0.15, 0.15, alpha=0.08))
            canvas.translate(landscape(A4)[0] / 2, landscape(A4)[1] / 2)
            canvas.rotate(25)
            canvas.drawCentredString(0, 0, "DRAFT - NOT APPROVED")
        canvas.restoreState()

    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=13 * mm, bottomMargin=14 * mm,
                            title=f"Supplier evaluation {req['rfq_number']}", author="AI Procurement OS")
    story = [Paragraph(f"Supplier Evaluation Report - {_esc(req['rfq_number'])}", st["title"]),
             Paragraph(_esc(" · ".join(x for x in (req["title"], req["buyer"], f"Generated {d['generated_at']}") if x)),
                       st["sub"]), Spacer(1, 6)]
    if final:
        badge_text, badge_color = (f"APPROVED - selected supplier: {final['selected_supplier'] or '-'} - by "
                                   f"{final['reviewer']} on {final['reviewed_at'][:16].replace('T', ' ')}"), colors.HexColor("#059669")
    else:
        badge_text, badge_color = "DRAFT - NOT APPROVED: system recommendation only, pending human decision", colors.HexColor("#b91c1c")
    badge = Table([[Paragraph(_esc(badge_text), st["badge"])]], colWidths=[page_w])
    badge.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), badge_color), ("TOPPADDING", (0, 0), (-1, -1), 6),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [badge, Spacer(1, 4)]

    story += [Paragraph("1. Recommendation", st["h2"]), Paragraph(_esc(rec.get("explanation", "No evaluation yet.")), st["body"])]
    if rec.get("unprocessed_documents"):
        story.append(Paragraph(f"<font color='#b91c1c'><b>Incomplete:</b> not evaluated: "
                               f"{_esc(', '.join(rec['unprocessed_documents']))}</font>", st["body"]))
    robust = next((r[1] for r in tb["Decision analysis"] if r[0] == "Decision robustness"), "")
    story += [Paragraph("Decision analysis", st["h2"]),
              _table([r for r in tb["Decision analysis"] if r[0] != "Decision robustness"], st,
                     [60 * mm, 55 * mm, page_w - 115 * mm], colorize=False), Spacer(1, 4),
              Paragraph(f"<b>Decision robustness.</b> {_esc(robust)}", st["body"])]
    story += [Paragraph("2. RFQ summary", st["h2"]),
              _table([r for r in tb["Summary"] if r[0] not in ("System recommendation", "Reviewer comments",
                                                                 "Selected supplier (human)", "Report status")],
                     st, [55 * mm, page_w - 55 * mm], colorize=False)]
    n = len(tb["Comparison"][0])
    story += [Paragraph("3. Supplier comparison", st["h2"]),
              _table(tb["Comparison"], st, [12 * mm, 45 * mm, 30 * mm, 16 * mm, 28 * mm, 28 * mm, 20 * mm, 16 * mm]
                     + [page_w - 195 * mm] if n == 9 else None)]
    story += [Paragraph("Supplier scorecard (real values, no weights)", st["h2"]),
              _table(tb["Scorecard"], st, [42 * mm, 28 * mm, 20 * mm, 24 * mm, 20 * mm, 21 * mm, 17 * mm, 18 * mm, 17 * mm,
                                          15 * mm, 15 * mm] + [page_w - 237 * mm])]
    m_cols = len(tb["Compliance matrix"][0])
    sup_w = (page_w - 95 * mm) / max(1, m_cols - 3)
    story += [PageBreak(), Paragraph("4. Compliance matrix", st["h2"]),
              Paragraph("PASS = meets · FAIL = does not meet · UNKNOWN = not stated (never treated as a pass) · "
                        "REVIEW_REQUIRED = needs human check", st["sub"]), Spacer(1, 3),
              _table(tb["Compliance matrix"], st, [48 * mm, 19 * mm, 28 * mm] + [sup_w] * (m_cols - 3))]
    serious = [tb["Findings"][0]] + [r for r in tb["Findings"][1:] if r[1] in ("HIGH", "MEDIUM")]
    low = len(tb["Findings"]) - len(serious)
    story += [Paragraph("5. Risks and open items", st["h2"]),
              _table(serious, st, [55 * mm, 20 * mm, 28 * mm, page_w - 103 * mm]) if len(serious) > 1
              else Paragraph("No high or medium findings.", st["body"]),
              Paragraph(f"{low} low-severity finding(s) are listed in the Excel report.", st["sub"])]
    appr = tb["Approvals"] if len(tb["Approvals"]) > 1 else [tb["Approvals"][0], ["-", "-", "PENDING", "-", "No decision yet"]]
    story += [KeepTogether([Paragraph("6. Human decision record", st["h2"]),
                            _table(appr, st, [32 * mm, 40 * mm, 25 * mm, 55 * mm, page_w - 152 * mm])])]
    story += [PageBreak(), Paragraph("7. Evidence - where each value came from", st["h2"]),
              Paragraph("Values were extracted by AI from the supplier documents; the source text allows every value "
                        "to be checked. 'Corrected by human' marks quotations edited during review.", st["sub"]), Spacer(1, 3),
              _table(tb["Evidence"], st, [40 * mm, 26 * mm, 30 * mm, 36 * mm, 12 * mm, page_w - 194 * mm, 22 * mm, 28 * mm],
                     colorize=False)]
    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


# ---------------------------------------------------------------- final report
def file_stem(rid: str) -> str:
    req = db.get_request(rid)
    return f"{req['rfq_number']}_evaluation".replace("/", "-").replace(" ", "_")


def save_final_reports(rid: str, actor: str) -> list:
    """After approval: store PDF + Excel in data/reports, mark REPORT_GENERATED, audit it."""
    status = db.get_status(rid)
    if status not in (db.S.APPROVED, db.S.REPORT_GENERATED):
        raise db.WorkflowStateError("Final reports are available after approval. Download a draft instead.")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    paths = []
    for ext, data in (("pdf", pdf_report(rid)), ("xlsx", excel_report(rid))):
        path = config.REPORT_DIR / f"{file_stem(rid)}_{stamp}.{ext}"
        path.write_bytes(data)
        paths.append(path)
    if status == db.S.APPROVED:
        db.set_status(rid, db.S.REPORT_GENERATED, actor, "final PDF + Excel saved")
    db.audit(rid, "REPORT_GENERATED", ", ".join(p.name for p in paths), actor)
    return paths
