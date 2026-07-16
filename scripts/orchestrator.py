#!/usr/bin/env python3
"""
Orchestrator — daily sending pipeline for job-madinah outreach.

Pipeline:
1) Load data/companies.csv → select today's batch (priority=1, validation_status in {MX_VALID, PORTAL_ONLY},
   not already sent in data/sent_history.csv, capped at JOB_MADINAH_DAILY_CAP).
2) For each company:
   - Build persona target (CEO/Founder, HR Director, Hiring Manager) based on heuristics.
   - Generate draft (subject + body) from EN templates (CEO/HR/Hiring).
   - Pick CV PDF (Hospitality if sector contains hotel/hospitality/hajj/umrah/travel,
     otherwise Generic Senior Marketing).
3) Run QA pipeline (anti-bounce, anti-typo, anti-generic) on drafts that have a real email.
4) For PORTAL_ONLY companies → write to data/portal_queue.csv (manual application required).
5) For valid-email drafts that PASSED QA → send via Gmail SMTP (smtp.gmail.com:587 STARTTLS).
6) Append to data/sent_history.csv + data/sent_log.csv.

Usage:
  python3 scripts/orchestrator.py            # full run (sends emails)
  python3 scripts/orchestrator.py --dry-run  # render up to 5 mails, NO SEND

Env vars:
- GMAIL_USER (sender)
- GMAIL_APP_PASSWORD (Gmail app password)
- JOB_MADINAH_DAILY_CAP (default 17, warmup window 15-20)
- JOB_MADINAH_CV_DIR (absolute path to CV PDF dir; optional in CI)
"""

import argparse
import csv
import json
import os
import re
import smtplib
import socket

# Hard global network timeout — a hanging SMTP/DNS peer must never freeze the whole run
# (2026-07-09: scheduled run hung >15min and was killed by the job timeout).
socket.setdefaulttimeout(60)
import subprocess
import sys
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


ROOT = Path(os.environ.get("JOB_MADINAH_ROOT", Path(__file__).resolve().parent.parent))
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
COMPANIES_CSV = DATA_DIR / "companies.csv"
SENT_HISTORY = DATA_DIR / "sent_history.csv"
SENT_LOG = DATA_DIR / "sent_log.csv"
PORTAL_QUEUE = DATA_DIR / "portal_queue.csv"
BOUNCES_FILE = DATA_DIR / "bounces.txt"

CV_DIR = Path(
    os.environ.get(
        "JOB_MADINAH_CV_DIR",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/01-CVs-Personnalisés/PDF",
    )
)
CV_DEFAULT = "CV-08-Generic-Senior-Marketing.pdf"
CV_HOSPITALITY = "CV-03-Hospitality.pdf"

