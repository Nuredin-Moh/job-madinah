#!/usr/bin/env python3
"""
Orchestrator — daily sending pipeline for job-madinah outreach.

Pipeline:
1) Load data/companies.csv → every sendable row (priority 1 or 2, validation_status MX_VALID,
   email present, not already sent in data/sent_history.csv), priority 1 first.
2) For each company:
   - Build persona target (CEO/Founder, HR Director, Hiring Manager) based on heuristics.
   - Generate draft (subject + body) from EN templates (CEO/HR/Hiring).
   - Pick CV PDF (Hospitality if sector contains hotel/hospitality/hajj/umrah/travel,
     otherwise Generic Senior Marketing).
3) Run QA pipeline (anti-bounce, anti-typo, anti-generic) chunk by chunk, walking down the
   queue until JOB_MADINAH_DAILY_CAP drafts have PASSED: a rejected row never blocks the
   rows behind it (before 08.11.2026 only the first CAP rows were checked, and 17 rejected
   customer-service mailboxes froze the queue from 16.10 to 08.11). Rejected rows are
   recorded once in data/qa_rejected.csv (company, email, reasons).
4) For PORTAL_ONLY companies → write to data/portal_queue.csv (manual application required),
   once per company (before 08.11.2026 every run re-appended them: 4314 rows for 20 companies).
5) For valid-email drafts that PASSED QA → send via Gmail SMTP (smtp.gmail.com:587 STARTTLS).
6) Append to data/sent_history.csv + data/sent_log.csv.

Usage:
  python3 scripts/orchestrator.py            # full run (sends emails)
  python3 scripts/orchestrator.py --dry-run  # QA + render up to 5 mails (JOB_MADINAH_DRY_RUN_CAP),
                                             # NO SEND, no data file written

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
import time
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
QA_REJECTED = DATA_DIR / "qa_rejected.csv"
BOUNCES_FILE = DATA_DIR / "bounces.txt"

CV_DIR = Path(
    os.environ.get(
        "JOB_MADINAH_CV_DIR",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/01-CVs-Personnalisés/PDF",
    )
)
CV_DEFAULT = "CV-08-Generic-Senior-Marketing.pdf"
CV_HOSPITALITY = "CV-03-Hospitality.pdf"
# Variantes Golfe non-saoudien : meme contenu, ciblage geographique neutre.
# Sans elles, un mail adapte "across the Gulf" partait avec un CV "Madinah /
# Saudi Arabia" en piece jointe (incoherence visible par le recruteur).
CV_DEFAULT_GULF = "CV-08-Generic-Senior-Marketing-Gulf.pdf"
CV_HOSPITALITY_GULF = "CV-03-Hospitality-Gulf.pdf"

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
# Seuil d'alerte (en jours d'envoi restants) avant que la file ne soit vide.
QUEUE_WARN_DAYS = float(os.environ.get("JOB_MADINAH_QUEUE_WARN_DAYS", "3"))
# Nombre de brouillons rendus par --dry-run.
DRY_RUN_CAP = int(os.environ.get("JOB_MADINAH_DRY_RUN_CAP", "5"))
# Temps maximum passe a descendre la file en QA (le job GitHub coupe a 15 min).
QA_TIME_BUDGET_S = float(os.environ.get("JOB_MADINAH_QA_TIME_BUDGET_S", "480"))

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

I am Nuredin Mohamed Ali, a Senior Digital Marketing Manager with experience across hospitality, e-commerce and Vision 2030-aligned brands. I came across {company} while mapping marketing teams across Saudi Arabia, and the trajectory of the organisation stood out.

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

In my last roles I led 360 acquisition and brand programs combining performance media, content, CRM and creative production, with measurable impact on revenue and LTV. I am now relocating to Saudi Arabia (ready within 1 month) and looking specifically for senior marketing leadership opportunities aligned with Vision 2030.

I would value a 15-minute exchange to share how my profile could plug into your roadmap.

CV attached. Happy to share portfolio links and references on request.

Best regards,
Nuredin Mohamed Ali
+41 79 884 05 33 | linkedin.com/in/nuredinmohamedali
"""

