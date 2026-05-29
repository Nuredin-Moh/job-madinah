# Job Madinah — Senior Marketing Manager search

Automation pipeline for Nuredin Mohamed Ali's job hunt: Senior Marketing Manager / Director role in Madinah, Saudi Arabia.

## Status

- DSA prospection (Swiss agency cold outreach) → **STOPPED 2026-05-29**. Workflows `bounce`, `reply`, `send` in `dsa-prospection` repo are disabled.
- Job Madinah outreach → **ACTIVE** from 2026-05-29.
- Target: 500 quality applications over 6 weeks → 5-10 interview rounds.
- Volume cap: 15-20 applications/day (quality > quantity for job hunt).

## Pipeline

```
[1] Source job postings + identified contacts
    ↓
[2] Generate personalized email from template (scripts/generate.py)
    ↓
[3] QA pipeline (scripts/qa.py) — anti-bounce, anti-typo, anti-generic
    ↓
[4] Send via Gmail draft (scripts/send.py — uses AppleScript on Mac)
    ↓
[5] Log to data/tracking.csv + logs/sent.log
    ↓
[6] Auto follow-up scheduler at J+7 / J+14 / J+21 (scripts/followup.py)
    ↓
[7] Daily report via Gmail (scripts/report.py) — runs via GitHub Actions
```

## Data structure

```
data/
├── tracking.csv              # source of truth — all applications + status
├── contacts.csv              # LinkedIn contacts identified, status
├── companies.csv             # target companies, sector, priority
└── bounces.txt               # emails confirmed BOUNCED — never retry
```

## Workflows (GitHub Actions)

| Workflow | Trigger | Action |
|----------|---------|--------|
| `daily-report.yml` | Cron 18:00 UTC daily | Sends summary email of today's actions, replies, upcoming follow-ups |
| `followup-scheduler.yml` | Cron 8:00 UTC daily | Identifies candidates due for follow-up, generates drafts |
| `qa-on-push.yml` | On push to data/ | Validates CSV integrity, no duplicate IDs, no missing emails |

NOTE: Email SENDING happens locally on Nuredin's Mac via AppleScript (Gmail draft creation + send). GitHub Actions handles only generation, QA, scheduling, and reporting.

## Templates

The 5 EN persona templates live in `/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/06-Candidatures-Spontanées/templates-EN-persona/`:

1. CEO / Founder
2. HR Director
3. Hiring Manager (CMO / MD)
4. Reply to specific job posting
5. Follow-up J+7 (3 versions)

CVs as PDF in `/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/01-CVs-Personnalisés/PDF/`.

## Anti-bounce policy

See `/Users/nuredin.mohamedali/Desktop/Arabie/Recherche Emploi Médine/07-Tracking/POLITIQUE-ANTI-BOUNCE.md`.

Hard rule: NO email guess. Every send requires:
1. Verified source (LinkedIn / Hunter.io / company site)
2. MX record check (`dig +short MX domain.com`)
3. Mailtester / SMTP verification

## Volume + cadence

- 15-20 quality applications/day max
- Sunday-Wednesday 9-11am Madinah time = send window
- Avoid: Thursday afternoon, Friday weekend KSA, Ramadan
- 50 emails/day max from `nuredinmohamedali@gmail.com` to preserve Gmail reputation
- Follow-up cadence: J+7 → J+14 → J+21 → stop

## Key paths (cross-repo)

```
~/Desktop/Arabie/                                    # All KSA assets root
~/Desktop/Arabie/CV EN - Version ATS.pdf             # Master CV (FR-version-2 for fallback)
~/Desktop/Arabie/Recherche Emploi Médine/            # Operations hub
~/job-madinah/                                       # This repo (automation infra)
~/dsa-prospection/                                   # OLD DSA stuff — workflows disabled
```
