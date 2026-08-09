# HackerOne Directory Watcher

Polls HackerOne's public program directory (sorted by launch date) every 15
minutes via GitHub Actions, and emails + WhatsApps you when:
- a new public program appears, or
- a program you've already seen changes (bounty amounts, reports resolved
  count, or features like retesting/collaboration/managed).

It only sees what HackerOne's public directory page shows (no private
program info, no login). It checks the top 60 rows sorted by newest launch
date each run.

## One-time setup

### 1. Create the GitHub repo

```
cd hackerone-watcher
git init
git add .
git commit -m "Initial commit"
gh repo create hackerone-watcher --private --source=. --push
```

### 2. Gmail App Password (for sending email)

1. Turn on 2-Step Verification on the Gmail account you want to send *from*
   (this can be the same account as vaibhavkalambe2003@gmail.com, or a
   separate "bot" Gmail account — a separate account is cleaner).
2. Go to https://myaccount.google.com/apppasswords
3. Create an app password named "hackerone-watch", copy the 16-character
   code.

### 3. Twilio WhatsApp Sandbox (for sending WhatsApp)

1. Sign up at https://www.twilio.com/try-twilio (free trial).
2. Go to Messaging > Try it out > Send a WhatsApp message. It shows a
   sandbox number (e.g. `+1 415 523 8886`) and a join code like
   `join some-word`.
3. From your WhatsApp (9969272885), send that join code as a WhatsApp
   message to the sandbox number. This links your number to the sandbox.
   **The sandbox session expires after 3 days of no activity from your
   side — you'll need to re-send the join code if it goes quiet.** This is
   a Twilio sandbox limitation; moving to a paid WhatsApp sender removes it.
4. Copy your Account SID and Auth Token from the Twilio Console dashboard.

### 4. Add GitHub repo secrets

In the repo: Settings > Secrets and variables > Actions > New repository
secret. Add:

| Secret | Value |
|---|---|
| `GMAIL_USER` | the Gmail address you created the app password for |
| `GMAIL_APP_PASSWORD` | the 16-character app password |
| `NOTIFY_EMAIL` | `vaibhavkalambe2003@gmail.com` |
| `TWILIO_ACCOUNT_SID` | from Twilio console |
| `TWILIO_AUTH_TOKEN` | from Twilio console |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` (your sandbox number) |
| `TWILIO_WHATSAPP_TO` | `whatsapp:+919969272885` |

### 5. First run — seed the state

The very first run has no prior state, so every currently-listed program
will be reported as "new" (could be 50+ programs in one email/WhatsApp
message). To avoid that flood:

- Run once manually first with notifications disabled by temporarily
  removing the secrets, just to populate `state/seen_programs.json`, commit
  it, then add the secrets back. **OR**
- Just let the first run send the big list — it's a one-time thing, then
  every run after only reports actual changes.

Trigger a manual run from the Actions tab ("Run workflow") or push a commit.

## Local testing

```
pip install -r requirements.txt
playwright install chromium
set GMAIL_USER=you@gmail.com
set GMAIL_APP_PASSWORD=xxxx
set NOTIFY_EMAIL=vaibhavkalambe2003@gmail.com
python scripts/check_hackerone.py
```

(Leave the `TWILIO_*` vars unset locally to skip WhatsApp sending during
testing — the script just logs and continues.)

## Limitations

- Only tracks the top 60 rows of the public directory sorted by launch
  date — a program would have to fall further back than that between two
  runs to be missed (unlikely at a 15-minute cadence).
- "Updated" detection is based on what the directory row itself shows
  (bounty min/avg, reports resolved, feature badges, launch date). It does
  **not** detect scope/policy text changes inside an individual program's
  page — that would require fetching and diffing every known program's
  policy page on every run, which doesn't scale well against thousands of
  programs. If you want that for a specific short list of programs you
  care about, say so and it can be added as a separate, smaller watchlist.
- GitHub Actions' `schedule` cron is best-effort and can lag by a few
  minutes under load; not a hard real-time guarantee.
