#!/usr/bin/env python3
"""
Generator candidatures emploi Madinah
======================================

Reads Tracking-Candidatures.csv and generates a ready-to-send email
for each row with status "À envoyer".

Output: mails-à-envoyer/YYYY-MM-DD-entreprise-poste.txt

Anti-bullshit policy
--------------------
- NO "Dear Hiring Manager" — always personalised by contact first name
  or by company name ("Dear {Company} Team,").
- NO `[phone]` placeholders — phone is hardcoded to Nuredin's real number.
- NO fabricated numbers. Only verifiable facts from Nuredin's CV are used:
    * CHF 2M+ annual budgets handled at Publicis Geneva (Nestlé, BCGE)
    * 10+ years of senior marketing experience
    * ROAS 4.2x on optimised paid campaigns
    * 90% client retention at Digital Swiss Agency (CEO)
    * Master CREA Geneva
- QA still re-runs `\\[[A-Z_]{2,}\\]` and `{{[a-z_]+}}` placeholder checks
  on every generated file before send.

Usage:
    python3 generator.py

Stdlib only.
"""

import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# -------- Configuration --------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("JOB_MADINAH_ROOT", SCRIPT_DIR.parent))
CSV_PATH = Path(
    os.environ.get(
        "JOB_MADINAH_TRACKING_CSV",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/Tracking-Candidatures.csv",
    )
)
OUTPUT_DIR = Path(
    os.environ.get(
        "JOB_MADINAH_OUTPUT_DIR",
        "/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/mails-à-envoyer",
    )
)
TRIGGER_STATUS = "À envoyer"

# -------- Profile (verified, no placeholders) --------
PROFILE = {
    "name": "Nuredin Mohamed Ali",
    "phone": "+212 626 012 886",
    "email": "nuredinmohamedali@gmail.com",
    "linkedin": "linkedin.com/in/nuredinmohamedali",
    "title": "Senior Digital Marketing Manager | CEO Digital Swiss Agency",
}

# Patterns used to detect leftover placeholders before writing a file.
PLACEHOLDER_REGEXES = (
    re.compile(r"\[[A-Z_]{2,}\]"),       # [PHONE], [COMPANY], ...
    re.compile(r"\{\{[a-z_]+\}\}"),       # {{first_name}}, {{company}}, ...
    re.compile(r"\+212\s*\[phone\]", re.IGNORECASE),  # legacy placeholder
)


# -------- Sector detection --------
def detect_sector(entreprise: str, poste: str) -> str:
    text = f"{entreprise} {poste}".lower()
    if any(k in text for k in [
        "hotel", "hôtel", "resort", "marriott", "hilton",
        "intercontinental", "movenpick", "pullman", "sofitel",
        "sheraton", "hospitality", "dar al", "accor", "ihg", "hyatt",
    ]):
        return "hotel"
    if any(k in text for k in [
        "mall", "retail", "store", "boutique", "cenomi",
        "shopping", "centre commercial", "chalhoub",
        "alshaya", "carrefour", "lulu",
    ]):
        return "retail"
    if any(k in text for k in [
        "agency", "agence", "ogilvy", "publicis", "tbwa",
        "wunderman", "memac", "communications",
    ]):
        return "agence"
    if any(k in text for k in [
        "tech", "startup", "saas", "neom", "roshn", "stc",
        "fintech", "hungerstation", "tabby", "tamara", "nana",
        "foodics",
    ]):
        return "tech"
    return "generic"


# -------- Hooks (no fabricated numbers) --------
SECTOR_HOOK = {
    "hotel": "I have been following {entreprise}'s positioning in {lieu} — strong work in the Pilgrim and Premium segments.",
    "retail": "I noticed {entreprise}'s recent expansion in {lieu} and the omnichannel ambition behind it.",
    "agence": "{entreprise}'s recent work caught my attention — clear strategic and performance execution.",
    "tech": "I have been following {entreprise}'s trajectory in {lieu} — your product positioning aligns with Vision 2030 priorities.",
    "generic": "I have been following {entreprise}'s growth in {lieu} and was impressed by your recent trajectory.",
}


