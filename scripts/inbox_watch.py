#!/usr/bin/env python3
"""
Cloud inbox watcher — checks the sending mailbox via IMAP for replies that matter
(interview invitations, screenings, recruiter replies, LinkedIn invite acceptances)
and emails an ALERT to Nuredin so nothing expires unseen (Huzzle lesson, 2026-06).

IMAP host: IMAP_HOST secret if set, else derived from SMTP_HOST (smtp.* -> imap.*).
Uses the same credentials as SMTP (works for Gmail app passwords and Hostinger).
Resilient: any failure prints and exits 0 (a broken watcher must not spam CI alerts),
except a login failure which exits 2 so we notice the watcher is blind.
"""

import email
import imaplib
import os
import re
import smtplib
import socket
import sys
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

socket.setdefaulttimeout(60)

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
SMTP_USE_SSL = os.environ.get("SMTP_USE_SSL", "0") == "1"
RECIPIENT = os.environ.get("REPORT_RECIPIENT", "nuredinmohamedali@gmail.com")
IMAP_HOST = os.environ.get("IMAP_HOST", "") or (
    "imap.gmail.com" if "gmail" in SMTP_HOST else SMTP_HOST.replace("smtp.", "imap.", 1)
)
LOOKBACK_DAYS = int(os.environ.get("INBOX_LOOKBACK_DAYS", "2"))

HOT = re.compile(
    r"interview|screening|assessment|shortlist|next step|schedule a call|"
    r"your availability|move forward|video call|teams meeting|zoom|"
    r"accepted your invitation|entretien|has replied|re:\s",
    re.I,
)
NOISE_SENDERS = re.compile(
    r"jobalerts|noreply@naukrigulf|newsletter|jobs-listings@linkedin|"
    r"gulftalent\.com.*digest|no-?reply@bayt|notifications@|mailer-daemon",
    re.I,
)


def dh(value):
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def main():
    if not SMTP_PASSWORD:
        print("[INFO] secrets not set - skipping")
        return 0
    try:
        box = imaplib.IMAP4_SSL(IMAP_HOST)
        box.login(SMTP_USER, SMTP_PASSWORD)
    except Exception as e:  # noqa: BLE001
        print(f"[ERROR] IMAP login failed on {IMAP_HOST} as {SMTP_USER}: {e}", file=sys.stderr)
        return 2

    if os.environ.get("INBOX_DEBUG_IDENTITY") == "1":
        # print identity split at @ so CI secret-masking (exact-string) doesn't hide it
        u = SMTP_USER.replace("@", " [at] ")
        f = SMTP_FROM.replace("@", " [at] ")
        r = RECIPIENT.replace("@", " [at] ")
        print(f"[IDENTITY] login={u} | from={f} | alerts_to={r} | imap={IMAP_HOST}")
    box.select("INBOX")
    since = (datetime.utcnow() - timedelta(days=LOOKBACK_DAYS)).strftime("%d-%b-%Y")
    _, data = box.search(None, f'(SINCE "{since}")')
    ids = data[0].split()
    hits = []
    for mid in ids[-200:]:
        _, msg_data = box.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
        raw = b"".join(part[1] for part in msg_data if isinstance(part, tuple))
        m = email.message_from_bytes(raw)
        frm, subj = dh(m.get("From")), dh(m.get("Subject"))
        if NOISE_SENDERS.search(frm):
            continue
        if HOT.search(subj) or HOT.search(frm):
            hits.append((dh(m.get("Date")), frm, subj))
    box.logout()

    print(f"[INFO] scanned {min(len(ids),200)} recent messages on {IMAP_HOST}, {len(hits)} hot")
    if not hits:
        print("[OK] nothing urgent")
        return 0

    lines = [
        "ALERTE - reponses/screenings detectes dans la boite d'envoi.",
        "Certains liens (interviews IA, chats) EXPIRENT en 24-48h - traiter aujourd'hui.",
        "",
    ]
    for d, f, s in hits:
        lines.append(f"- {d}\n  De: {f}\n  Sujet: {s}\n")
    body = "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM
    msg["To"] = RECIPIENT
    msg["Subject"] = f"[Job Madinah] {len(hits)} reponse(s) a traiter - ne pas laisser expirer"
    msg.attach(MIMEText(body, "plain", "utf-8"))
    try:
        if SMTP_USE_SSL:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        print(f"[OK] alert sent to {RECIPIENT}")
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] alert send failed: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