TEMPLATE_CEO = """Dear {first_name},

I am Nuredin Mohamed Ali, Senior Digital Marketing Manager with experience building and leading marketing organisations across Europe and MENA. I am writing directly because I have been following {company} and would like to be considered for a senior marketing leadership role on your team.

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


# Mailbox words that are never a person's first name. A handle starting with one
# of them gets "Dear Hiring Team," (before 14.10.2026, ~250 of 1050 mails opened
# with "Dear Hello," / "Dear Customerservice," / "Dear Sales,").
GENERIC_HANDLES = {
    "careers", "career", "hr", "hrd", "jobs", "job", "info", "contact", "contactus",
    "recruitment", "recruitments", "recruit", "recruiting", "recruiter", "talent",
    "hiring", "hireme", "apply", "cv", "resume", "people", "join", "hello", "hi",
    "marketing", "sales", "customerservice", "customercare", "customer", "care",
    "support", "service", "services", "help", "admin", "office", "mail", "email",
    "enquiry", "enquiries", "inquiry", "inquiries", "crm", "pr", "media", "press",
    "communications", "comms", "corporate", "cs", "connect", "admission",
    "admissions", "reservations", "reservation", "booking", "bookings", "team",
    "general", "business", "partners", "partnership", "feedback", "webmaster",
    "noreply", "no", "saudi", "ksa", "uae", "riyadh", "jeddah", "dammam", "khobar",
    "dubai", "doha", "qatar", "kuwait", "bahrain", "oman", "muscat",
    "al", "el", "investor", "investors", "ir", "hra", "dao", "gulf", "group",
}


def first_name_from_email(email: str, company: str = "") -> str:
    """'firstname.lastname@x' → 'Firstname'; anything else → 'Hiring Team'.

    A single-word handle (hello@, sales@, mnagah@) is never trusted as a first
    name: only a separated handle whose first part is a plausible name is used.
    """
    if not email or "@" not in email:
        return "Hiring Team"
    handle = email.split("@", 1)[0].strip()
    parts = [p for p in re.split(r"[._\-+]", handle) if p]
    if len(parts) < 2:
        return "Hiring Team"
    first = parts[0]
    if (len(first) < 2 or not first.isalpha()
            or first.lower() in GENERIC_HANDLES
            or any(p.lower() in GENERIC_HANDLES for p in parts[1:2])):
        return "Hiring Team"
    # gloria.management@gloria-hotels.com : the "name" is the company's
    company_words = set(re.findall(r"[a-z]+", company.lower()))
    if first.lower() in company_words or first.lower() == "".join(re.findall(r"[a-z]+", company.lower())):
        return "Hiring Team"
    return first.capitalize()


def pick_cv(sector: str, company_row=None) -> str:
    """Choisit le CV par metier ET par pays.

    Le corps du mail est deja neutralise pour le Golfe non-saoudien par
    adapt_for_gulf(); la piece jointe doit suivre, sinon le CV contredit le mail.
    """
    s = (sector or "").lower()
    hospitality = any(h in s for h in HOSPITALITY_HINTS)
    if company_row is not None and is_gulf_non_ksa(company_row):
        return CV_HOSPITALITY_GULF if hospitality else CV_DEFAULT_GULF
    return CV_HOSPITALITY if hospitality else CV_DEFAULT


# ---------- Sent history ----------

SENT_HISTORY_HEADERS = ["date", "company", "email", "persona", "cv", "subject", "status"]
SENT_LOG_HEADERS = ["timestamp", "company", "email", "persona", "result", "details"]
PORTAL_QUEUE_HEADERS = ["date", "company", "sector", "portal_url", "status", "notes"]
QA_REJECTED_HEADERS = ["first_seen", "company", "email", "reasons"]


def load_keys(path: Path, *fields: str) -> set:
    """Set of lowercased tuples (or strings for one field) already present in a CSV."""
    if not path.exists():
        return set()
    keys = set()
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            vals = tuple((row.get(k) or "").strip().lower() for k in fields)
            keys.add(vals[0] if len(vals) == 1 else vals)
    return keys


MIN_DAILY_FOR_SKIP = int(os.environ.get("JOB_MADINAH_MIN_DAILY", "12"))


def count_sent_today() -> int:
    """Nombre de mails deja envoyes aujourd'hui (lu dans sent_history.csv)."""
    if not SENT_HISTORY.exists():
        return 0
    today = datetime.now().strftime("%Y-%m-%d")
    n = 0
    with SENT_HISTORY.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if (row.get("date") or "").strip()[:10] == today and \
               (row.get("status") or "").strip().lower() == "sent":
                n += 1
    return n


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