# -------- Fit blocks — verifiable facts ONLY --------
# Sources used:
#   - 10+ years senior marketing (CV / LinkedIn).
#   - CHF 2M+ annual budgets at Publicis Geneva on Nestlé and BCGE accounts.
#   - ROAS 4.2x average on optimised paid campaigns (DSA internal reporting).
#   - 90% client retention at Digital Swiss Agency.
#   - Master CREA Geneva.
# All other figures previously hard-coded (€2.1M, €1.2M, +47%, €480K, 35%)
# have been removed because they were not traceable to a verifiable source.
COMMON_FIT_LINES = [
    "- 10+ years senior marketing across hospitality, retail and tech",
    "- CHF 2M+ annual budgets handled at Publicis Geneva (Nestlé, BCGE accounts)",
    "- ROAS 4.2x average on optimised paid campaigns",
    "- 90% client retention at Digital Swiss Agency (CEO, current)",
    "- Master in Digital Marketing — CREA Geneva",
]

SECTOR_INTRO = {
    "hotel": "I have led digital growth for hospitality and luxury brands for 10+ years (ex-Publicis Geneva, currently CEO Digital Swiss Agency).",
    "retail": "I have 10+ years scaling retail and luxury brands across MENA and EU (ex-Publicis Geneva, currently CEO Digital Swiss Agency).",
    "agence": "I bring 10+ years of agency and client-side experience (ex-Publicis Geneva, currently CEO Digital Swiss Agency).",
    "tech": "I have 10+ years scaling brands across MENA and EU (ex-Publicis Geneva, currently CEO Digital Swiss Agency).",
    "generic": "I am a Senior Digital Marketing Manager with 10+ years driving growth for hospitality, retail and tech brands (ex-Publicis Geneva, currently CEO Digital Swiss Agency).",
}


def build_fit_block(sector: str) -> str:
    intro = SECTOR_INTRO[sector]
    bullets = "\n".join(COMMON_FIT_LINES)
    return f"{intro} Recent track record:\n{bullets}"


EMAIL_TEMPLATE = """Subject: {subject}

{greeting}

{hook}

I am {name}, {title}.

{fit_block}

I am relocating to Madinah within 3 months and would value a 15-minute call to explore how my profile could support {entreprise}'s 2026 plans for the {poste} role you posted{source_note}.

CV attached.

Best regards,

{name}
{title}
{phone} | {linkedin} | {email}
"""


# -------- Helpers --------
def slugify(value: str) -> str:
    value = value.lower().strip()
    value = re.sub(
        r"[àâäéèêëîïôöùûüç]",
        lambda m: {
            "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e",
            "ë": "e", "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u",
            "û": "u", "ü": "u", "ç": "c",
        }[m.group(0)],
        value,
    )
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value[:80]


def extract_first_name(contact: str) -> str:
    """
    Return the first name of the contact, or empty string if not parseable.
    NEVER returns 'Hiring Manager' — fallback is handled in build_greeting().
    """
    if not contact or not contact.strip():
        return ""
    name_part = contact.split("/")[0].split("(")[0].strip()
    if not name_part or "@" in name_part:
        return ""
    tokens = name_part.split()
    if not tokens:
        return ""
    first = tokens[0].strip(",.;")
    # Filter out tokens that are obviously not a first name
    if first.lower() in {"hr", "team", "department", "linkedin", "n/a"}:
        return ""
    return first


def build_greeting(contact: str, entreprise: str) -> str:
    """
    Personalised greeting:
      1. Contact first name if available
      2. Otherwise '{Company} Team' — never 'Hiring Manager'.
    """
    first = extract_first_name(contact)
    if first:
        return f"Dear {first},"
    company = (entreprise or "").strip()
    if not company:
        # Last-resort fallback: still avoids generic "Hiring Manager"
        return "Dear Marketing Team,"
    return f"Dear {company} Team,"


