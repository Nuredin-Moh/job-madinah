#!/usr/bin/env python3
"""
Daily report — summarizes the job-madinah pipeline and emails it to Nuredin.

Reads the repo's committed data files, so it works on GitHub Actions without any
external CSV/gist dependency:
  - data/sent_history.csv        cold-email outreach (date, company, email, persona, cv, subject, status)
  - data/sent_log.csv            send attempts (timestamp, company, email, persona, result, details)
  - data/portal_applications.csv portal / Easy-Apply submissions (portal, job_title, ..., status, notes)
  - data/portal_queue.csv        portals requiring manual application (date, company, sector, portal_url, status, notes)

Sends via SMTP using the same configuration as orchestrator.py (SMTP_* secrets, with
GMAIL_* as fallback). If no SMTP password is set, prints the report to stdout.

Resilience: missing/empty data never hard-fails the job — it still produces a report and
exits 0, so the daily cron does not spam failure notifications. A non-zero exit is reserved
for a genuine SMTP send failure (a real problem worth surfacing).

Run via GitHub Actions cron 18:00 UTC daily (= 21:00 KSA).

Env vars:
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_FROM / SMTP_USE_SSL
  (or GMAIL_USER / GMAIL_APP_PASSWORD), REPORT_RECIPIENT
"""

import csv
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


ROOT = Path(os.environ.get("JOB_MADINAH_ROOT", Path(__file__).resolve().parent.parent))
DATA = ROOT / "data"

GMAIL_USER = os.environ.get("GMAIL_USER", "nuredinmohamedali@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
# SMTP config mirrors orchestrator.py: Gmail STARTTLS by default, Hostinger SSL via env.
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", GMAIL_USER)
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", GMAIL_APP_PASSWORD)
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0") == "1"
REPORT_RECIPIENT = os.environ.get("REPORT_RECIPIENT", "nuredinmohamedali@gmail.com")

TARGET_DAILY = int(os.environ.get("JOB_MADINAH_DAILY_CAP", "17"))


def read_csv(name):
    """Read data/<name> as a list of dicts; return [] if missing/unreadable."""
    path = DATA / name
    if not path.exists():
        print(f"[INFO] {path} not found — section skipped", file=sys.stderr)
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] could not read {path}: {e}", file=sys.stderr)
        return []


def date_only(value):
    """Normalize 2026-05-30 / 2026-05-30T19:23:00Z / '2026-05-30 18:17:28' -> '2026-05-30'."""
    s = (value or "").strip()
    if not s:
        return ""
    return s.replace("T", " ").split(" ")[0][:10]


def summarize():
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    cutoff_7d = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    sent = read_csv("sent_history.csv")
    companies = read_csv("companies.csv")
    sent_names = {(r.get("company") or "").strip().lower() for r in sent}
    queue_depth = sum(
        1 for r in companies
        if (r.get("validation_status") or "").strip() == "MX_VALID"
        and (r.get("name") or "").strip().lower() not in sent_names
    )
    log = read_csv("sent_log.csv")
    portal_apps = read_csv("portal_applications.csv")
    portal_queue = read_csv("portal_queue.csv")

    emails_today = sum(1 for r in sent if date_only(r.get("date")) == today)
    emails_yesterday = sum(1 for r in sent if date_only(r.get("date")) == yesterday)
    emails_7d = sum(1 for r in sent if date_only(r.get("date")) >= cutoff_7d)

    log_today = [r for r in log if date_only(r.get("timestamp")) == today]
    ok_today = sum(1 for r in log_today if (r.get("result") or "").strip().lower() == "ok")
    err_today = [r for r in log_today if (r.get("result") or "").strip().lower() not in ("ok", "")]

    portal_status = {}
    for r in portal_apps:
        st = (r.get("status") or "unknown").strip() or "unknown"
        portal_status[st] = portal_status.get(st, 0) + 1
    # Anything not cleanly submitted is actionable (blocked uploads, opened-but-not-submitted, etc.)
    portal_blocked = [
        r for r in portal_apps
        if "BLOCK" in (r.get("status") or "").upper()
        or "REQUIRED" in (r.get("status") or "").upper()
        or "OPENED" in (r.get("status") or "").upper()
    ]

    pending_manual = [
        r for r in portal_queue
        if (r.get("status") or "").strip().lower() not in ("done", "applied", "submitted", "")
    ]

    return {
        "today": today,
        "emails_total": len(sent),
        "emails_today": emails_today,
        "emails_yesterday": emails_yesterday,
        "emails_7d": emails_7d,
        "ok_today": ok_today,
        "err_today": err_today,
        "portal_total": len(portal_apps),
        "portal_status": portal_status,
        "portal_blocked": portal_blocked,
        "pending_manual": pending_manual,
        "queue_depth": queue_depth,
        "has_any_data": bool(sent or log or portal_apps or portal_queue),
    }


