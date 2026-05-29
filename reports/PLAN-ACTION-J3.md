# Plan d'action J3 (2026-05-29) — Job Madinah

## État actuel — Pipeline

- **156 candidatures** loguées dans Tracking-Candidatures.csv (target 350)
- **75 entreprises cibles** cartographiées sur 7 secteurs
- **31 BOUNCES** identifiés (politique anti-bounce désormais en place — voir POLITIQUE-ANTI-BOUNCE.md)
- **9 CVs FR/EN + 1 Arabe** + **9 Lettres + 1 Arabe** prêts à utiliser
- **11 DM LinkedIn HR envoyés J2** (Rua Al-Madinah, NEOM, RCU, RSG, Riyadh Air, STA)
- **3 réponses positives en cours** (Al Madinah Mall, Webdew KSA en entretien, Dar Al Iman vu 2x)

## Quoi de nouveau aujourd'hui (J3)

1. **5 templates EN persona** créés dans `06-Candidatures-Spontanées/templates-EN-persona/`
   - 01 CEO/Founder, 02 HR Director, 03 Hiring Manager, 04 Job Posting Reply, 05 Follow-Up J+7
2. **Repo GitHub job-madinah** créé : github.com/Nuredin-Moh/job-madinah (privé)
3. **Pipeline QA automatisé** (`scripts/qa.py`) avec checks anti-bounce, anti-placeholder, MX validation
4. **Scheduler follow-up** (`scripts/followup_scheduler.py`) → J+7/+14/+21 versions
5. **Daily report** (`scripts/daily_report.py`) → résumé Gmail quotidien
6. **3 workflows GitHub Actions** configurés : daily-report, followup-scheduler, qa-on-push
7. **Liste 47 companies** dans `data/companies.csv` (priorité 1 = 28, mega-projets PIF + hôtels 5* Madinah + groupes hospitality MENA)
8. **27 emails bounced** transférés dans `data/bounces.txt` (anti-rebond)

## Ce qui reste à faire — Actions Nuredin

### Imminent (cette semaine)

1. **Postuler aux 50 candidatures "PRÊT À SOUMETTRE"** dans le CSV (IDs 105-154)
   - 24 portails hospitality (Marriott / IHG / Hilton / Accor / Hyatt / Four Seasons)
   - 16 portails mega-projets PIF (NEOM / RSG / RCU / Rua / Riyadh Air / DGDA / Qiddiya / Taiba / New Murabba / STA)
   - 11 DM LinkedIn HR déjà envoyés J2 — surveiller réponses
2. **Surveiller les 4 réponses chaudes** sous 24h (Movenpick, Dar Al Iman 2 vues, Al Madinah Mall call, Webdew entretien 30/05)
3. **Suivre l'entretien Webdew KSA** 2026-05-30 (préparer : codes culturels KSA + Vision 2030 + 3 questions de fin gagnantes)
4. **Configurer secrets GitHub** sur le repo job-madinah :
   - `GMAIL_APP_PASSWORD` : créer un mot de passe d'application Gmail
   - `REPORT_RECIPIENT` : nuredinmohamedali@gmail.com
   - (optionnel) `TRACKING_GIST_ID` + `TRACKING_GIST_TOKEN` pour sync auto du CSV

### Court terme (J+5 à J+14)

5. **Acheter LinkedIn Sales Navigator 1 mois free trial** → identifier 30 contacts CMO/HR additionnels (Astuce PDF étape 4 : "Le filtre LinkedIn caché")
6. **Hunter.io 49 USD/mois** → vérifier 500 emails (corrige 27 bounces → ~85% de hit rate sur emails nominatifs)
7. **Photo LinkedIn premium** (50-100 EUR photographe) — astuce ÉTAPE 3 PDF : "Photo premium obligatoire → ROI énorme"
8. **Activer Open to Work caché côté Europe** (visible uniquement KSA recruteurs) — astuce PDF "Le hack recruteur"
9. **Postuler aux 90 nouvelles cibles** identifiées dans companies.csv non encore traitées

### Stratégique (J+14 à J+30)

10. **Headline LinkedIn**: changer en "Senior Marketing Manager | Vision 2030 Projects | Open to Madinah / KSA"
11. **About LinkedIn**: 3 phrases pitch 30 secondes (cf PDF étape 3)
12. **1 post LinkedIn/semaine en EN** sur le marché Madinah hospitality / Vision 2030 → attire recruteurs sans postuler
13. **Cible re-candidature** pour les 27 bounces : passer par formulaire careers + DM LinkedIn HR (mapping dans ALTERNATIVES-BOUNCES.md)

## Tips stratégiques tirés du PDF "10 étapes Golfe"

### Étape 4 — Ciblage en sniper, pas en mitraillette
> "Tu passes de candidat lambda noyé dans 500 CV à candidat prioritaire identifié."

