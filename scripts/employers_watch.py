#!/usr/bin/env python3
"""Veille mensuelle multi-employeurs : alerte quand un poste marketing s'ouvre.

Chaque employeur ici a deja repondu a une candidature spontanee de Nuredin en
renvoyant vers son portail, ou l'a recu sans poste ouvert a ce moment-la. Le but
n'est pas de re-postuler : c'est d'etre prevenu le jour ou un poste marketing
parait, plutot que de le decouvrir des mois plus tard.

Complete scripts/salla_watch.py (meme principe, un seul employeur Workable).

Chaque source declare comment lire ses offres :
  - "zoho"     : portail Zoho Recruit, JSON public
  - "workable" : API widget Workable
  - "html"     : page listant les postes, on lit le texte brut

Usage: python3 scripts/employers_watch.py [--dry-run]
"""

import argparse
import json
import os
import re
import smtplib
import socket
import sys
import urllib.request
import html as html_lib
from email.mime.text import MIMEText
from pathlib import Path

socket.setdefaulttimeout(45)

STATE = Path(__file__).resolve().parent.parent / "data" / "employers_seen.json"

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER)
RECIPIENT = os.environ.get("REPORT_RECIPIENT", "nuredinmohamedali@gmail.com")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

# --- Employeurs suivis -------------------------------------------------------
# Ajouter ici tout employeur qui a repondu "postulez via notre portail".
SOURCES = [
    {
        "name": "Batterjee Medical College",
        "kind": "zoho",
        "url": "https://bmc.zohorecruit.com/jobs/Careers",
        "page": "https://bmc.edu.sa/en/Life-at-BMC/Work-at-BMC",
        "fallback_html": "https://bmc.edu.sa/en/Life-at-BMC/Work-at-BMC",
        "why": "a repondu 30.08 en renvoyant vers son portail ; seul poste marketing = junior 1-3 ans",
    },
    {
        "name": "Al Khozama Investment",
        "kind": "html",
        "url": "https://careers.alkhozama.com/",
        "page": "https://careers.alkhozama.com/",
        "why": "bras d'investissement de la King Faisal Foundation (Al Faisaliah, Riyad) ; a repondu 31.08",
    },
    {
        "name": "International Schools Group (ISG)",
        "kind": "html",
        "url": "https://international-schools-group.skoolspotrecruit.com/",
        "page": "https://www.isg.edu.sa/available-positions",
        "why": "a repondu 22.08 ; poste Marketing & Communications Manager ferme entre-temps",
    },
    {
        "name": "Vera Interior",
        "kind": "html",
        "url": "https://verainterior.com/en/career/",
        "page": "https://verainterior.com/en/career/",
        "why": "a repondu 30.08 ; n'avait qu'un poste commercial a Medine",
    },
]

KEEP = re.compile(
    r"marketing|crm|lifecycle|growth|brand|campaign|acquisition|retention|"
    r"seo|sem|paid|performance|content|social|communicat|e-?commerce|digital",
    re.I,
)
DROP = re.compile(
    r"tamheer|intern\b|internship|engineer|developer|backend|frontend|devops|"
    r"nurse|nursing|clinical|physician|doctor|dentist|pharmac|therapist|"
    r"faculty|professor|instructor|teacher|lecturer|"
    r"waiter|waitress|chef|barista|cashier|retailer|driver|security|"
    r"designer|videographer|photographer|graphic|"
    r"sales executive|sales consultant|sales representative|sales team lead|"
    r"accountant|finance|audit|legal|receptionist|housekeep",
    re.I,
)


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")


def titles_workable(account):
    api = f"https://apply.workable.com/api/v1/widget/accounts/{account}?details=true"
    data = json.loads(fetch(api))
    return [(j.get("title") or "").strip() for j in data.get("jobs", [])]


def titles_html(url):
    """Lit les intitules d'une page d'offres sans JS : liens + titres."""
    html = fetch(url)
    html = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.S)
    out = []
    # intitules dans des liens vers une fiche de poste (on garde l'URL pour
    # pouvoir ecarter les fiches de test)
    for m in re.finditer(r'<a[^>]+href="([^"]*(?:job|career|vacan)[^"]*)"[^>]*>(.*?)</a>', html, re.S | re.I):
        href = m.group(1)
        t = re.sub(r"<[^>]+>", " ", m.group(2))
        t = re.sub(r"\s+", " ", t).strip()
        if 3 < len(t) < 90:
            out.append((t, href))
    # intitules dans des balises de titre
    for m in re.finditer(r"<h[1-5][^>]*>(.*?)</h[1-5]>", html, re.S | re.I):
        t = re.sub(r"<[^>]+>", " ", m.group(1))
        t = re.sub(r"\s+", " ", t).strip()
        if 3 < len(t) < 90:
            out.append((t, ""))
    return out


