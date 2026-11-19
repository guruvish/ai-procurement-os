# User guide

This is for the person doing the buying. You don't need to know anything technical.

## Starting the app

Open the project folder in a terminal and run `python run.py`. Your browser opens at http://localhost:8501.

Before anything else, type your name in the sidebar. Every change and decision is logged under it.

## 1. Start a new evaluation

Go to **New evaluation** and fill in:

- the RFQ number (each one has to be unique), plus a title, department and company if you like;
- the RFQ document, meaning the request you sent to suppliers;
- the supplier quotes. You can select them all at once. PDF, Excel, Word and CSV all work, and so do scanned PDFs.

Press **Create evaluation**. If a file is broken or in a format the app can't read, it tells you which one
and why, and uploads the rest.

## 2. Let it read the documents (Documents tab)

Press **Read documents and compare**. Each file takes 10 to 15 seconds, and it all runs in the background,
so you can keep using the app while you wait.

Sometimes a file can't be read, usually because the AI service was busy. The button then changes to
**Read the remaining documents**. Files that were already read aren't read again.

## 3. Check what was read (Review tab)

Under each value you'll see the page it came from, the exact line of text, and how confident the model was.

- If a value is wrong, correct it, press **Save corrections**, then **Re-evaluate with my corrections**.
  Re-evaluating doesn't use the AI again.
- A red box means the value doesn't match the line it was supposedly taken from. Check it and correct it
  if needed, then save.
- A yellow box means the supplier's own document gives two different answers. That's one to ask them about.

## 4. Compare suppliers (Compare tab)

Each supplier ends up in one of three places:

| Result | What it means |
|---|---|
| ✅ Compliant | Meets every must-have, and the price can be compared fairly with the others |
| ⚠️ Needs clarification | Nothing fails, but something you required is missing or unclear |
| ❌ Not compliant | At least one must-have clearly fails. A low price doesn't change that |

In the requirement table, ✅ means met, ❌ means missed, ❔ means the quote doesn't say (this never counts as
a pass), and 🔍 means it's worth a second look. Open *How each price was made comparable* to see the working,
for example converting a per-gram price to per-kilo or taking GST out.

## 5. Risks and follow-up questions (Risks tab)

Issues are listed per supplier, most serious first. Where something is missing, there's a draft email to the
supplier asking for exactly that. Edit it as you like and paste it into your email.

## 6. Insights (Insights tab)

How much the recommended supplier saves compared with the most expensive qualifying quote, how close the
runner-up is, what it costs to pass over a cheaper quote that fails a requirement, and what would have to
change for the recommendation to change.

## 7. Decide (Decision tab)

The recommended supplier is already selected. Change it if you want to, then press **Approve** or **Reject**.

- If you reject, or pick a supplier that misses a requirement, you'll need to add a note.
- If some quotes couldn't be read, you'll need to tick a box confirming you know, and add a note saying why
  you're approving anyway.
- Download the PDF report and the Excel workbook. Until someone approves, both are stamped as drafts.

## Also worth knowing

- **Analytics** in the sidebar covers every evaluation: savings, how long decisions take, how often the
  recommendation is followed, and how each supplier has done over time.
- The **Audit** tab shows who did what, and when.
- The **← Back** button at the top takes you to the page you were on before.
- The app only recommends. It never places orders, approves anything or contacts suppliers on its own.