# La priorite ORDONNE la file, elle ne la filtre plus.
# Historique : trois fois (01.08, 12.08, 21.08.2026) un refill a ecrit des
# cibles valides en priority=2 alors que l'envoi n'acceptait que priority==1
# -> des dizaines de cibles echouees en silence et des jours a zero envoi.
# Desormais toute ligne MX_VALID avec un email part ; prio 1 d'abord.
SENDABLE_PRIORITIES = (1, 2)


def _priority(row) -> int:
    try:
        return int((row.get("priority") or "0").strip())
    except ValueError:
        return 0


def select_candidates(companies: list[dict], already_sent: set) -> tuple[list[dict], list[dict]]:
    """Return (sendable, portal_only) for today's run, NOT capped.

    sendable : every MX_VALID row with an email, never sent, priority 1 first
               (stable order inside each priority). The QA decides later which
               of them really go out.
    portal_only : one row per company.
    """
    sendable, portal_only, portal_names = [], [], set()
    for row in companies:
        priority = _priority(row)
        if priority not in SENDABLE_PRIORITIES:
            continue
        name = (row.get("name") or "").strip()
        if not name or name in already_sent:
            continue
        status = (row.get("validation_status") or "").strip().upper()
        if status in SENDABLE_STATUSES and (row.get("email") or "").strip():
            sendable.append(row)
        elif status in PORTAL_STATUSES and name.lower() not in portal_names:
            portal_names.add(name.lower())
            portal_only.append(row)
    # Prio 1 d'abord, prio 2 ensuite ; ordre stable a l'interieur de chaque groupe.
    sendable.sort(key=_priority)
    return sendable, portal_only


def log_queue_depth(n: int, cap: int, label: str = "sendable") -> None:
    # Alerte de profondeur de file : le 12.08.2026 la file s'est videe en
    # silence (11 envois le 11, 0 le 12) et personne ne l'a su avant coup.
    days_left = n / cap if cap else 0
    if n < cap:
        log("WARN", f"QUEUE EMPTY TODAY: only {n} {label} targets left "
                    f"(cap {cap}) — refill data/companies.csv NOW")
    elif days_left < QUEUE_WARN_DAYS:
        log("WARN", f"QUEUE LOW: {n} {label} targets left = "
                    f"{days_left:.1f} days at {cap}/day — refill soon")
    else:
        log("INFO", f"Queue depth: {n} {label} = {days_left:.1f} days")


def select_today_batch(companies: list[dict], already_sent: set, cap: int) -> tuple[list[dict], list[dict]]:
    """Return (sendable, portal_only) lists, both capped (kept for helper scripts).

    main() no longer sends this capped slice as-is: it walks down the whole
    queue with qa_until_cap(), so a rejected row cannot block the next ones.
    """
    sendable, portal_only = select_candidates(companies, already_sent)
    log_queue_depth(len(sendable), cap)
    return sendable[:cap], portal_only[:cap]


# ---------- Draft building ----------




