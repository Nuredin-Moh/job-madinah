#!/usr/bin/env python3
"""
Daily report — sends a summary of the job-madinah pipeline to Nuredin's Gmail.

Reads tracking CSV → counts statuses → renders markdown report → sends via SMTP or stdout.

Run via GitHub Actions cron 18:00 UTC daily.

Env vars expected:
- GMAIL_USER (sender, defaults to nuredinmohamedali@gmail.com)
- GMAIL_APP_PASSWORD (Gmail app password — store as GitHub secret)
- REPORT_RECIPIENT (defaults to nuredinmohamedali@gmail.com)
"""

import csv
import json
import os
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


TRACKING_CSV = Path(
    os.environ.get(
        "JOB_MADINAH_TRACKING_CSV",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/Tracking-Candidatures.csv",
    )
)
GMAIL_USER = os.environ.get("GMAIL_USER", "nuredinmohamedali@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
REPORT_RECIPIENT = os.environ.get("REPORT_RECIPIENT", "nuredinmohamedali@gmail.com")


def load_tracking():
    if not TRACKING_CSV.exists():
        print(f"[ERROR] Tracking CSV not found: {TRACKING_CSV}", file=sys.stderr)
        return []
    with TRACKING_CSV.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def summarize(rows):
    """Return dict of metrics."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    last_7d_cutoff = now - timedelta(days=7)

    status_counts = {}
    sent_today = 0
    sent_yesterday = 0
    sent_last_7d = 0
    pending_followups_today = []
    hot_responses = []
    interviews = []

    for row in rows:
        statut = (row.get("Statut") or "").strip()
        date_str = (row.get("Date candidature") or "").strip()
        next_followup = (row.get("Date prochaine relance") or "").strip()

        status_counts[statut] = status_counts.get(statut, 0) + 1

        # Volume metrics
        if date_str == today_str:
            sent_today += 1
        if date_str == yesterday:
            sent_yesterday += 1
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d")
            if d >= last_7d_cutoff:
                sent_last_7d += 1
        except ValueError:
            pass

        # Pending follow-ups due today or overdue
        if next_followup:
            try:
                d_followup = datetime.strptime(next_followup, "%Y-%m-%d")
                if d_followup.date() <= now.date() and statut not in ("Refus", "Hired"):
                    pending_followups_today.append(row)
            except ValueError:
                pass

        # Hot signals
        if statut in ("Réponse", "Entretien", "Interview", "Hired"):
            if statut in ("Réponse",):
                hot_responses.append(row)
            elif statut in ("Entretien", "Interview"):
                interviews.append(row)

    return {
        "total": len(rows),
        "status_counts": status_counts,
        "sent_today": sent_today,
        "sent_yesterday": sent_yesterday,
        "sent_last_7d": sent_last_7d,
        "pending_followups_today": pending_followups_today,
        "hot_responses": hot_responses,
        "interviews": interviews,
        "today": today_str,
    }


def render_text(summary):
    """Render plain-text report."""
    lines = []
    lines.append(f"=== JOB MADINAH — Daily Report — {summary['today']} ===\n")
    lines.append(f"Pipeline total: {summary['total']} applications\n")
    lines.append("--- Volume ---")
    lines.append(f"  Sent today:       {summary['sent_today']}")
    lines.append(f"  Sent yesterday:   {summary['sent_yesterday']}")
    lines.append(f"  Sent last 7 days: {summary['sent_last_7d']}")
    target_daily = 17  # midpoint of 15-20
    if summary["sent_today"] < target_daily:
        lines.append(
            f"  ⚠ Behind daily target ({summary['sent_today']}/{target_daily}). Catch up before EOD."
        )
    lines.append("")

    lines.append("--- Status breakdown ---")
    for status, count in sorted(
        summary["status_counts"].items(), key=lambda kv: -kv[1]
    ):
        lines.append(f"  {status:40} {count}")
    lines.append("")

    if summary["interviews"]:
        lines.append("🔥 INTERVIEWS (act fast):")
        for r in summary["interviews"]:
            lines.append(
                f"  [{r.get('ID')}] {r.get('Entreprise')} — {r.get('Poste')} — {r.get('Personne contactée')}"
            )
        lines.append("")

    if summary["hot_responses"]:
        lines.append("📨 ACTIVE REPLIES (respond < 24h):")
        for r in summary["hot_responses"]:
            lines.append(
                f"  [{r.get('ID')}] {r.get('Entreprise')} — {r.get('Poste')} — {r.get('Notes')}"
            )
        lines.append("")

    if summary["pending_followups_today"]:
        lines.append(f"📅 FOLLOW-UPS DUE TODAY ({len(summary['pending_followups_today'])}):")
        for r in summary["pending_followups_today"][:20]:
            lines.append(
                f"  [{r.get('ID')}] {r.get('Entreprise')} — {r.get('Poste')} — next: {r.get('Date prochaine relance')}"
            )
        if len(summary["pending_followups_today"]) > 20:
            lines.append(f"  ... and {len(summary['pending_followups_today']) - 20} more")
        lines.append("")

    lines.append("--- Action items ---")
    lines.append("- Send today's follow-ups (template 05 in templates-EN-persona/)")
    lines.append("- Reply to any active threads within 24h")
    lines.append("- Push pipeline to 17/day if behind")
    lines.append("")
    lines.append("Generated by job-madinah/scripts/daily_report.py")
    return "\n".join(lines)


def send_via_smtp(body, summary):
    """Send the report via Gmail SMTP."""
    if not GMAIL_APP_PASSWORD:
        print("[INFO] GMAIL_APP_PASSWORD not set — printing report to stdout instead")
        print(body)
        return 0

    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = REPORT_RECIPIENT
    msg["Subject"] = (
        f"[Job Madinah] Daily {summary['today']} — "
        f"{summary['sent_today']} sent, {len(summary['interviews'])} interviews, "
        f"{len(summary['hot_responses'])} replies"
    )
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.send_message(msg)
        print(f"[OK] Report sent to {REPORT_RECIPIENT}")
        return 0
    except Exception as e:
        print(f"[ERROR] SMTP send failed: {e}", file=sys.stderr)
        print(body)  # fallback to stdout
        return 1


def main():
    rows = load_tracking()
    if not rows:
        print("[ERROR] No tracking data", file=sys.stderr)
        return 1
    summary = summarize(rows)
    body = render_text(summary)
    return send_via_smtp(body, summary)


if __name__ == "__main__":
    sys.exit(main())
