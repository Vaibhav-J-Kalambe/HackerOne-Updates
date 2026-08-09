"""
Polls HackerOne's public program directory, diffs it against the last known
state, and emails/WhatsApps the user about new programs and meaningful
updates to programs already seen (bounty changes, new features, more
reports resolved).

State is stored in state/seen_programs.json and is expected to be committed
back to the repo by the calling GitHub Actions workflow, since Actions
runners are ephemeral.
"""
import json
import os
import smtplib
import sys
from dataclasses import dataclass, asdict
from email.mime.text import MIMEText
from pathlib import Path

from playwright.sync_api import sync_playwright
import urllib.request
import urllib.parse

DIRECTORY_URL = "https://hackerone.com/directory/programs?order_direction=DESC&order_field=launched_at"
STATE_PATH = Path(__file__).resolve().parent.parent / "state" / "seen_programs.json"

TRACKED_FIELDS = ["name", "tags", "launch_date", "reports_resolved", "bounty_min", "bounty_avg"]


@dataclass
class Program:
    handle: str
    name: str
    tags: list
    launch_date: str
    reports_resolved: str
    bounty_min: str
    bounty_avg: str

    def url(self) -> str:
        return f"https://hackerone.com/{self.handle}"


def scrape_directory(max_rows: int = 60) -> list[Program]:
    programs = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(DIRECTORY_URL, wait_until="networkidle", timeout=45000)
        page.wait_for_selector("table tbody tr", timeout=20000)

        rows = page.query_selector_all("table tbody tr")
        for row in rows[:max_rows]:
            cells = row.query_selector_all("td")
            if len(cells) < 5:
                continue

            name_cell_lines = [
                line.strip()
                for line in cells[0].inner_text().split("\n")
                if line.strip()
            ]
            name = name_cell_lines[0] if name_cell_lines else "Unknown"
            tags = name_cell_lines[1:]

            link = cells[0].query_selector("a")
            href = link.get_attribute("href") if link else None
            handle = href.split("?")[0].strip("/").split("/")[-1] if href else name

            launch_date = cells[1].inner_text().strip()
            reports_resolved = cells[2].inner_text().strip()
            bounty_min = cells[3].inner_text().strip()
            bounty_avg = cells[4].inner_text().strip()

            programs.append(
                Program(
                    handle=handle,
                    name=name,
                    tags=tags,
                    launch_date=launch_date,
                    reports_resolved=reports_resolved,
                    bounty_min=bounty_min,
                    bounty_avg=bounty_avg,
                )
            )
        browser.close()
    return programs


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def diff(programs: list[Program], prior_state: dict) -> tuple[list[Program], list[tuple[Program, dict]]]:
    new_programs = []
    updated_programs = []

    for program in programs:
        prior = prior_state.get(program.handle)
        if prior is None:
            new_programs.append(program)
            continue

        changes = {}
        current = asdict(program)
        for field in TRACKED_FIELDS:
            if current[field] != prior.get(field):
                changes[field] = {"old": prior.get(field), "new": current[field]}
        if changes:
            updated_programs.append((program, changes))

    return new_programs, updated_programs


def format_email(new_programs: list[Program], updated_programs: list[tuple[Program, dict]]) -> str:
    lines = []
    if new_programs:
        lines.append(f"NEW PROGRAMS ({len(new_programs)})")
        lines.append("=" * 40)
        for p in new_programs:
            lines.append(f"\n{p.name}")
            lines.append(f"  Link: {p.url()}")
            lines.append(f"  Features: {', '.join(p.tags) if p.tags else 'None listed'}")
            lines.append(f"  Launched: {p.launch_date}")
            lines.append(f"  Reports resolved: {p.reports_resolved}")
            lines.append(f"  Bounty range: {p.bounty_min} - {p.bounty_avg}")
        lines.append("")

    if updated_programs:
        lines.append(f"UPDATED PROGRAMS ({len(updated_programs)})")
        lines.append("=" * 40)
        for p, changes in updated_programs:
            lines.append(f"\n{p.name}  ({p.url()})")
            for field, delta in changes.items():
                lines.append(f"  {field}: {delta['old']!r} -> {delta['new']!r}")
        lines.append("")

    return "\n".join(lines)


def send_email(subject: str, body: str) -> None:
    user = os.environ["GMAIL_USER"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]
    to_addr = os.environ.get("NOTIFY_EMAIL", user)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to_addr

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(user, app_password)
        server.sendmail(user, [to_addr], msg.as_string())


def send_whatsapp(body: str) -> None:
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    from_number = os.environ.get("TWILIO_WHATSAPP_FROM")
    to_number = os.environ.get("TWILIO_WHATSAPP_TO")

    if not all([sid, token, from_number, to_number]):
        print("WhatsApp env vars not fully set, skipping WhatsApp send.")
        return

    # WhatsApp messages have a practical length limit; keep it short.
    if len(body) > 1500:
        body = body[:1450] + "\n...(see email for full details)"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = urllib.parse.urlencode(
        {"From": from_number, "To": to_number, "Body": body}
    ).encode()
    req = urllib.request.Request(url, data=data)
    req.add_header(
        "Authorization",
        "Basic " + __import__("base64").b64encode(f"{sid}:{token}".encode()).decode(),
    )
    with urllib.request.urlopen(req) as resp:
        if resp.status >= 300:
            print(f"Twilio WhatsApp send failed: {resp.status} {resp.read()}")


def main() -> None:
    programs = scrape_directory()
    if not programs:
        print("No programs scraped; aborting without touching state (page may have failed to load).")
        sys.exit(1)

    prior_state = load_state()
    new_programs, updated_programs = diff(programs, prior_state)

    if new_programs or updated_programs:
        body = format_email(new_programs, updated_programs)
        subject = f"HackerOne: {len(new_programs)} new, {len(updated_programs)} updated program(s)"
        print(body)
        send_email(subject, body)
        send_whatsapp(body)
    else:
        print("No new or updated programs since last run.")

    new_state = {p.handle: asdict(p) for p in programs}
    # Preserve any previously-seen programs that fell off the scraped page
    # (e.g. only top N rows are checked each run) so they aren't re-reported
    # as "new" the next time they resurface near the top.
    merged_state = {**prior_state, **new_state}
    save_state(merged_state)


if __name__ == "__main__":
    main()
