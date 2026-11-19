# Google Sheets export - setup (optional, ~10 minutes)

The app writes each evaluation into a shared Google Sheet (tabs: Summary, Comparison, Compliance matrix,
Findings, Evidence, Approvals). Without this setup, everything else works and the **Excel download**
contains the same tables.

## 1. Create a service account (once)
1. Open https://console.cloud.google.com and create a project (e.g. `rfq-evaluator`).
2. **APIs & Services -> Library** -> search **Google Sheets API** -> **Enable**.
3. **IAM & Admin -> Service accounts -> Create service account** (name: `rfq-exporter`, no roles needed).
4. Open the new account -> **Keys -> Add key -> Create new key -> JSON**. A `.json` file downloads.
5. Save it in the project as `credentials/google_service_account.json`
   (the `credentials/` folder is in `.gitignore` - the key never goes to GitHub).

## 2. Share a spreadsheet with it
1. Create a Google Sheet (e.g. "RFQ evaluations").
2. Open the JSON file, copy the `client_email` value (ends with `iam.gserviceaccount.com`).
3. In the sheet click **Share**, paste that e-mail, give **Editor**, untick "Notify".
4. Copy the sheet ID from the URL: `https://docs.google.com/spreadsheets/d/<THIS PART>/edit`.

## 3. Configure and test
Add to `.env`:
```
GOOGLE_SHEET_ID=<the id from step 2.4>
# optional, default shown:
# GOOGLE_SERVICE_ACCOUNT_FILE=credentials/google_service_account.json
```
Restart the app -> open an evaluation -> **✅ Decision** tab -> **📤 Export to Google Sheets**.

## Troubleshooting
| Message | Fix |
|---|---|
| "Spreadsheet not found" | Wrong `GOOGLE_SHEET_ID`, or the sheet is not shared with the service-account e-mail |
| "Google refused access" | Share the sheet with the service-account e-mail as **Editor** |
| Button missing ("not set up") | `.env` has no `GOOGLE_SHEET_ID`, or the JSON file is not at the configured path |
| Company policy blocks service-account keys | Use the Excel download instead (same tables) |
