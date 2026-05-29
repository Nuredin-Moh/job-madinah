#!/usr/bin/env python3
"""
Follow-up scheduler — reads tracking CSV, identifies candidates due for follow-up,
generates draft texts ready to copy into Gmail.

Triggers used:
- J+7 from initial send → Version A (simple bump)
- J+14 → Version B (value-add)
- J+21 → Version C (graceful goodbye)

Skip if status in: Refus, Hired, BOUNCED, STOP, or Date prochaine relance is empty.

Output: writes /tmp/followups_to_send.json + a markdown drafts file.

Run via GitHub Actions cron 8:00 UTC daily.
"""

import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


TRACKING_CSV = Path(
    os.environ.get(
        "JOB_MADINAH_TRACKING_CSV",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/Tracking-Candidatures.csv",
    )
)
OUTPUT_DIR = Path("/tmp")

SKIP_STATUSES = {
    "Refus",
    "Hired",
    "Embauche",
    "BOUNCED - email invalide",
    "BOUNCED probable - à vérifier",
    "STOP",
    "Stopped",
    "SKIP - profil 404 LinkedIn",
    "SKIP - page entreprise pas profil individuel",
}


VERSION_A = """{greeting}

Just a quick note to surface my message from {original_date} in case it had been missed.

I am still very interested in joining {company} and would value a brief 15-min conversation when your schedule allows.

Happy to share additional materials, references, or a short intro video if useful.

Best regards,
Nuredin Mohamed Ali
+212 626 012 886 | linkedin.com/in/nuredinmohamedali
"""

VERSION_B = """{greeting}

Following up on my note from {original_date}.

Should you reconsider opening conversations for Senior Marketing roles at {company}, I remain very interested and available — happy to share a short loom walking through a Vision 2030-aligned acquisition plan tailored to your team.

Best regards,
Nuredin Mohamed Ali
+212 626 012 886 | linkedin.com/in/nuredinmohamedali
"""

VERSION_C = """{greeting}

This is my last note on this thread — I will respect your time.

{company} remains high on my shortlist, and I would welcome the chance to reconnect whenever the timing makes sense. If a different team or division might be a better fit, I would be grateful for an introduction.

Wishing you continued success.

Best regards,
Nuredin Mohamed Ali
"""


def days_between(date_str: str) -> int:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return (datetime.now() - d).days
    except ValueError:
        return -1


def extract_first_name(contact: str) -> str:
    """Return contact first name, or empty string. Never 'Hiring Manager'."""
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
    """Personalised greeting — never 'Dear Hiring Manager'."""
    first = extract_first_name(contact)
    if first:
        return f"Dear {first},"
    company = (company or "").strip()
    if company:
        return f"Dear {company} Team,"
    return "Dear Marketing Team,"


def main():
    if not TRACKING_CSV.exists():
        print(f"[ERROR] Tracking CSV not found: {TRACKING_CSV}", file=sys.stderr)
        return 1

    today_str = datetime.now().strftime("%Y-%m-%d")
    today_date = datetime.now().date()

    followups = []
    with TRACKING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            statut = (row.get("Statut") or "").strip()
            if any(skip in statut for skip in SKIP_STATUSES):
                continue

            date_str = (row.get("Date candidature") or "").strip()
            if not date_str:
                continue
            try:
                d_init = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue

            days_since = (today_date - d_init).days
            if days_since < 7:
                continue
            if days_since > 25:
                continue  # past J+21 + buffer, stop

            # Pick template version
            if 7 <= days_since <= 9:
                version = "A"
                template = VERSION_A
            elif 13 <= days_since <= 16:
                version = "B"
                template = VERSION_B
            elif 20 <= days_since <= 22:
                version = "C"
                template = VERSION_C
            else:
                continue

            company = (row.get("Entreprise") or "").strip()
            poste = (row.get("Poste") or "").strip()
            contact = (row.get("Personne contactée") or "").strip()
            first_name = extract_first_name(contact)
            greeting = build_greeting(contact, company)

            body = template.format(
                greeting=greeting,
                company=company,
                original_date=d_init.strftime("%B %d"),
            )

            followups.append(
                {
                    "csv_id": row.get("ID"),
                    "version": version,
                    "company": company,
                    "poste": poste,
                    "contact": contact,
                    "first_name": first_name,
                    "original_date": date_str,
                    "days_since": days_since,
                    "subject": f"Re: Senior Digital Marketing Manager — {company}",
                    "body": body,
                }
            )

    # Write JSON
    out_json = OUTPUT_DIR / "followups_to_send.json"
    with out_json.open("w", encoding="utf-8") as f:
        json.dump(followups, f, indent=2, ensure_ascii=False)

    # Write markdown
    out_md = OUTPUT_DIR / f"followups_{today_str}.md"
    with out_md.open("w", encoding="utf-8") as f:
        f.write(f"# Follow-ups due {today_str}\n\n")
        f.write(f"Total: {len(followups)} contacts\n\n")
        f.write("---\n\n")
        for fu in followups:
            f.write(f"## [{fu['csv_id']}] {fu['company']} — Version {fu['version']} (J+{fu['days_since']})\n\n")
            f.write(f"- Contact: {fu['contact']}\n")
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