GMAIL_USER = os.environ.get("GMAIL_USER", "nuredinmohamedali@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
# Optional custom SMTP (Hostinger fallback when Gmail 2FA SMS blocks app password)
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", GMAIL_USER)
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", GMAIL_APP_PASSWORD)
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0") == "1"
DAILY_CAP = int(os.environ.get("JOB_MADINAH_DAILY_CAP", "17"))

SENDABLE_STATUSES = {"MX_VALID"}
PORTAL_STATUSES = {"PORTAL_ONLY"}

HOSPITALITY_HINTS = (
    "hotel",
    "hospitality",
    "hajj",
    "umrah",
    "travel",
    "ota",
    "aviation",
    "tourism",
)


# ---------- Templates ----------

SUBJECT_TPL = "Senior Digital Marketing Manager — interest in {company}"

TEMPLATE_HR = """Dear {first_name},

I am Nuredin Mohamed Ali, a Senior Digital Marketing Manager with 10+ years of experience across hospitality, e-commerce and Vision 2030-aligned brands. I came across {company} while mapping marketing teams across Saudi Arabia, and the trajectory of the organisation stood out.

What I bring:
- Multi-million euro media plans across Meta, Google, TikTok and programmatic
- Full-funnel team leadership (brand, performance, CRM, content)
- Native Arabic and French speaker (English C1) — rare for a European-trained marketer

Could we open a 15-minute conversation in the coming weeks to explore whether my profile fits a current or upcoming Senior Marketing role on your team?

I have attached my CV and would be happy to provide references on request.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""

TEMPLATE_HIRING = """Dear {first_name},

I am writing to express strong interest in joining the marketing team at {company} as a Senior Digital Marketing Manager / Director.

In my last roles I led 360 acquisition and brand programs combining performance media, content, CRM and creative production, with measurable impact on revenue and LTV. I am now relocating to Saudi Arabia (ready within 3 months) and looking specifically for senior marketing leadership opportunities aligned with Vision 2030.

I would value a 15-minute exchange to share how my profile could plug into your roadmap.

CV attached. Happy to share portfolio links and references on request.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""

TEMPLATE_CEO = """Dear {first_name},

I am Nuredin Mohamed Ali, Senior Digital Marketing Manager with 10+ years building and leading marketing organisations across Europe and MENA. I am writing directly because I have been following {company} and would like to be considered for a senior marketing leadership role on your team.

In short: full-funnel ownership, multi-million budgets, team building, and a strong cultural fit for Saudi Arabia — I am a native Arabic and French speaker (English C1) and operate confidently in multicultural environments.

Could we book a 15-minute introduction call in the coming weeks? I am happy to share concrete case studies that match your context.

CV attached.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""


def log(level: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


# ---------- Persona / template selection ----------

CEO_HINTS = ("founder", "ceo", "owner", "managing director", "general manager")
HR_HINTS = ("hr", "people", "talent", "recruit", "careers", "career")


def pick_template(email: str) -> tuple[str, str]:
    """Return (persona_label, template_text) based on the recipient email handle."""
    handle = (email.split("@", 1)[0] or "").lower() if email else ""
    if any(h in handle for h in CEO_HINTS):
        return "ceo_founder", TEMPLATE_CEO
    if any(h in handle for h in HR_HINTS):
        return "hr_director", TEMPLATE_HR
    return "hiring_manager", TEMPLATE_HIRING


def first_name_from_email(email: str) -> str:
    """Cheap heuristic: 'careers@x' → 'Hiring Team'; 'firstname.lastname@x' → 'Firstname'."""
    if not email or "@" not in email:
        return "Hiring Team"
    handle = email.split("@", 1)[0]
    if handle.lower() in {"careers", "career", "hr", "jobs", "info", "contact", "recruitment"}:
        return "Hiring Team"
    # split on common separators
    parts = re.split(r"[._\-+]", handle)
    if not parts or not parts[0]:
        return "Hiring Team"
    first = parts[0].strip()
    if not first or any(ch.isdigit() for ch in first):
        return "Hiring Team"
    return first.capitalize()


def pick_cv(sector: str) -> str:
    s = (sector or "").lower()
    if any(h in s for h in HOSPITALITY_HINTS):
        return CV_HOSPITALITY
    return CV_DEFAULT


# ---------- Sent history ----------

SENT_HISTORY_HEADERS = ["date", "company", "email", "persona", "cv", "subject", "status"]
SENT_LOG_HEADERS = ["timestamp", "company", "email", "persona", "result", "details"]
PORTAL_QUEUE_HEADERS = ["date", "company", "sector", "portal_url", "status", "notes"]


def load_already_sent() -> set:
    """Return set of company names already in sent_history.csv."""
    if not SENT_HISTORY.exists():
        return set()
    sent = set()
    with SENT_HISTORY.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n = (row.get("company") or "").strip()
            if n:
                sent.add(n)
    return sent


def ensure_csv_with_headers(path: Path, headers: list[str]) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)


def append_row(path: Path, headers: list[str], row: dict) -> None:
    ensure_csv_with_headers(path, headers)
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow({k: row.get(k, "") for k in headers})


# ---------- Companies loading + selection ----------


def load_companies() -> list[dict]:
    if not COMPANIES_CSV.exists():
        log("ERROR", f"Companies CSV not found: {COMPANIES_CSV}")
        return []
    with COMPANIES_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def select_today_batch(companies: list[dict], already_sent: set, cap: int) -> tuple[list[dict], list[dict]]:
    """Return (sendable, portal_only) lists for today's run, both already capped."""
    sendable, portal_only = [], []
    for row in companies:
        try:
            priority = int((row.get("priority") or "0").strip())
        except ValueError:
            priority = 0
        if priority != 1:
            continue
        name = (row.get("name") or "").strip()
        if not name or name in already_sent:
            continue
        status = (row.get("validation_status") or "").strip().upper()
        if status in SENDABLE_STATUSES and (row.get("email") or "").strip():
            sendable.append(row)
        elif status in PORTAL_STATUSES:
            portal_only.append(row)
    # Cap the daily batch on the SENDABLE side first; portal_only is observational.
    return sendable[:cap], portal_only[:cap]


# ---------- Draft building ----------




GULF_MARKERS = ("country:uae", "country:qatar", "country:kuwait", "country:bahrain",
                "country:oman", "country:gulf", "dubai", "abu dhabi", "doha",
                "kuwait", "manama", "muscat", "sharjah")


def adapt_for_gulf(body: str, company_row: dict) -> str:
    """Non-KSA Gulf targets must not get KSA-specific wording (Vision 2030, relocating to Saudi)."""
    blob = ((company_row.get("notes") or "") + " " + (company_row.get("city") or "")).lower()
    if not any(m in blob for m in GULF_MARKERS):
        return body
    return (body
            .replace("across Saudi Arabia", "across the Gulf")
            .replace("relocating to Saudi Arabia", "relocating to the Gulf")
            .replace("a strong cultural fit for Saudi Arabia", "a strong cultural fit for the Gulf")
            .replace("aligned with Vision 2030", "in the region's fast-growing market")
            .replace("Vision 2030-aligned brands", "high-growth Gulf brands"))

def build_draft(company_row: dict) -> dict:
    name = (company_row.get("name") or "").strip()
    sector = (company_row.get("sector") or "").strip()
    email = (company_row.get("email") or "").strip()
    persona, template = pick_template(email)
    first_name = first_name_from_email(email)
    body = template.format(first_name=first_name, company=name)
    body = adapt_for_gulf(body, company_row)
    cv = pick_cv(sector)
    return {
        "csv_id": name,
        "to": email,
        "subject": SUBJECT_TPL.format(company=name),
        "body": body,
        "cv": cv,
        "persona": persona,
        "sector": sector,
        "company": name,
        "portal_url": (company_row.get("source") or "").strip(),
    }


# ---------- Sending ----------


def send_email(draft: dict) -> tuple[bool, str]:
    """Send one draft via SMTP. Defaults to Gmail STARTTLS; supports Hostinger SSL via env."""
    if not SMTP_PASSWORD:
        return False, "SMTP_PASSWORD/GMAIL_APP_PASSWORD not set"
    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = draft["to"]
    msg["Subject"] = draft["subject"]
    msg["Reply-To"] = os.environ.get("REPLY_TO_ADDRESS", "nuredinmohamedali@gmail.com")
    msg.attach(MIMEText(draft["body"], "plain", "utf-8"))

    cv_path = CV_DIR / draft["cv"]
    if cv_path.exists():
        with cv_path.open("rb") as f:
            part = MIMEApplication(f.read(), Name=draft["cv"])
        part["Content-Disposition"] = f'attachment; filename="{draft["cv"]}"'
        msg.attach(part)
    else:
        log("WARN", f"CV not found at {cv_path} — sending without attachment")

    try:
        if SMTP_USE_SSL:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
        return True, "sent"
    except Exception as e:  # noqa: BLE001
        return False, f"smtp_error: {e}"


# ---------- QA invocation ----------


def run_qa(drafts_json: Path) -> Path:
    """Run scripts/qa.py against drafts and return path of the .qa.json output."""
    qa_script = ROOT / "scripts" / "qa.py"
    try:
        subprocess.run(
            ["python3", str(qa_script), str(drafts_json)],
            check=False,
            timeout=180,
        )
    except Exception as e:  # noqa: BLE001
        log("WARN", f"QA pipeline raised: {e}")
    return drafts_json.with_suffix(".qa.json")


# ---------- Main ----------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Render up to 5 mails, no send")
    args = parser.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    companies = load_companies()
    if not companies:
        log("ERROR", "No companies loaded — abort")
        return 1
    log("INFO", f"Loaded {len(companies)} companies")

    already_sent = load_already_sent()
    log("INFO", f"Already sent in history: {len(already_sent)} companies")

    cap = 5 if args.dry_run else DAILY_CAP
    sendable, portal_only = select_today_batch(companies, already_sent, cap)
    log("INFO", f"Today batch: {len(sendable)} sendable, {len(portal_only)} portal-only")

    # 1) Build drafts for sendable batch
    drafts = [build_draft(row) for row in sendable]

    # 2) Write drafts JSON + run QA
    drafts_json = Path("/tmp/drafts_to_send.json")
    with drafts_json.open("w", encoding="utf-8") as f:
        json.dump(drafts, f, indent=2, ensure_ascii=False)
    qa_out = run_qa(drafts_json)
    qa_drafts: list[dict] = []
    if qa_out.exists():
        try:
            qa_drafts = json.loads(qa_out.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log("WARN", f"Could not parse QA output: {e}")
            qa_drafts = []
    else:
        log("WARN", f"QA output missing at {qa_out}; treating all drafts as not-passed")
        qa_drafts = []

    log("INFO", f"QA passed: {len(qa_drafts)}/{len(drafts)}")

    # 3) Portal-only → manual queue
    today_str = datetime.now().strftime("%Y-%m-%d")
    for row in portal_only:
        append_row(
            PORTAL_QUEUE,
            PORTAL_QUEUE_HEADERS,
            {
                "date": today_str,
                "company": (row.get("name") or "").strip(),
                "sector": (row.get("sector") or "").strip(),
                "portal_url": (row.get("source") or "").strip(),
                "status": "manual_application_required",
                "notes": (row.get("notes") or "").strip()[:200],
            },
        )

    # 4) Send (or dry-run)
    if args.dry_run:
        out_dir = Path("/tmp/dry_run_drafts")
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, d in enumerate(drafts, 1):
            fp = out_dir / f"draft_{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', d['company'])}.eml.txt"
            fp.write_text(
                f"TO: {d['to']}\nSUBJECT: {d['subject']}\nCV: {d['cv']}\nPERSONA: {d['persona']}\n\n{d['body']}",
                encoding="utf-8",
            )
        log("OK", f"DRY-RUN rendered {len(drafts)} mails into {out_dir}, NO SEND.")
        return 0

    sent_ok = 0
    sent_fail = 0
    for d in qa_drafts:
        ok, details = send_email(d)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        append_row(
            SENT_LOG,
            SENT_LOG_HEADERS,
            {
                "timestamp": now,
                "company": d.get("company", ""),
                "email": d.get("to", ""),
                "persona": d.get("persona", ""),
                "result": "ok" if ok else "fail",
                "details": details,
            },
        )
        if ok:
            sent_ok += 1
            append_row(
                SENT_HISTORY,
                SENT_HISTORY_HEADERS,
                {
                    "date": today_str,
                    "company": d.get("company", ""),
                    "email": d.get("to", ""),
                    "persona": d.get("persona", ""),
                    "cv": d.get("cv", ""),
                    "subject": d.get("subject", ""),
                    "status": "sent",
                },
            )
        else:
            sent_fail += 1
            log("FAIL", f"{d.get('company')}: {details}")

    log("INFO", f"=== Done: {sent_ok} sent, {sent_fail} failed, {len(portal_only)} portal-only queued ===")
    return 0 if sent_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
