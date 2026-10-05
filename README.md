# NED ORIC Data Portal — backend

This is the Django 4.2 + DRF API that rebuilds the legacy ORIC Data Portal, NED University's annual research, innovation and entrepreneurship returns for the HEC ORIC Scorecard. The research behind it is in `../knowledge/`.

Conventions follow `sis_backend`:
- **authentication is django-allauth 65.19 headless**, set up like SIS: `people.User(AbstractUser)` with email login plus a `Person` profile; account, headless and MFA adapters in `people/adapters.py`; email login, login-by-code, **Google and Apple sign-in** (Google: GIS id_token → `POST …/auth/provider/token`; Apple: server redirect via `POST …/auth/provider/redirect`; credentials from env, not a DB SocialApp), TOTP plus recovery codes, tracked user sessions. The same SameSite=Lax session cookie authenticates `/_allauth` and `/api/v1`. Signup is closed (ORIC provisions accounts)
- split settings (`oric_backend/settings/{base,dev,prod}.py`), Pipfile, one Docker Compose file per environment
- session-cookie auth, the `{ok,data,meta}` envelope and `DomainAPIError`
- a code-first RBAC capability catalog, `HasCapability` / `RBACViewSetMixin`, `/me/abilities/` CASL rules, and the coverage-guard test
- django-auditlog plus `ActivityEvent`, correlated by request id

## Run (Docker only)

```bash
docker compose -f docker-compose.local.yml up -d --build   # values from .env (copy of .env.example)
docker exec -it oric_local-backend-1 python manage.py migrate
docker exec -it oric_local-backend-1 python manage.py seed_oric --demo
```

| Service | URL |
|---|---|
| API | http://localhost:8090/api/v1/ |
| Swagger | http://localhost:8090/api/docs/ |
| Django admin | http://localhost:8090/admin/ |
| Mailpit: every email the portal sends locally (sign-in codes, password resets, workflow notifications, contact form) | http://localhost:8035 (SMTP on localhost:1035) |
| Postgres | localhost:5442 |

Ports are offset from the SIS stack (`sms_local`) so both can run at once. The demo accounts are listed in `seed_readme.md`.

Tests (run only what you touch):
```bash
docker exec -i oric_local-backend-1 python manage.py test rbac submissions
```

## Apps

| App | Responsibility |
|---|---|
| `audit` | `RequestIdMiddleware` (first), `ActivityEvent` (logins, exports, downloads, workflow), read API for the auditlog `LogEntry` |
| `people` | `User(AbstractUser)` (email login, generated username) + `Person` profile (name, photo, designation, department, ORCID, Scholar, bio). django-allauth adapters, `/me/profile/`, `/me/activity/`, People admin. `services/profile.provision_user()` creates User + Person + verified email |
| `org` | `Department`, `ReportingCycle` (fiscal year, open/closed, deadline), `TeamMember`, `ContactMessage`, public site content |
| `rbac` | Capability catalog, `AccessRole` (+ pillar restriction), `RoleAssignment` (+ department scope), abilities, admin API with escalation/lockout guards |
| `submissions` | **`registry.py`** (every form), `Submission` (one per person × pillar × cycle), `SectionEntry` (JSON validated against the registry), `EvidenceFile` (private), `ReviewEvent`, workflow service |
| `reports` | Home dashboard, scorecard summary (declared vs provided, money totals, funding pipeline, by department, trend), CSV/XLSX export |
| `notifications` | In-app notifications plus email on workflow events |

## API (all under `/api/v1/`)

| Area | Endpoints |
|---|---|
| Auth (allauth headless, **not** under /api/v1) | `/_allauth/browser/v1/`: `GET/DELETE auth/session`, `POST auth/login`, `auth/2fa/authenticate`, `auth/code/request` / `confirm`, `auth/password/request` / `reset`, `account/password/change`, `account/authenticators/totp`, `recovery-codes`, `auth/sessions`. Spec: `/_allauth/openapi.html` |
| Me | `GET/PATCH me/profile/` (JSON or multipart with `avatar`) · `GET me/activity/` · `GET me/abilities/` · `GET me/home/` |
| Forms | `GET forms/schema/` (public, the whole registry) |
| Returns | `submissions/` (list: `?pillar&status&cycle&cycle__year&department&mine=1&search`), `POST submissions/{id}/transition/ {action, comment}` with actions `submit`, `start_review`, `return`, `approve`, `reject`, `reopen` |
| Entries | `entries/?submission=` · `POST entries/` (multipart: `submission`, `section`, `data`=JSON, plus one file per file field) · `PATCH/DELETE entries/{id}/` |
| Evidence | `GET evidence/{id}/download/[?inline=1]` (permission-checked) |
| Reports | `reports/summary/?year&department&pillar&approved_only` · `reports/export/?pillar&year&department&status&format=csv\|xlsx` |
| Org | `departments/` · `reporting-cycles/` · `team-members/` · `contact-messages/` (+ `mark_handled`) · `public/site/` · `public/contact/` |
| People | `users/` (+ `set_password`, `deactivate`, `activate`) |
| RBAC | `rbac/capabilities/` · `rbac/roles/` (+ `GET/PUT {id}/capabilities/`) · `rbac/assignments/` (+ `activate`, `deactivate`) |
| Audit | `audit/activity/` · `audit/changes/` |
| Notifications | `notifications/` (+ `mark_read`, `mark_all_read`, `unread_count`) |