→ Plutôt que 200 candidatures aux portails publiques, identifier 20-30 entreprises/projets ciblés et **être déjà visible** sur leur radar via LinkedIn (filtre "poste fantôme" : 80% des postes ne passent jamais en annonce publique).

### Étape 5 — Le "double canal"
> "Envoie ton CV par email ET fais un message LinkedIn → double visibilité."

→ Pour chaque candidature stratégique : email + DM LinkedIn au CMO/HR. C'est ce qui passe le reply rate de 2-3% à 15-20%.

### Étape 7 — Négociation package : ne JAMAIS parler en net
> "Compare avec Dubaï → bon argument pour négocier +"

Quand une réponse positive arrive : préparer la grille KSA Senior Manager 8-15 ans exp = 18-22k EUR/mois nets équivalent. Package type :
- Salaire base : 45-55k SAR/mois
- Housing : 12-15k SAR/mois
- École enfants : 80k SAR/an × N enfants
- Car allowance : 3k SAR/mois
- Flights : 1-2 A/R par an pour famille
- Assurance santé premium famille
- ILOE chômage obligatoire depuis 2023

→ Toujours poser : *"Is this package aligned with your other expat managers at the same level?"* → protège des offres "discount expat".

## KPIs visés 6 semaines

- 500 candidatures qualifiées (vs 156 actuelles → +344 à venir)
- 20% reply rate sur emails nominatifs avec recherche perso (vs 2-3% générique)
- 5-10 entretiens (round 1)
- 2-3 offres concrètes
- 1 contrat signé avant fin Q3 2026

## Architecture finale

```
~/Desktop/Arabie/
├── CV EN - Version ATS.pdf                # Master CV (référence)
├── CV EN - Version ATS - 2.pdf            # Variant
├── LES 10 CHOSES… mp4                     # Strategic video
├── Les 10 etapes… pdf                     # Strategic PDF (Mehdi le Formateur)
└── Recherche Emploi Médine/
    ├── 01-CVs-Personnalisés/              # 9 CVs FR/EN + Arabe + PDFs
    ├── 02-Lettres-Motivation/             # 9 lettres + Arabe
    ├── 03-Liste-Postes/                   # Marché + Entreprises + Vision 2030
    ├── 04-LinkedIn/                       # Profil + plan content + scripts + contacts
    ├── 05-Recruteurs-Agences/             # Cabinets
    ├── 06-Candidatures-Spontanées/
    │   ├── Email-Spontané-{Hôtel,Agence,Retail,Tech,Arabe}.md
    │   ├── templates-EN-persona/           ← NEW 2026-05-29
    │   │   ├── 01-CEO-Founder-EN.md
    │   │   ├── 02-HR-Director-EN.md
    │   │   ├── 03-Hiring-Manager-EN.md
    │   │   ├── 04-Job-Posting-Reply-EN.md
    │   │   ├── 05-Follow-Up-7-Days-EN.md
    │   │   └── README.md
    │   └── Sequence-Relances.md
    ├── 07-Tracking/                       # CSV + scripts + politiques
    │   ├── Tracking-Candidatures.csv      # 156 lignes en cours
    │   ├── POLITIQUE-ANTI-BOUNCE.md       # Politique obligatoire
    │   ├── MACHINE-A-POSTULER.md          # 50 jobs prêts
    │   ├── PLAN-350-CANDIDATURES.md       # Plan 6 semaines
    │   ├── ALTERNATIVES-BOUNCES.md        # Mapping 27 bounces → alternatives
    │   ├── generator.py                   # Generate emails from CSV
    │   └── send_emails.py                 # AppleScript Apple Mail send
    ├── 08-Documents-Visa/                 # Checklist visa KSA
    └── 09-Préparation-Entretiens/         # Q&A EN + codes culturels + nego

~/job-madinah/                              ← NEW 2026-05-29
├── README.md                              # Pipeline overview
├── .github/workflows/
│   ├── daily-report.yml                   # 18:00 UTC daily
│   ├── followup-scheduler.yml             # 08:00 UTC Sun-Wed
│   └── qa-on-push.yml                     # On push
├── scripts/
│   ├── qa.py                              # Anti-bounce + placeholders + MX + duplicates
│   ├── daily_report.py                    # Pipeline summary → Gmail
│   └── followup_scheduler.py              # J+7/+14/+21 generation
├── data/
│   ├── companies.csv                      # 47 target companies
│   └── bounces.txt                        # 27 confirmed bad emails
├── reports/PLAN-ACTION-J3.md              ← This file
└── logs/                                  # Runtime logs (gitignored)

~/dsa-prospection/                          # OLD — workflows désactivés
```

---

**Date** : 2026-05-29
**Prochaine revue** : 2026-06-05 (J+7) — vérifier réponses + ajuster volume