def render_text(s):
    L = []
    L.append(f"=== JOB MADINAH — Daily Report — {s['today']} ===")
    L.append("")

    if not s["has_any_data"]:
        L.append("No pipeline data found in data/ yet (sent_history.csv, portal_applications.csv...).")
        L.append("Nothing to report today.")
        L.append("")
        L.append("Generated by job-madinah/scripts/daily_report.py")
        return "\n".join(L)

    L.append(f"  Reserve de cibles restante: {s['queue_depth']}")
    if s["queue_depth"] < 40:
        L.append("  /!\\ RESERVE BASSE (<40) - ouvrir l'app Claude 2 min pour que la routine la recharge")
    L.append("")
    L.append("--- Cold-email outreach ---")
    L.append(f"  Total emails sent:   {s['emails_total']}")
    L.append(f"  Sent today:          {s['emails_today']}")
    L.append(f"  Sent yesterday:      {s['emails_yesterday']}")
    L.append(f"  Sent last 7 days:    {s['emails_7d']}")
    L.append(f"  Send results today:  {s['ok_today']} ok, {len(s['err_today'])} error(s)")
    if s["emails_today"] < TARGET_DAILY:
        L.append(f"  /!\\ Behind daily target ({s['emails_today']}/{TARGET_DAILY}). Catch up before EOD.")
    L.append("")

    if s["err_today"]:
        L.append("SEND ERRORS TODAY:")
        for r in s["err_today"][:15]:
            L.append(f"  {r.get('company')} <{r.get('email')}> — {r.get('result')}: {r.get('details')}")
        L.append("")

    L.append("--- Portal / Easy-Apply applications ---")
    L.append(f"  Total portal applications: {s['portal_total']}")
    for status, count in sorted(s["portal_status"].items(), key=lambda kv: -kv[1]):
        L.append(f"    {status:50} {count}")
    L.append("")

    if s["portal_blocked"]:
        L.append(f"PORTAL APPLICATIONS NEEDING MANUAL ACTION ({len(s['portal_blocked'])}):")
        for r in s["portal_blocked"][:20]:
            L.append(f"  {r.get('portal')} — {r.get('job_title')} — {r.get('status')}")
            if r.get("job_url"):
                L.append(f"      {r.get('job_url')}")
        L.append("")

    if s["pending_manual"]:
        L.append(f"PORTALS PENDING MANUAL APPLICATION ({len(s['pending_manual'])}):")
        for r in s["pending_manual"][:20]:
            L.append(f"  {r.get('company')} ({r.get('sector')}) — {r.get('portal_url')}")
        L.append("")

    L.append("--- Action items ---")
    L.append(f"- Keep cold-email volume at {TARGET_DAILY}/day")
    L.append("- Manually finish blocked portal applications (CV upload steps)")
    L.append("- Reply to any active threads within 24h")
    L.append("")
    L.append("Generated by job-madinah/scripts/daily_report.py")
    return "\n".join(L)


def send_report(body, subject):
    """Send via SMTP (SSL or STARTTLS). Print to stdout if no password configured.

    Returns 0 on success / stdout fallback, 1 on a real SMTP failure.
    """
    if not SMTP_PASSWORD:
        print("[INFO] No SMTP password set (SMTP_PASSWORD/GMAIL_APP_PASSWORD) — printing report:\n")
        print(body)
        return 0

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = REPORT_RECIPIENT
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

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
        print(f"[OK] Report sent to {REPORT_RECIPIENT}")
        return 0
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] SMTP send failed: {e}", file=sys.stderr)
        print(body)  # keep the content visible in the run log
        return 1


def main():
    summary = summarize()
    body = render_text(summary)
    subject = (
        f"[Job Madinah] Daily {summary['today']} — "
        f"{summary['emails_today']} emails, "
        f"{summary['portal_total']} portal apps"
    )
    return send_report(body, subject)


if __name__ == "__main__":
    sys.exit(main())