def titles_zoho(src):
    """Zoho Recruit : la liste est rendue en JS, MAIS le JSON des offres est
    present dans le HTML sous forme d'entites (&#34; pour les guillemets).
    On desechappe puis on lit Posting_Title / Job_Opening_Name."""
    raw = fetch(src["url"])
    plain = html_lib.unescape(raw)
    found = re.findall(r'"(?:Posting_Title|Job_Opening_Name)"\s*:\s*"([^"]{3,90})"', plain)
    if found:
        return found
    # Repli : les intitules apparaissent aussi dans les URL de fiche.
    slugs = re.findall(r"/jobs/Careers/\d+/([A-Za-z0-9\-]{3,60})", plain)
    return [s.replace("-", " ") for s in slugs]


def collect(src):
    """Retourne une liste de (titre, href) quel que soit le type de source."""
    kind = src["kind"]
    if kind == "workable":
        return [(t, "") for t in titles_workable(src["url"])]
    if kind == "zoho":
        return [(t, "") for t in titles_zoho(src)]
    return titles_html(src["url"])


# Entrees de demonstration laissees en ligne par certains employeurs
# (Vera Interior expose une fiche dont l'URL est /career/test-new-job-4/).
TEST_ENTRY = re.compile(r"\btest\b|\bdemo\b|lorem|sample.job|new.job.\d", re.I)
# Pages de CATEGORIE, pas des offres (/job-cat/digital-marketing/, /tag/, ...).
CATEGORY_URL = re.compile(r"/(job-cat|job-category|category|tag|departments?)/", re.I)


def relevant(title, href=""):
    href = href or ""
    if TEST_ENTRY.search(title) or TEST_ENTRY.search(href):
        return False
    if CATEGORY_URL.search(href):
        return False
    return bool(KEEP.search(title)) and not DROP.search(title)


def load_seen():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_seen(d):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def send(subject, body):
    if not SMTP_PASSWORD:
        print("[INFO] SMTP non configure — email ignore")
        print(body)
        return
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = SMTP_FROM
    msg["To"] = RECIPIENT
    msg["Subject"] = subject
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo(); s.starttls(); s.ehlo()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
    print(f"[OK] email envoye a {RECIPIENT}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    seen = load_seen()
    news, errors = [], []

    for src in SOURCES:
        name = src["name"]
        try:
            titles = collect(src)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {type(e).__name__} {e}")
            print(f"[WARN] {name}: {e}", file=sys.stderr)
            continue
        # Un titre n'est garde que si une occurrence AVEC url valide le retient.
        # Sinon une fiche de test passait par son doublon sans href.
        with_href = {t for t, href in titles if href and relevant(t, href)}
        no_href_at_all = {t for t, href in titles if not href} - {t for t, href in titles if href}
        keep = sorted(with_href | {t for t in no_href_at_all if relevant(t)})
        # Une source qui ne rend AUCUN intitule est un angle mort, pas un
        # "rien de nouveau" : son portail est probablement rendu en JS et la
        # veille ne verra jamais une ouverture. Il faut le dire.
        if not titles:
            errors.append(f"{name}: 0 intitule lisible (portail en JS ?) — verifier a la main : {src['page']}")
        before = set(seen.get(name, []))
        fresh = [t for t in keep if t not in before]
        print(f"[INFO] {name}: {len(titles)} intitules, {len(keep)} dans le domaine, {len(fresh)} nouveaux")
        if fresh:
            news.append((name, src["page"], fresh))
        # On memorise ce qu'on a vu, meme sans nouveaute.
        seen[name] = sorted(before | set(keep))

    if news:
        lines = ["Nouveau(x) poste(s) marketing chez des employeurs qui t'avaient renvoye vers leur portail :", ""]
        for name, page, fresh in news:
            lines.append(f"### {name}")
            for t in fresh:
                lines.append(f"  - {t}")
            lines.append(f"  {page}")
            lines.append("")
        if errors:
            lines.append("Sources illisibles ce mois-ci : " + " | ".join(errors))
        body = "\n".join(lines)
        total = sum(len(f) for _, _, f in news)
        if args.dry_run:
            print(body)
        else:
            send(f"[Veille employeurs] {total} nouveau(x) poste(s) marketing", body)
    elif errors:
        body = ("Aucun nouveau poste ce mois-ci, mais des sources n'ont pas pu etre lues.\n"
                "Tant qu'elles restent illisibles, une ouverture peut passer inapercue :\n\n"
                + "\n".join("  - " + e for e in errors))
        print(body)
        if not args.dry_run:
            send(f"[Veille employeurs] {len(errors)} source(s) illisible(s)", body)
    else:
        print("[INFO] rien de nouveau — pas d'email")

    if not args.dry_run:
        save_seen(seen)
    return 0


if __name__ == "__main__":
    sys.exit(main())
