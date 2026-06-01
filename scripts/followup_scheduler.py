#!/usr/bin/env python3
"""
Follow-up scheduler — reads the committed cold-email history, identifies companies
due for a follow-up, and generates draft texts ready to copy into Gmail.

Data source: data/sent_history.csv (date, company, email, persona, cv, subject, status).
This works on GitHub Actions with no external CSV/gist dependency.

Triggers (days since the initial email was sent):
- J+7  → Version A (simple bump)
- J+14 → Version B (value-add)
- J+21 → Version C (graceful goodbye)

Skips rows whose status indicates the thread is closed (replied / bounced / stop).

Output: /tmp/followups_to_send.json + /tmp/followups_<date>.md

Resilience: missing/empty data never hard-fails (exit 0) so the cron does not spam
failure notifications.

Run via GitHub Actions cron (Sun–Wed 08:00 UTC).
"""

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(os.environ.get("JOB_MADINAH_ROOT", Path(__file__).resolve().parent.parent))
# Primary source = committed cold-email history. A custom path can still be forced
# via JOB_MADINAH_TRACKING_CSV (back-compat); we then read it with flexible columns.
SENT_HISTORY = ROOT / "data" / "sent_history.csv"
OVERRIDE_CSV = os.environ.get("JOB_MADINAH_TRACKING_CSV", "").strip()
OUTPUT_DIR = Path("/tmp")

# Status substrings that mean "do not follow up".
SKIP_STATUS_SUBSTRINGS = (
    "repl",      # replied
    "répond",    # répondu
    "bounce",    # bounced
    "invalid",
    "stop",
    "refus",
    "reject",
    "hired",
    "embauch",
)


VERSION_A = """{greeting}

Just a quick note to surface my message from {original_date} in case it had been missed.

I am still very interested in joining {company} and would value a brief 15-min conversation when your schedule allows.

Happy to share additional materials, references, or a short intro video if useful.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""

VERSION_B = """{greeting}

Following up on my note from {original_date}.

Should you reconsider opening conversations for Senior Marketing roles at {company}, I remain very interested and available - happy to share a short Loom walking through a Vision 2030-aligned acquisition plan tailored to your team.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""

VERSION_C = """{greeting}

This is my last note on this thread - I will respect your time.

{company} remains high on my shortlist, and I would welcome the chance to reconnect whenever the timing makes sense. If a different team or division might be a better fit, I would be grateful for an introduction.

Wishing you continued success.

Best regards,
Nuredin Mohamed Ali
"""


def load_rows():
    """Load outreach rows from the override CSV if set, else sent_history.csv.

    Returns a list of normalized dicts: {date, company, email, subject, status}.
    Handles both the cold-email schema (date/company/email/subject/status) and the
    older French tracking schema (Date candidature/Entreprise/Statut) if an override
    CSV is provided.
    """
    path = Path(OVERRIDE_CSV) if OVERRIDE_CSV else SENT_HISTORY
    if not path.exists():
        print(f"[INFO] No outreach data found at {path} - nothing to schedule", file=sys.stderr)
        return []
    rows = []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                rows.append(
                    {
                        "date": (r.get("date") or r.get("Date candidature") or "").strip(),
                        "company": (r.get("company") or r.get("Entreprise") or "").strip(),
                        "email": (r.get("email") or "").strip(),
                        "subject": (r.get("subject") or "").strip(),
                        "status": (r.get("status") or r.get("Statut") or "").strip(),
                        "contact": (r.get("Personne contactée") or "").strip(),
                    }
                )
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] could not read {path}: {e}", file=sys.stderr)
        return []
    return rows


def extract_first_name(contact: str) -> str:
    if not contact or not contact.strip():
        return ""
    name_part = contact.split("/")[0].split("(")[0].strip()
    if not name_part or "@" in name_part:
        return ""
    tokens = name_part.split()
    if not tokens:
        return ""
    first = tokens[0].strip(",.;")
    if first.lower() in {"hr", "team", "department", "linkedin", "n/a"}:
        return ""
    return first


def build_greeting(contact: str, company: str) -> str:
    """Personalised greeting - never 'Dear Hiring Manager'."""
    first = extract_first_name(contact)
    if first:
        return f"Dear {first},"
    company = (company or "").strip()
    if company:
        return f"Dear {company} Team,"
    return "Dear Marketing Team,"


def main():
    rows = load_rows()
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_date = datetime.now().date()

    followups = []
    for row in rows:
        status = row["status"].lower()
        if any(sub in status for sub in SKIP_STATUS_SUBSTRINGS):
            continue

        date_str = row["date"]
        if not date_str:
            continue
        try:
            d_init = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
        except ValueError:
            continue

        days_since = (today_date - d_init).days

        if 7 <= days_since <= 9:
            version, template = "A", VERSION_A
        elif 13 <= days_since <= 16:
            version, template = "B", VERSION_B
        elif 20 <= days_since <= 22:
            version, template = "C", VERSION_C
        else:
            continue

        company = row["company"]
        contact = row["contact"]
        greeting = build_greeting(contact, company)
        subject = row["subject"] or f"Senior Digital Marketing Manager - {company}"
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        body = template.format(
            greeting=greeting,
            company=company,
            original_date=d_init.strftime("%B %d"),
        )

        followups.append(
            {
                "version": version,
                "company": company,
                "email": row["email"],
                "contact": contact,
                "original_date": date_str,
                "days_since": days_since,
                "subject": subject,
                "body": body,
            }
        )

    # Always write outputs (even if empty) so downstream steps are predictable.
    out_json = OUTPUT_DIR / "followups_to_send.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(followups, f, indent=2, ensure_ascii=False)

    out_md = OUTPUT_DIR / f"followups_{today_str}.md"
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Follow-ups due {today_str}\n\n")
        f.write(f"Total: {len(followups)} contacts\n\n---\n\n")
        for fu in followups:
            f.write(f"## {fu['company']} - Version {fu['version']} (J+{fu['days_since']})\n\n")
            f.write(f"- Contact: {fu['contact'] or fu['email'] or 'n/a'}\n")
            f.write(f"- Subject: `{fu['subject']}`\n\n")
            f.write("```\n")
            f.write(fu["body"])
            f.write("```\n\n---\n\n")

    print(f"[OK] {len(followups)} follow-ups generated")
    print(f"  JSON: {out_json}")
    print(f"  Markdown: {out_md}")
    by_version = {}
    for fu in followups:
        by_version[fu["version"]] = by_version.get(fu["version"], 0) + 1
    for v, c in sorted(by_version.items()):
        print(f"  Version {v}: {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