## Google & Apple sign-in

Both are **optional and off until their keys are set**: without keys the buttons are hidden and nothing else changes.

Same flow and rules as `sis_backend`. The policy lives in `people/adapters.ORICSocialAccountAdapter`:
- **Verified email only.** Google must assert `email_verified`.
- **Linking:** the Google identity is auto-linked to the existing ORIC account with that email. It never creates an account (signup is closed; unknown addresses are refused with a clear message).
- **Disabled accounts:** never reactivated, roles never changed.
- **Domains:** optional `GOOGLE_ALLOWED_DOMAINS` (for example `neduet.edu.pk`).
- **Per-identity switch:** People admins can turn off one person's Google sign-in from the People drawer (`SocialAccountStatus`) without touching the account.
- **Audit:** every refusal is written to the audit trail.

**Apple** follows the same adapter rules and adds Apple's quirks:
- **Email only on first sign-in.** Apple sends the email only on the first authorization; returning Apple users are matched by their linked identity.
- **Relay addresses.** "Hide My Email" relay addresses get a specific refusal telling the person to sign in with their password and connect Apple from their profile.
- **Flow:** a full-page server redirect, the same choice SIS made. The browser form-POSTs to `/_allauth/browser/v1/auth/provider/redirect` and goes to Apple. Apple form-posts back to Django at `/accounts/apple/login/callback/` (allauth bridges the SameSite cookie gap), and the browser lands on `/sign-in`, or on `/profile?tab=security` for connect. Failures come back as `?error=<code>`, which are mapped to readable messages in `ORIC-frontend/lib/auth/social-errors.ts`.

Apple setup:
1. In Apple Developer → Identifiers, create a **Services ID** (this is the client id) and enable *Sign in with Apple*.
2. Set the Return URL to `https://<portal-domain>/accounts/apple/login/callback/`. Apple requires a live HTTPS domain, so this can't be tested on plain localhost.
3. Under Keys, create a *Sign in with Apple* key.
4. Set `APPLE_OAUTH_CLIENT_ID`, `APPLE_TEAM_ID`, `APPLE_KEY_ID`, and `APPLE_PRIVATE_KEY` (the .p8 contents, with `
` for newlines). Put the same Services ID in the frontend's `NEXT_PUBLIC_APPLE_CLIENT_ID` (frontend `.env.local`) to show the button.

Google setup: create an OAuth 2.0 **Web application** client in Google Cloud Console and add each portal origin (`http://localhost:3000`, production URL) under *Authorized JavaScript origins*. Then set `GOOGLE_OAUTH_CLIENT_ID` (and optionally `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_ALLOWED_DOMAINS`) in the environment before `docker compose up`. Put the same client ID in the frontend's `NEXT_PUBLIC_GOOGLE_CLIENT_ID` (frontend `.env.local`). Without it, the Google button is simply hidden. People link or unlink Google from **Profile → Sign-in & security → Connected accounts**.

## Workflow

```
draft ──submit──▶ submitted ──start_review──▶ under_review ──approve──▶ approved
  ▲                   │  └──────────approve / reject──────────┘     └──reject──▶ rejected
  └──── returned ◀────┴──return (comment required)                  reopen ◀── approved/rejected
```
- **Submit:** owner only, while the cycle is open and before the deadline. Every count declared in the header must have that many entries.
- **Edit:** the owner can edit while the return is draft or returned. Staff with `submission.change` can edit anything not yet approved.
- **Notifications:** submitting notifies reviewers in scope (department + pillar). Every decision notifies the owner.

## Adding or changing a form field
1. Edit `submissions/registry.py`.
2. Run `docker exec -i oric_local-backend-1 python manage.py export_registry` to refresh the knowledge docs.
3. The frontend picks it up automatically from `forms/schema/`.

## Adding a capability
Add it in `rbac/capability_catalog.py` (and to a `ROLE_DEFS` pattern if needed). Then ship a data migration like `rbac/migrations/0002_seed_catalog.py` that calls `sync_capabilities()` followed by an additive `seed_roles`. Without that migration the new key has no database row and nobody can ever hold it. Map the endpoint with `capability_map` / `required_capability`, otherwise `rbac/tests/test_coverage_guard.py` fails.
