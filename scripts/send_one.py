#!/usr/bin/env python3
"""Envoie UN mail cible (reponse chaude, relance nominative) via le meme canal
SMTP + CV que le pipeline quotidien, en dehors du batch automatique.

Cas d'usage : une entreprise repond a un cold email en redirigeant vers une
autre adresse (RH, recrutement). Le batch generique ne convient pas — il faut
un mail qui fait reference a leur reponse. On l'ecrit a la main dans un JSON
et on l'envoie avec les secrets du repo (qui ne vivent que dans GitHub).

Usage (GitHub Actions, workflow send-one.yml) :
    python3 scripts/send_one.py --json '<JSON>'

JSON attendu :
    {"to": "...", "subject": "...", "body": "...", "cv": "CV-08-Generic-Senior-Marketing-Gulf.pdf",
     "company": "Kuwait Hospital", "persona": "hr_director"}

Le mail est journalise dans data/sent_history.csv et data/sent_log.csv comme
un envoi normal, donc dedup et rapports le voient.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import orchestrator as o  # noqa: E402

REQUIRED = ("to", "subject", "body", "cv", "company")


def append_csv(path, headers, row):
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=headers)
        if not exists:
            w.writeheader()
        w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", required=True, help="draft as JSON string")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    draft = json.loads(args.json)
    missing = [k for k in REQUIRED if not draft.get(k)]
    if missing:
        o.log("ERROR", f"missing fields: {missing}")
        return 2
    draft.setdefault("persona", "manual")

    cv_path = o.CV_DIR / draft["cv"]
    if not cv_path.exists():
        o.log("ERROR", f"CV not found: {cv_path} — refusing to send without attachment")
        return 2

    # Garde-fou : jamais deux fois la meme adresse
    already = set()
    if o.SENT_HISTORY.exists():
        for r in csv.DictReader(o.SENT_HISTORY.open(encoding="utf-8")):
            already.add((r.get("email") or "").strip().lower())
    if draft["to"].strip().lower() in already:
        o.log("ERROR", f"{draft['to']} already in sent_history — refusing duplicate")
        return 3

    o.log("INFO", f"send_one -> {draft['to']} | {draft['subject']} | cv={draft['cv']}")
    if args.dry_run:
        print(draft["body"])
        return 0

    ok, detail = o.send_email(draft)
    today = date.today().isoformat()
    append_csv(o.SENT_HISTORY, o.SENT_HISTORY_HEADERS, {
        "date": today, "company": draft["company"], "email": draft["to"],
        "persona": draft["persona"], "cv": draft["cv"], "subject": draft["subject"],
        "status": "sent" if ok else "failed",
    })
    append_csv(o.SENT_LOG, o.SENT_LOG_HEADERS, {
        "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
        "company": draft["company"], "email": draft["to"], "persona": draft["persona"],
        "result": "OK" if ok else "FAIL", "details": detail,
    })
    o.log("OK" if ok else "ERROR", f"{draft['company']}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