# --- Determination du pays : par DEFAUT tout est traite comme Golfe NEUTRE. ---
# Le risque est asymetrique : un mail neutre a une entreprise saoudienne ne
# choque personne, alors qu'un mail "Vision 2030 / relocating to Saudi Arabia"
# avec un CV "Madinah" envoye a une entreprise emiratie est une faute visible.
# On ne bascule donc en mode Arabie que si on RECONNAIT positivement le pays.
# (21.08.2026 : "Gulf Craft / Umm Al Quwain" passait en mode Arabie faute de
# marqueur — la ville manquait simplement dans la liste.)
KSA_CITIES = (
    "riyadh", "riyad", "jeddah", "jedda", "dammam", "khobar", "al khobar",
    "dhahran", "jubail", "al jubail", "yanbu", "makkah", "mecca", "la mecque",
    "madinah", "medina", "medine", "al madinah", "taif", "al taif", "abha",
    "tabuk", "qassim", "buraydah", "hail", "najran", "jizan", "al ahsa",
    "hofuf", "khamis mushait", "neom", "diriyah", "qiddiya", "red sea",
)
KSA_MARKERS = ("country:saudi", "country:ksa", "saudi arabia", "ksa")

# Conserve pour compatibilite : marqueurs Golfe explicites (non-KSA).
GULF_MARKERS = ("country:uae", "country:qatar", "country:kuwait", "country:bahrain",
                "country:oman", "country:gulf", "dubai", "abu dhabi", "doha",
                "kuwait", "manama", "muscat", "sharjah")


def _blob(company_row) -> str:
    return ((company_row.get("notes") or "") + " "
            + (company_row.get("city") or "") + " "
            + (company_row.get("website") or "")).lower()


def is_ksa(company_row) -> bool:
    """True seulement si le pays Arabie Saoudite est POSITIVEMENT reconnu."""
    blob = _blob(company_row)
    if any(m in blob for m in GULF_MARKERS):
        return False          # un marqueur Golfe explicite l'emporte
    if (company_row.get("website") or "").lower().endswith(".sa"):
        return True
    if ".sa/" in blob or ".com.sa" in blob:
        return True
    # Maaden (Waad Al Shamal), HTMi (Jazan) : ville hors liste, mais adresse en .sa
    if (company_row.get("email") or "").strip().lower().endswith(".sa"):
        return True
    return any(c in blob for c in KSA_CITIES) or any(m in blob for m in KSA_MARKERS)


def is_gulf_non_ksa(company_row: dict) -> bool:
    """True si la cible n'est PAS identifiee comme saoudienne.

    Source unique pour le corps du mail (adapt_for_gulf) ET le CV joint
    (pick_cv) : les deux doivent toujours dire la meme chose. Defaut sur
    "Golfe neutre" — c'est le sens sur lequel une erreur ne coute rien.
    """
    return not is_ksa(company_row)


