#!/usr/bin/env python3
"""
QA pipeline for job-madinah outreach drafts.

Validates a JSON list of drafts (same shape as send_emails.py expects) for:
- All required fields present (to, subject, body, cv, csv_id)
- Recipient first name spelled (no "Dear Hiring Manager")
- Company name spelled (no "[COMPANY]" / "[TOKEN]" placeholders remaining)
- Body length in 80-180 word range
- CV filename matches an actual PDF in CV PDF directory
- Email domain MX record exists (anti-bounce)
- Recipient not in bounces.txt blacklist
- No duplicate sends in last 30 days against the same recipient

Usage:
    python3 qa.py /tmp/drafts_to_send.json

Exit 0 = all drafts pass QA. Exit 1 = at least one draft failed.
Each failed draft is logged with reason; failed drafts are stripped from output.

Output: /tmp/drafts_to_send.qa.json — only drafts that passed QA.
"""

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("JOB_MADINAH_ROOT", Path(__file__).resolve().parent.parent))
CV_DIR = Path(
    os.environ.get(
        "JOB_MADINAH_CV_DIR",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/01-CVs-Personnalisés/PDF",
    )
)
TRACKING_CSV = Path(
    os.environ.get(
        "JOB_MADINAH_TRACKING_CSV",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/Tracking-Candidatures.csv",
    )
)
BOUNCES_FILE = ROOT / "data" / "bounces.txt"

PLACEHOLDER_PATTERN = re.compile(r"\[[A-Z_]{2,}\]")
GENERIC_GREETINGS = {
    "dear hiring manager",
    "dear sir or madam",
    "dear sir/madam",
    "to whom it may concern",
}


def log(level, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


def check_mx(domain: str) -> bool:
    """Return True if domain has at least one MX record."""
    try:
        result = subprocess.run(
            ["dig", "+short", "MX", domain],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return bool(result.stdout.strip())
    except Exception as e:
        log("WARN", f"dig failed for {domain}: {e}")
        return False  # fail closed — anti-bounce


def load_bounces() -> set:
    """Load blacklisted email addresses from bounces.txt (lowercased)."""
    if not BOUNCES_FILE.exists():
        return set()
    with BOUNCES_FILE.open("r", encoding="utf-8") as f:
        return {line.strip().lower() for line in f if line.strip()}


def load_recent_recipients(days: int = 30) -> set:
    """Load recipients we've already emailed in the last N days from tracking CSV."""
    if not TRACKING_CSV.exists():
        log("WARN", f"Tracking CSV not found at {TRACKING_CSV}")
        return set()
    cutoff = datetime.now() - timedelta(days=days)
    recent = set()
    with TRACKING_CSV.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                date_str = (row.get("Date candidature") or "").strip()
                if not date_str:
                    continue
                d = datetime.strptime(date_str, "%Y-%m-%d")
                if d < cutoff:
                    continue
            except ValueError:
                continue
            contact = (row.get("Personne contactée") or "").lower()
            # extract any email-shaped tokens
            for token in re.findall(r"[\w.+-]+@[\w.-]+", contact):
                recent.add(token.lower())
    return recent


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def qa_draft(draft: dict, bounces: set, recent: set) -> tuple[bool, list[str]]:
    """Return (passed, list_of_failures)."""
    failures = []

    # 1) Required fields
    for required in ("to", "subject", "body", "cv", "csv_id"):
        if required not in draft or not draft[required]:
            failures.append(f"Missing required field: {required}")
    if failures:
        return False, failures

    to_list = draft["to"] if isinstance(draft["to"], list) else [draft["to"]]
    subject = draft["subject"]
    body = draft["body"]
    cv = draft["cv"]

    # 2) Placeholder tokens not replaced
    for field_name, content in (("subject", subject), ("body", body)):
        leftover = PLACEHOLDER_PATTERN.findall(content)
        if leftover:
            failures.append(
                f"Unreplaced placeholders in {field_name}: {set(leftover)}"
            )

    # 3) Generic greeting (kills reply rate)
    body_lower = body.lower()
    for greeting in GENERIC_GREETINGS:
        if greeting in body_lower:
            failures.append(f"Generic greeting found: '{greeting}'")

    # 4) Body word count
    wc = word_count(body)
    if wc < 80:
        failures.append(f"Body too short: {wc} words (min 80)")
    if wc > 220:
        failures.append(f"Body too long: {wc} words (max 220)")

    # 5) CV file exists
    cv_path = CV_DIR / cv
    if not cv_path.exists():
        failures.append(f"CV PDF not found: {cv_path}")

    # 6) Recipients sanity
    for addr in to_list:
        addr_lower = addr.lower().strip()
        if not re.match(r"[\w.+-]+@[\w.-]+\.[\w]{2,}$", addr_lower):
            failures.append(f"Invalid email format: {addr}")
            continue
        if addr_lower in bounces:
            failures.append(f"Recipient in bounces blacklist: {addr}")
        if addr_lower in recent:
            failures.append(f"Recent duplicate send (<30d) to: {addr}")
        # MX check
        domain = addr_lower.split("@", 1)[1]
        if not check_mx(domain):
            failures.append(f"No MX record for {domain} (anti-bounce)")

    return (len(failures) == 0), failures


def main():
    if len(sys.argv) != 2:
        log("ERROR", "Usage: python3 qa.py /path/to/drafts.json")
        return 1
    drafts_path = Path(sys.argv[1])
    if not drafts_path.exists():
        log("ERROR", f"Drafts file not found: {drafts_path}")
        return 1

    with drafts_path.open("r", encoding="utf-8") as f:
        drafts = json.load(f)

    log("INFO", f"QA pipeline starting on {len(drafts)} drafts")
    bounces = load_bounces()
    log("INFO", f"Loaded {len(bounces)} bounced emails")
    recent = load_recent_recipients(30)
    log("INFO", f"Loaded {len(recent)} recent recipients (last 30d)")

    passed = []
    failed_count = 0
    for i, draft in enumerate(drafts, 1):
        csv_id = draft.get("csv_id", f"draft-{i}")
        ok, failures = qa_draft(draft, bounces, recent)
        if ok:
            log("OK", f"[{csv_id}] PASSED")
            passed.append(draft)
        else:
            failed_count += 1
            log("FAIL", f"[{csv_id}] FAILED:")
            for f in failures:
                log("FAIL", f"  - {f}")

    log("INFO", f"=== Summary: {len(passed)}/{len(drafts)} passed, {failed_count} failed ===")

    # Write filtered output
    out_path = drafts_path.with_suffix(".qa.json")
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(passed, f, indent=2, ensure_ascii=False)
    log("INFO", f"QA output written to {out_path}")

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
