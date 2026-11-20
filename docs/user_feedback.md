# Stand-in user test and feedback

I didn't have a real buyer available during the sprint, so I acted as one myself. On 19 November, from 13:05 to
13:15, I took the role of a procurement executive using the app for the first time. The task: create RFQ-2026-001,
upload the RFQ and five quotes (one of them deliberately broken), let it read them, review the results and make a
decision. I started the app with `python run.py`, used the sample files from `scripts/make_sample_data.py`, and
didn't look at the code.

Being both builder and tester isn't ideal, since I know how it's meant to work. So I wrote down every moment I
hesitated, got confused or had to guess, and changed something for each one. The first ten came from that session; the rest came up as I
kept using it over the following day.

| # | What happened | How much it mattered | What I changed |
|---|---|---|---|
| U1 | The form said "please fill the RFQ number and upload…" without saying what was actually missing (it was the quotes) | Moderate | It now names what's missing, e.g. "Still needed: Supplier quotes" |
| U2 | Six separate green "uploaded" boxes pushed the tabs off the screen | Moderate | One summary line for uploads, and one box for rejected files |
| U3 | An error message included the technical term "FileDataError" | Minor | Plain wording ("this file seems damaged, try downloading it again"); the technical detail goes to the log |
| U4 | The Audit tab was hidden behind a scroll arrow | Minor | Shorter tab names with icons, so all seven fit on one line |
| U5 | Three quotes failed with "Gemini API error 429" and I didn't know what to do | Serious | Rate-limit handling (F6), and the button now says "Read the 3 remaining documents" |
| U6 | A supplier was recommended although 3 of 4 quotes were missing | Critical | A clear "incomplete" warning, plus a confirmation and note before approving (F7) |
| U7 | Streamlit's own "Deploy" menu and pop-ups were confusing | Minor | Developer controls hidden |
| U8 | It looked plain, like a demo rather than a product | Moderate | A proper visual design; changed again later (U14) |
| U9 | I typed my name while it was reading, the run silently stopped, and the button stayed greyed out | Serious | Processing moved to the background, with a Resume button (F10) |
| U10 | The "press Enter" hint was invisible, disabled buttons looked clickable, some labels were cut off, and headings showed link icons | Minor | All four fixed |
| U11 | Balloons floating up after approving felt wrong for a business tool | Minor | A calm "decision recorded" card showing who approved and when |
| U12 | I wanted more on suppliers, the decision and the risks | Moderate | An Insights tab (savings, how close the runner-up is, what would change the decision, risk profile, scorecard), an Analytics page across all RFQs, and both added to the reports |
| U13 | My name disappeared every time the page refreshed | Minor | The name is kept in the page address |
| U14 | There was no way back to the previous page; clicking in the sidebar opened pages scrolled halfway down; and the text and docs read as stiff and machine-written | Moderate | A Back button that remembers where you came from, every page opening at the top, a calmer navy and teal design with new fonts, and all the on-screen text and guides rewritten in plain language |

**What worked without any help:** creating the evaluation, understanding why the broken file was rejected, finding
the source line under each value, reading the comparison table, and approving.

**How long it took:** about 3 minutes to create it and upload, 56 seconds for the reading, and about 4 minutes from
reviewing to a decision.
