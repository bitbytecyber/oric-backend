# Seed commands

All commands run inside the backend container:

```bash
docker exec -it oric_local-backend-1 python manage.py <command>
```

| Command | What it does | Idempotent |
|---|---|---|
| `seed_oric` | Reference data: the 28 NED departments (with codes and faculties), the last 3 reporting cycles (the most recent fiscal year is OPEN, older ones CLOSED, deadline 15 Dec), the 6-person ORIC team, the RBAC catalog and built-in roles | yes |
| `seed_oric --demo` | The above, plus a full demo world (below) | yes: decisions are seeded per person × year × pillar, so a re-run adds nothing |
| `seed_oric --demo --faculty-per-dept 6 --years 3 --seed 2026` | Size the demo world (`--seed` changes who files what) | yes |
| `seed_oric --reset-demo --demo` | Deletes every `*oric.test` account with its returns and evidence, then rebuilds | — |
| `seed_oric --superuser-email X --superuser-password Y` | Also creates a superuser with a verified email (or set `ORIC_SUPERUSER_EMAIL` / `ORIC_SUPERUSER_PASSWORD`) | yes |
| `seed_rbac [--additive]` | Re-syncs the capability catalog and built-in roles. `--additive` never removes grants | yes |
| `send_test_email [address]` | Sends one test email through the configured SMTP. Locally it lands in Mailpit at http://localhost:8035 | yes |
| `export_registry` | Regenerates `knowledge/03-forms-catalog.md` and `knowledge/data/form_registry.json` from `submissions/registry.py` | yes |

## What `--demo` creates (default sizes)

- **People (≈125).** Every account is provisioned like a real one: a `User`, a `Person` profile and a *verified* allauth `EmailAddress`.
  - **13 named role accounts.** Listed in the table below.
  - **4 generated faculty per department, 112 in total.** Each has a realistic name, designation (Professor → Lecturer), employee ID and phone.
  - **A focal person per department.** The first generated person in each department is that department's focal person, a `department_focal` role scoped to the department. Electrical Engineering uses `focal.ee@oric.test` instead.
- **Returns (≈560 over three fiscal years).**
  - **Who files:** about 80 % of faculty file Research Excellence, 50 % Innovation & Commercialization and 22 % Sustainability & Capacity Building.
  - **Statuses:**
    - Current year: every status (draft, submitted, under review, returned, approved, rejected).
    - Past years: approved, with a few returned or rejected.
  - **Contents:** each return declares 2–5 sub-forms with 1–3 activities each. Between them, all 32 sub-forms are used.
  - **Values:** realistic for every field: research titles, HEC/PSF/Ignite grants, PKR amounts, co-PI universities, inventions, startups, HJRS publications and so on.
  - **Drafts:** some drafts are deliberately incomplete, so the ledger shows hollow (missing) dots.
- **Evidence (≈3,000 PDFs).** One-page PDFs naming the faculty member, return, section and activity, stamped "Synthetic demo evidence".
- **Review history.** Submit, start-review, return/approve/reject events with reviewer comments and realistic dates inside each filing window. The current year also gets owner notifications.
- **Contact inbox.** A few sample messages.

Everything demo-related lives on the reserved `.test` domain (`@oric.test`, `@faculty.oric.test`), so no email can reach a real person.

## Demo accounts

Password for every demo account: `OricDemo#2026` (override with `ORIC_DEMO_PASSWORD` when seeding). Generated faculty use the same password.

| Email | Role(s) | What to try |
|---|---|---|
| admin@oric.test | System administrator (`admin`, holds `rbac.manage`) | Roles & permissions, people, audit |
| director@oric.test | Director ORIC + faculty | Everything except super-admin role management |
| manager@oric.test | ORIC manager | Review queue (all pillars), approve/return, reports, exports, cycles, team, inbox |
| research.manager@oric.test | Research Operations manager (RE only) + faculty | Sees only Research Excellence returns |
| ip.manager@oric.test | IP manager (IC only) + faculty | Sees only Innovation & Commercialization returns |
| techtransfer@oric.test | Tech Transfer manager (IC + RE) + faculty | Two pillars |
| incubation@oric.test | Incubation manager (SCB only) + faculty | Sees only startup / spin-off returns |
| auditor@oric.test | Auditor (read-only) | Reports, exports, audit trail |
| focal.ee@oric.test | Department focal person, scoped to Electrical Eng. | Sees and reviews only EE returns |
| faculty.ee@oric.test | Faculty (Electrical) | RE submitted, IC draft |
| faculty.cs@oric.test | Faculty (CS & IT) | RE approved, SCB under review |
| faculty.me@oric.test | Faculty (Mechanical) | IC returned for revision |
| faculty.ch@oric.test | Faculty (Chemical) | RE draft |
| *first.last*@faculty.oric.test | Generated faculty (112) | Look them up on **People** |

Sign-in is django-allauth: password, *Continue with Google* / *Continue with Apple* (only once their keys are set; demo `*.test` addresses can't be Google/Apple accounts, so link your own to a real account you create on **People**), *Email me a sign-in code* (the code arrives in Mailpit at http://localhost:8035), and optional TOTP two-step verification set up from **Profile → Sign-in & security**.

Never run `--demo` against production.