def adapt_for_gulf(body: str, company_row: dict) -> str:
    """Non-KSA Gulf targets must not get KSA-specific wording (Vision 2030, relocating to Saudi)."""
    if not is_gulf_non_ksa(company_row):
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
    first_name = first_name_from_email(email, name)
    body = template.format(first_name=first_name, company=name)
    body = adapt_for_gulf(body, company_row)
    cv = pick_cv(sector, company_row)
    return {
        "csv_id": name,
        "to": email,
        "subject": SUBJECT_TPL.format(company=name),
        "body": body,
        "cv": cv,
        "persona": persona,
        "sector": sector,
        "company": name,
        # Expose pour la QA : le corps ET la piece jointe doivent viser le meme pays.
        "gulf_non_ksa": is_gulf_non_ksa(company_row),
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
        # Recruiter-facing filename: clean, professional (never internal names like CV-08-Generic)
        display_name = "CV-Senior-Marketing-Nuredin-Mohamed-Ali.pdf"
        with cv_path.open("rb") as f:
            part = MIMEApplication(f.read(), Name=display_name)
        part["Content-Disposition"] = f'attachment; filename="{display_name}"'
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


def _read_json_list(path: Path) -> list:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as e:  # noqa: BLE001
        log("WARN", f"Could not parse {path}: {e}")
        return []


def _draft_key(d: dict) -> tuple:
    to = d.get("to")
    to = ",".join(to) if isinstance(to, list) else (to or "")
    return ((d.get("csv_id") or "").strip().lower(), to.strip().lower())


def qa_until_cap(candidates: list[dict], cap: int) -> tuple[list[dict], list[dict], int]:
    """Walk down the queue, QA chunk by chunk, until `cap` drafts have passed.

    Returns (passed[:cap], rejected, examined). `rejected` items are
    {"company", "to", "failures"}. A draft that fails QA is skipped and the
    next row is tried, so a bad row can never freeze the queue again.
    Before 08.11.2026 only the first `cap` rows were checked: 17 customer-service
    mailboxes at the head of the queue meant 0 send per run from 16.10 to 08.11.
    At most one draft per company passes (duplicate names in companies.csv).
    """
    passed, rejected = [], []
    passed_companies = set()
    examined = 0
    if cap <= 0 or not candidates:
        return passed, rejected, examined
    chunk = max(cap * 2, 10)
    start = time.monotonic()
    n_chunk = 0
    while len(passed) < cap and examined < len(candidates):
        if time.monotonic() - start > QA_TIME_BUDGET_S:
            log("WARN", f"QA time budget ({QA_TIME_BUDGET_S:.0f}s) reached after "
                        f"{examined} rows — stopping here, the rest waits for the next run")
            break
        n_chunk += 1
        batch = candidates[examined:examined + chunk]
        examined += len(batch)
        drafts = [build_draft(row) for row in batch]
        drafts_json = Path(f"/tmp/drafts_to_send_{n_chunk:02d}.json")
        with drafts_json.open("w", encoding="utf-8") as f:
            json.dump(drafts, f, indent=2, ensure_ascii=False)
        qa_out = run_qa(drafts_json)
        if not qa_out.exists():
            log("WARN", f"QA output missing at {qa_out}; treating this chunk as not-passed")
        ok_keys = {_draft_key(d) for d in _read_json_list(qa_out)}
        reasons = {_draft_key(r): r.get("failures") or []
                   for r in _read_json_list(drafts_json.with_suffix(".rejected.json"))}
        for d in drafts:
            k = _draft_key(d)
            if k in ok_keys:
                if d["company"].strip().lower() in passed_companies or len(passed) >= cap:
                    continue
                passed_companies.add(d["company"].strip().lower())
                passed.append(d)
            else:
                rejected.append({
                    "company": d.get("company", ""),
                    "to": d.get("to", ""),
                    "failures": reasons.get(k) or ["QA did not pass this draft (no reason returned)"],
                })
    return passed, rejected, examined


def record_qa_rejections(rejected: list[dict], today_str: str) -> int:
    """Append each rejected (company, email) once to data/qa_rejected.csv."""
    known = load_keys(QA_REJECTED, "company", "email")
    added = 0
    for r in rejected:
        key = ((r.get("company") or "").strip().lower(), (r.get("to") or "").strip().lower())
        if key in known:
            continue
        known.add(key)
        append_row(QA_REJECTED, QA_REJECTED_HEADERS, {
            "first_seen": today_str,
            "company": (r.get("company") or "").strip(),
            "email": (r.get("to") or "").strip(),
            "reasons": " ; ".join(r.get("failures") or [])[:500],
        })
        added += 1
    return added


def queue_portal_rows(portal_only: list[dict], today_str: str) -> int:
    """Append PORTAL_ONLY companies to portal_queue.csv only if not already queued.

    Before 08.11.2026 each run (3 per day) re-appended the same companies:
    4314 rows for 20 companies.
    """
    known = load_keys(PORTAL_QUEUE, "company")
    added = 0
    for row in portal_only:
        name = (row.get("name") or "").strip()
        if not name or name.lower() in known:
            continue
        known.add(name.lower())
        append_row(
            PORTAL_QUEUE,
            PORTAL_QUEUE_HEADERS,
            {
                "date": today_str,
                "company": name,
                "sector": (row.get("sector") or "").strip(),
                "portal_url": (row.get("source") or "").strip(),
                "status": "manual_application_required",
                "notes": (row.get("notes") or "").strip()[:200],
            },
        )
        added += 1
    return added


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

    # Garde-fou d'idempotence : le cron GitHub Actions est peu fiable (le run
    # du 27.08.2026 a demarre avec 11h de retard, celui du 28.08 pas du tout).
    # Un second cron de rattrapage tourne donc dans la journee ; il doit rester
    # SANS EFFET si le batch du jour est deja parti, sinon on enverrait 2x le
    # quota quotidien (risque de classement en spam).
    sent_today = count_sent_today()
    if not args.dry_run and sent_today >= MIN_DAILY_FOR_SKIP:
        log("INFO", f"Already {sent_today} emails sent today (>= {MIN_DAILY_FOR_SKIP}) — nothing to do")
        return 0
    if sent_today:
        log("INFO", f"{sent_today} emails already sent today — sending the remainder")

    cap = DRY_RUN_CAP if args.dry_run else max(0, DAILY_CAP - sent_today)
    candidates, portal_only = select_candidates(companies, already_sent)
    log_queue_depth(len(candidates), cap, "sendable (before QA)")
    log("INFO", f"Candidates: {len(candidates)} sendable before QA, {len(portal_only)} portal-only")

    # 1-2) Build drafts + QA, walking down the queue until `cap` drafts pass.
    qa_drafts, rejected, examined = qa_until_cap(candidates, cap)
    log("INFO", f"QA passed: {len(qa_drafts)} (cap {cap}) — {examined} rows examined, "
                f"{len(rejected)} rejected and skipped")
    for r in rejected:
        log("SKIP", f"[{r['company']}] {r['to']} — " + " ; ".join(r["failures"])[:300])
    if len(qa_drafts) < cap and examined >= len(candidates):
        log("WARN", f"REAL QUEUE EMPTY: only {len(qa_drafts)} rows pass QA out of "
                    f"{len(candidates)} candidates — refill data/companies.csv with real HR addresses")

    today_str = datetime.now().strftime("%Y-%m-%d")

    # 4) Dry-run : nothing is sent and no data file is written.
    if args.dry_run:
        out_dir = Path("/tmp/dry_run_drafts")
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, d in enumerate(qa_drafts, 1):
            fp = out_dir / f"draft_{i:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', d['company'])}.eml.txt"
            fp.write_text(
                f"TO: {d['to']}\nSUBJECT: {d['subject']}\nCV: {d['cv']}\nPERSONA: {d['persona']}\n\n{d['body']}",
                encoding="utf-8",
            )
        (out_dir / "qa_rejected.txt").write_text(
            "\n".join(f"{r['company']} | {r['to']} | {' ; '.join(r['failures'])}" for r in rejected) + "\n",
            encoding="utf-8",
        )
        log("OK", f"DRY-RUN rendered {len(qa_drafts)} QA-passed mails into {out_dir} "
                  f"({len(rejected)} rejected listed in qa_rejected.txt), NO SEND.")
        return 0

    # 3) Bookkeeping : rejected rows once in qa_rejected.csv, portals once in portal_queue.csv.
    n_rej = record_qa_rejections(rejected, today_str)
    n_portal = queue_portal_rows(portal_only, today_str)
    log("INFO", f"Recorded {n_rej} new QA rejection(s) in {QA_REJECTED.name}, "
                f"{n_portal} new portal(s) in {PORTAL_QUEUE.name}")

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

    log("INFO", f"=== Done: {sent_ok} sent, {sent_fail} failed, {len(rejected)} QA-rejected skipped, "
                f"{n_portal} new portal-only queued ===")
    return 0 if sent_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
