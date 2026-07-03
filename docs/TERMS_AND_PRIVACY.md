# Terms of Use & Privacy Policy

**Sapienoids Analytics Portal** · Last updated: 4 July 2026

By ticking "I agree" in the app (or by uploading a file), you accept these
terms. If you do not agree, do not upload data.

## 1. What the app does with your data

- **Your file stays in your session.** Uploaded CSV/Excel data is processed
  in the server's memory for the duration of your browser session only. It is
  not saved to a database, not shared with other visitors, and is discarded
  when your session ends or the app restarts.
- **No account, no tracking.** The app requires no sign-up and sets no
  advertising trackers. Streamlit's platform may collect standard operational
  logs (timestamps, errors) as described in
  [Streamlit's privacy notice](https://streamlit.io/privacy-policy).
- **Mapping memory.** To make repeat uploads faster, the app may store the
  *column names* of your file and how they map to business fields. It never
  stores cell values, and you can delete this via "Forget saved mapping".
- **Reports are generated on demand** and downloaded directly to your device;
  the server keeps no copy after your session.

## 2. AI features (optional)

- AI insights, commentary and ask-your-data use **Google Gemini**. When you
  use them, the app sends **column names, aggregate statistics, computed KPI
  values and your typed question** to Google's API — **never raw data rows**.
  Google's handling of that content is governed by the
  [Gemini API terms](https://ai.google.dev/gemini-api/terms).
- AI features only operate when an API key is configured. With no key,
  nothing is sent to any third party.
- If you enter an API key in a running public deployment, be aware the key
  activates AI features for all visitors of that deployment until its next
  restart (the key itself is never displayed).
- Do not upload data containing personal identifiers (names, phone numbers,
  medical record numbers) if your organisation's policy forbids processing
  them with cloud AI services. The privacy-sensitive presets (HR, healthcare,
  education) are designed to keep analysis aggregate-only, but **you** are
  responsible for what you upload.

## 3. No professional advice

All outputs — KPIs, trends, anomalies, forecasts, recommendations, AI
commentary — are **automated statistical analysis for informational purposes
only**. They are not financial, investment, accounting, tax, medical, legal
or employment advice. Forecasts assume history repeats and can be wrong.
Verify every figure against your source systems before acting on it.

## 4. Acceptable use

You agree not to: upload data you have no right to process; attempt to
extract other users' data or the server's files (queries are restricted to
read-only access over your own uploaded table); use the app for unlawful
discrimination or surveillance; or overload the free service.

## 5. Warranty & liability

The app is provided **"as is", without warranty of any kind**. To the maximum
extent permitted by law, the author is not liable for any loss arising from
use of the app or reliance on its outputs, including data loss, business
decisions, or third-party service behaviour (Streamlit, Google).

## 6. Changes

These terms may be updated; the "last updated" date changes accordingly.
Continued use after a change means acceptance.

## 7. Contact

Questions or data concerns: open an issue at
https://github.com/sapienoidscontact/data-web-app or email the maintainer.
