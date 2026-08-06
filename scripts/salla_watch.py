#!/usr/bin/env python3
"""Veille mensuelle des offres Salla (jobs.salla.com) dans le domaine de Nuredin.

Compare les offres actuelles a l'etat memorise (data/salla_seen.json) et
envoie un email a Nuredin uniquement s'il y a du nouveau dans son domaine.

Filtrage :
  - GARDE   : marketing digital / performance / CRM / lifecycle / growth / brand / e-commerce
  - IGNORE  : technique, produit, design, finance, RH, vente pure
  - IGNORE  : programmes Tamheer (reserves aux nationaux saoudiens)
"""

import json
import os
import re
import smtplib
import socket
import sys
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

socket.setdefaulttimeout(60)

JOBS_URL = "https://jobs.salla.com/"
API_URL = "https://apply.workable.com/api/v1/widget/accounts/salla?details=true"
STATE = Path(__file__).resolve().parent.parent / "data" / "salla_seen.json"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
RECIPIENT = os.environ.get("REPORT_RECIPIENT", "nuredinmohamedali@gmail.com")

# Un titre doit contenir un de ces mots pour etre retenu.
KEEP = re.compile(
    r"marketing|crm|lifecycle|growth|brand|campaign|acquisition|retention|"
    r"seo|sem|paid|performance|content|social|communication|e-?commerce|"
    r"digital marketing",
    re.I,
)
# ... sauf s'il contient un de ceux-ci (faux positifs / hors perimetre).
DROP = re.compile(
    r"tamheer|engineer|developer|backend|frontend|devops|sre|mlops|"
    r"data scientist|data analyst|designer|design |ui |ux |product manager|"
    r"security|finance|financial|accountant|recruit|human resource|"
    r"sales manager|sales executive|onboarding specialist|intern\b",
    re.I,
)


def fetch_jobs():
    """Retourne les offres publiees via l'API publique Workable de Salla."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Mozilla/5.0"})
    data = json.loads(urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "ignore"))
    jobs = []
    for j in data.get("jobs", []):
        loc = ", ".join(
            x for x in (j.get("city"), j.get("country")) if x
        ) or j.get("location", "")
        jobs.append(
            {
                "id": j.get("shortcode") or j.get("url", ""),
                "url": j.get("url") or j.get("shortlink", ""),
                "title": (j.get("title") or "").strip(),
                "dept": (j.get("department") or "").strip(),
                "loc": loc,
                "text": f"{j.get('title','')} | {j.get('department','')} | {loc}",
            }
        )
    return jobs


def relevant(job):
    """Retenu si le TITRE matche le domaine et n'est pas exclu."""
    title = job["title"]
    return bool(KEEP.search(title)) and not DROP.search(title)


def load_seen():
    if STATE.exists():
        try:
            return set(json.loads(STATE.read_text(encoding="utf-8")))
        except Exception:
            return set()
    return set()


def save_seen(ids):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(sorted(ids), indent=1), encoding="utf-8")


def send(subject, body):
    if not SMTP_PASSWORD:
        print("[INFO] SMTP non configure - email ignore")
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = SMTP_FROM
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo()
        s.starttls()
        s.ehlo()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
    print(f"[OK] email envoye a {RECIPIENT}")


def main():
    try:
        jobs = fetch_jobs()
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] impossible de lire {JOBS_URL}: {e}", file=sys.stderr)
        return 0

    if not jobs:
        print("[WARN] aucune offre extraite - structure de page changee ?", file=sys.stderr)
        return 0

    keep = [j for j in jobs if relevant(j)]
    seen = load_seen()
    new = [j for j in keep if j["id"] not in seen]

    print(f"[INFO] {len(jobs)} offres, {len(keep)} dans le domaine, {len(new)} nouvelles")

    if new:
        lines = [
            f"{len(new)} nouvelle(s) offre(s) Salla dans ton domaine :",
            "",
        ]
        for j in new:
            lines.append(f"  - {j['text']}")
            lines.append(f"    {j['url']}")
            lines.append("")
        lines.append(f"Toutes les offres : {JOBS_URL}#jobs")
        send(f"[Salla] {len(new)} nouvelle(s) offre(s) pour toi", "\n".join(lines))
    else:
        print("[INFO] rien de nouveau - pas d'email")

    # Memorise toutes les offres pertinentes vues (nouvelles incluses)
    save_seen(seen | {j["id"] for j in keep})
    return 0


if __name__ == "__main__":
    sys.exit(main())
