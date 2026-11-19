# Proxy-user test & feedback (Day 3-4)

**Tester:** Kavuturu Guru Vishnu (acting as procurement executive), 2026-11-19, 13:05-13:15 IST.
**Task:** create RFQ-2026-001, upload RFQ + 5 quotations (incl. one corrupted), process, review, decide.
**Setup:** `python run.py`, sample files from `scripts/make_sample_data.py`, no help from the builder.

| # | Observation (what the user saw / did) | Severity | Change made (patch step 10) |
|---|---|---|---|
| U1 | "Please fill the RFQ number and upload..." - did not say WHICH field was missing (quotations were) | Medium | Message now names the missing items, e.g. "Still missing: **Supplier quotations**" |
| U2 | Six separate green "Uploaded ..." boxes pushed the tabs below the fold | Medium | One summary: "Uploaded 4 file(s): ...", one box for rejected files |
| U3 | Error showed a technical term "(FileDataError)" | Low | Plain message: "seems damaged or incomplete - try downloading or saving it again"; technical detail goes to the log |
| U4 | "Audit trail" tab hidden behind a scroll arrow | Low | Short tab names (① Documents ... 🧾 Audit) - all fit on one line |
| U5 | 3 quotations failed with "Gemini API error 429" - unclear what to do | **High** | Rate-limit handling (F6); button changes to "Read the N remaining documents"; messages say exactly what to click |
| U6 | Recommendation shown although 3 of 4 suppliers were missing | **Critical** | Incomplete banner + confirmation required (F7) |
| U7 | Streamlit "Deploy" menu and promo pop-up confused the user | Low | `toolbarMode = "viewer"` hides developer controls |
| U9 | Typed name during processing -> run silently stopped, button greyed out, header kept saying "AI is reading" | **High** | Background processing job + Resume (F10) |
| U10 | "Press Enter to apply" hint invisible in sidebar; disabled buttons looked clickable; metric labels cut off ("Rate-limit ..."); link icons on headings | Low | Contrast fixed, disabled style, short labels with tooltips, heading anchors hidden |
| U11 | Balloons after approval felt unprofessional for a premium client | Low | Calm "Decision recorded" card with an animated checkmark, approver and time; toast notification |
| U12 | "Wants BI on suppliers, decision and risk" | Medium | New 📊 Insights tab (savings, gap to runner-up, compliance premium, decision robustness, price-vs-delivery, risk profile, scorecard), portfolio 📊 Analytics page, decision analysis + scorecard in PDF/Excel |
| U13 | Reviewer name lost after every refresh | Low | Name kept in the page address (?user=) |
| U8 | "Looks plain - should feel like a product" | Medium | New theme: gradient hero with animated isometric illustration, workflow stepper, supplier cards with a "Recommended" ribbon, coloured cost chart, live processing log |

**What worked without help:** creating the evaluation, understanding the corrupted-file rejection,
finding the source quote under each value, reading the compliance matrix, approving.

**Time:** create + upload ~3 min; AI processing 56 s; review to decision ~4 min.
