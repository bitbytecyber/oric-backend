# Seeding & demo logins

All commands run inside the backend container:

```bash
docker exec -it oric_local-backend-1 python manage.py <command>
```

| Command | What it does |
|---|---|
| `seed_oric` | Fiscal years (the last three; the current one OPEN, deadline 15 Dec), RBAC catalog + roles, and the NED directory from `org/seed/*.csv` (6 faculties, 31 departments, ~550 people, deans, chairs, ORIC staff) |
| `seed_oric --workbook .local/hec_fy2024-25.xlsx` | + imports last year's HEC ORIC Self-Assessment workbook into FY 2024-25 (~2,050 verified records, ~136 names to match) |
| `seed_oric --demo` | + a shared demo password on every account and ~570 synthetic FY 2025-26 submissions in every status (tagged `data._demo`) |
| `seed_oric --reset-demo --demo` | Deletes synthetic submissions and regenerates them |
| `import_directory [--dry-run] [--dir path]` | Upserts the directory CSVs on their own and re-syncs Dean / Chairman roles |
| `import_hec_workbook <path> --year 2025 [--keep]` | Imports any HEC workbook into the fiscal year ending in `--year` |
| `seed_rbac [--additive]` | Re-syncs the capability catalog and built-in roles |

The HEC workbook is not committed (it contains staff contact details). Put a copy at
`oric-backend/.local/hec_fy2024-25.xlsx`; `.local/` is git-ignored and mounted in the container.

Full local reset:

```bash
docker exec oric_local-db-1 psql -U oric -d postgres -c 'DROP DATABASE "oric-local" WITH (FORCE);' -c 'CREATE DATABASE "oric-local" OWNER oric;'
docker exec oric_local-backend-1 python manage.py migrate
docker exec oric_local-backend-1 python manage.py seed_oric --workbook .local/hec_fy2024-25.xlsx --demo
```

## Demo logins

Password for every account in demo mode: `OricDemo#2026` (or `ORIC_DEMO_PASSWORD`). Accounts are the real
directory emails; nothing is sent to them locally (mail goes to Mailpit at http://localhost:8035).

| Role | Login | Starts on |
|---|---|---|
| System admin | `admin@oric.test` | Everything incl. roles |
| Director ORIC | `riazuddin@neduet.edu.pk` (Dr. Riaz Uddin) | University → all faculties |
| Manager Research Ops | `uzair@neduet.edu.pk` | Grants, IRB, publications, trainings |
| Manager IP | `aahmed@neduet.edu.pk` | IP disclosures, patents, licensing, prototypes |
| Manager Tech Transfer & UIL | `saeeda@neduet.edu.pk` | Contract research, consultancy, linkages |
| Manager BIC | `mirzafaizan@cloud.neduet.edu.pk` | Startups, spin-offs, funding, events |
| Assistant manager (all categories) | `engrimran@neduet.edu.pk` | All categories, imports |
| Dean, Civil & Petroleum | `asadkhan@neduet.edu.pk` | His faculty → departments |
| Dean, Architecture & Sciences | `baig@neduet.edu.pk` | His faculty → departments |
| Chairman, Urban & Infrastructure | `adnan@neduet.edu.pk` | His department → people |
| Faculty member (EED) | `abdullah.munir@neduet.edu.pk` | Own records |
| Faculty member (CED) | `arebasyed@cloud.neduet.edu.pk` | Own records |

Any other person in `org/seed/people.csv` can sign in the same way. People whose department site publishes no email
have a `@placeholder.neduet.edu.pk` address (`email_source=placeholder`); replace those with real addresses by
re-importing `people.csv`.