def build_subject(poste: str, entreprise: str) -> str:
    return f"Senior Digital Marketing Manager – 10 yrs exp – Available for {entreprise} ({poste})"


def build_source_note(source: str, url: str) -> str:
    if source and source.strip():
        return f" via {source}"
    return ""


def scan_placeholders(text: str) -> list[str]:
    """Return any leftover placeholder tokens. Used as a hard QA gate."""
    leftover: list[str] = []
    for rx in PLACEHOLDER_REGEXES:
        leftover.extend(rx.findall(text))
    return leftover


def generate_email(row: dict) -> tuple[str, list[str]]:
    """
    Returns (email_text, leftover_placeholders).
    If leftover_placeholders is non-empty, the email must NOT be sent.
    """
    entreprise = row.get("Entreprise", "").strip() or "your team"
    poste = row.get("Poste", "").strip() or "Senior Marketing role"
    lieu = row.get("Lieu", "").strip() or "Madinah"
    source = row.get("Source", "").strip()
    url = row.get("URL annonce", "").strip()
    contact = row.get("Personne contactée", "").strip()

    sector = detect_sector(entreprise, poste)
    hook = SECTOR_HOOK[sector].format(entreprise=entreprise, lieu=lieu)
    fit = build_fit_block(sector)
    greeting = build_greeting(contact, entreprise)

    email_body = EMAIL_TEMPLATE.format(
        subject=build_subject(poste, entreprise),
        greeting=greeting,
        hook=hook,
        name=PROFILE["name"],
        title=PROFILE["title"],
        fit_block=fit,
        entreprise=entreprise,
        poste=poste,
        source_note=build_source_note(source, url),
        phone=PROFILE["phone"],
        linkedin=PROFILE["linkedin"],
        email=PROFILE["email"],
    )

    header = (
        f"# Email généré le {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"# Entreprise: {entreprise}\n"
        f"# Poste: {poste}\n"
        f"# Source: {source}\n"
        f"# URL: {url}\n"
        f"# Contact: {contact}\n"
        f"# Lieu: {lieu}\n"
        f"# Secteur détecté: {sector}\n"
        f"# Score match (CSV): {row.get('Score match', 'N/A')}\n"
        f"# {'-' * 70}\n"
        f"# ACTION: vérifier l'adresse destinataire puis envoyer\n"
        f"# {'-' * 70}\n\n"
    )

    full_text = header + email_body
    leftover = scan_placeholders(email_body)  # only body, not the meta header
    return full_text, leftover


def main() -> int:
    if not CSV_PATH.exists():
        print(f"[ERROR] CSV introuvable: {CSV_PATH}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0
    skipped = 0
    rejected = 0

    with CSV_PATH.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            statut = (row.get("Statut") or "").strip()
            if statut != TRIGGER_STATUS:
                skipped += 1
                continue

            entreprise = row.get("Entreprise", "").strip() or "entreprise"
            poste = row.get("Poste", "").strip() or "poste"
            date_str = datetime.now().strftime("%Y-%m-%d")
            filename = f"{date_str}-{slugify(entreprise)}-{slugify(poste)}.txt"
            output_path = OUTPUT_DIR / filename

            email_content, leftover = generate_email(row)
            if leftover:
                print(
                    f"[REJECT] {filename} — leftover placeholders {set(leftover)} — NOT written",
                    file=sys.stderr,
                )
                rejected += 1
                continue

            output_path.write_text(email_content, encoding="utf-8")
            print(f"[OK] {filename}")
            generated += 1

    print(f"\n--- Résumé ---")
    print(f"Mails générés : {generated}")
    print(f"Rejetés (placeholders détectés) : {rejected}")
    print(f"Lignes ignorées (statut != '{TRIGGER_STATUS}') : {skipped}")
    print(f"Output : {OUTPUT_DIR}")

    if generated == 0 and rejected == 0:
        print(
            f"\nTip: passe une ligne du CSV en statut '{TRIGGER_STATUS}' "
            "pour générer un mail."
        )
    return 0 if rejected == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
