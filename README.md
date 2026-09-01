# EVS — Electronic Voting System

Self-hosted voting platform built on Django 5 + PostgreSQL with anonymous
(link-based) and identified voting, role-based access, and an append-only
hash-chained audit log for immutable results. The frontend is server-rendered
Django templates with a small dependency-free JS layer (`static/js/evs.js`).

- **Admin panel** (`/panel/`): create/manage polls, one-time voting links,
  role management, results with audit trail, chain-integrity indicator.
- **Public voting**: anonymous one-time links (browser-fingerprint dedupe)
  or authenticated email/password voting.
- **Immutability**: every event is appended to a SHA-256 hash chain;
  tampering is detectable via `/api/admin/audit/verify/`.

## Contents
1. [Requirements](#requirements)
2. [Quick start — Docker (production-ish)](#quick-start--docker)
3. [Local development (no Docker)](#local-development-no-docker)
4. [Configuration reference](#configuration-reference)
5. [First steps after install](#first-steps-after-install)
6. [How to run a vote (end-to-end)](#how-to-run-a-vote-end-to-end)
7. [API surface](#api-surface)
8. [Security notes](#security-notes)
9. [Tests](#tests)
10. [Troubleshooting](#troubleshooting)

---

## Requirements

| Component | Version | Notes |
|---|---|---|
| Docker + Compose | any recent | for the Docker path |
| Python | 3.11+ | for the local dev path |
| PostgreSQL | 15 | only for bare-metal installs; Docker ships it; local dev falls back to SQLite |

---

## Quick start — Docker

Three containers: `nginx` (reverse proxy, port 80) → `web` (gunicorn) →
`db` (PostgreSQL 15). Migrations and static files are applied automatically
on container start.

```bash
git clone https://github.com/monnommon/evs.git
cd evs

# Generate secrets (required for a sane production setup)
export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(50))')
export DB_PASSWORD=$(python -c 'import secrets; print(secrets.token_hex(16))')
export ALLOWED_HOSTS=yourdomain.com          # comma-separated; NOT * in production
export DEBUG=false

docker compose up --build -d
```

- App: `http://yourdomain.com/` (nginx → gunicorn)
- Create the first superuser:

  ```bash
  docker compose exec web python manage.py createsuperuser --email you@example.com
  ```
- Logs / stop / wipe:

  ```bash
  docker compose logs -f web
  docker compose down            # stop (data persists in the postgres_data volume)
  docker compose down -v        # stop AND delete the database
  ```

**Recommended**: put the exports in a `.env` file next to `docker-compose.yml`
(compose reads it automatically):

```env
SECRET_KEY=<long random hex>
DB_PASSWORD=<random hex>
ALLOWED_HOSTS=vote.example.com
DEBUG=false
```

`.env` is in `.gitignore` — never commit it.

---

## Local development (no Docker)

```bash
git clone https://github.com/monnommon/evs.git
cd evs

python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# SQLite is used automatically when DATABASE_URL is unset
python manage.py migrate

# Canonical roles (Admin / Secretariat / User)
python manage.py shell -c "from accounts.models import Role; Role.ensure_defaults()"

# Admin user (interactive) — password must be 8+ chars
python manage.py createsuperuser --email admin@example.com

python manage.py runserver      # http://127.0.0.1:8000/
```

To develop against PostgreSQL instead of SQLite:

```bash
export DATABASE_URL=postgresql://evs:evsdev@localhost:5432/evs
python manage.py migrate
```

---

## Configuration reference

All configuration is via environment variables (see `evs/settings.py`).

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | insecure dev key | **Set in production.** `python -c 'import secrets; print(secrets.token_hex(50))'` |
| `DEBUG` | `false` | Keep `false` in production. |
| `ALLOWED_HOSTS` | `*` | Comma-separated domains/IPs the app answers on. Narrow it in production. |
| `DATABASE_URL` | *(unset → SQLite)* | e.g. `postgresql://user:pass@host:5432/dbname` |
| `DB_PASSWORD` | `evsdev` | Used by docker-compose for the Postgres container and `DATABASE_URL`. |
| `DB_CONN_MAX_AGE` | `60` | Persistent-DB-connection age in seconds. |
| `EMAIL_BACKEND` | console backend | Set to `django.core.mail.backends.smtp.EmailBackend` to actually send mail (needed for password reset). |
| `EMAIL_HOST` / `EMAIL_PORT` | `""` / `587` | SMTP server + port. |
| `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` | `""` | SMTP credentials. |
| `EMAIL_USE_TLS` | `true` | STARTTLS on port 587; set `false` + `EMAIL_PORT=465` semantics vary by provider. |
| `DEFAULT_FROM_EMAIL` | `evs-noreply@example.com` | From-address for outgoing mail. |
| `FRONTEND_URL` | `http://localhost` | Base URL used in generated links (e.g. password reset). |
| `STATIC_ROOT` | `./staticfiles` | Where `collectstatic` gathers files. |
| `TIME_ZONE` | `Europe/Moscow` | Display timezone (dates are stored as UTC internally). |
| `SECURE_SSL_REDIRECT` | `false` | With `DEBUG=false` + TLS proxy: redirect all HTTP→HTTPS. Secure cookies and HSTS are enabled automatically when `DEBUG=false`. |
| `REGISTRATION_OPEN` | `true` | `false` closes self-registration (403) — accounts are then created via Django admin. No email verification is implemented either way. |

### Email / SMTP (password reset)

Out of the box mail goes to the console (docker logs / terminal). To send
real mail:

```env
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.example.com
EMAIL_PORT=587
EMAIL_USE_TLS=true
EMAIL_HOST_USER=smtp-login
EMAIL_HOST_PASSWORD=smtp-password
DEFAULT_FROM_EMAIL=votes@example.com
```

---

## First steps after install

1. Log into the **admin panel** at `/panel/` with the superuser email/password.
2. The superuser has all rights. Create day-to-day accounts via
   `POST /api/auth/register/` and assign roles in `/panel/users/`:
   - **Admin** — full rights (create polls, finalize, manage users/roles)
   - **Secretariat** — read results (panel results pages + public results)
   - **User** — authenticated voting only
3. Change the password-reset sender (`DEFAULT_FROM_EMAIL`) before inviting
   real users if you plan to use password reset.

---

## How to run a vote (end-to-end)

1. **Create a poll** — `/panel/` → *New poll*: title, description, start/end
   time (displayed in the configured `TIME_ZONE`), `anonymous` on/off,
   `multiple options` on/off, one option per line. Status `active` opens
   voting immediately.
2. **Invite voters**:
   - Anonymous: `/panel/` → *Generate link* — produces a one-time URL
     `/poll/<token>/`. Set the count field to N to generate N links at once
     and download them as CSV (token, url, expires). Each link allows exactly
     one vote; the same browser can't vote twice in the same poll
     (fingerprint dedupe).
   - Identified: voters register (`/api/auth/register/`) and vote via
     `POST /polls/{id}/vote/` with their JWT.
3. **During the vote** — progress visible at `/panel/` (Admin) or results
   pages (Secretariat). Voters see a confirmation page after voting.
4. **Finish** — *Finalize* on the panel: the poll freezes (further votes
   rejected with 409), a terminal audit entry is written, results become
   immutable. Results page: `/panel/polls/{id}/results/` or public
   `/polls/{id}/results/` (only once closed/finalized).
5. **Verify integrity** — the dashboard shows the audit-chain indicator;
   API: `GET /api/admin/audit/verify/` → `{"chain_valid": true, …}`.

---

## API surface

All API endpoints live under `/api/…` and return JSON. The HTML pages
(`/panel/…`, `/poll/…`, `/polls/…`) are server-rendered; the same public
URLs return JSON when the client sends `Accept: application/json`
(dual-mode views).

**Auth** (`/api/auth/…`): `register/`, `login/`, `logout/`
(refresh-token blacklist), `password-reset/`, `password-reset/confirm/`,
`token/refresh/`, `me/`.
SimpleJWT: 15-min access / 7-day refresh tokens.

**Admin** (`/api/admin/…`, requires Admin role): `polls/` CRUD,
`polls/{id}/results/` (tally + audit trail), `polls/{id}/finalize/`,
`polls/{id}/generate-link/`, `users/`, `users/{id}/role/`, `roles/`,
`audit/verify/`.

**Authenticated voting**: `GET /polls/active/`, `GET /polls/{id}/`,
`POST /polls/{id}/vote/`, `GET /my-votes/`.

**Anonymous voting**: `GET /poll/{token}/`, `POST /poll/{token}/vote/`
(fields: `fingerprint` — computed client-side, stored as SHA-256; one vote
per fingerprint per poll, one vote per link), `GET /poll/{token}/confirm/`.

---

## Security notes

- **Always** set `SECRET_KEY`, `ALLOWED_HOSTS`, `DEBUG=false` in production.
  The bundled `docker-compose.yml` now **refuses to start** without them.
  With `DEBUG=false` the app also enables secure cookies and HSTS; set
  `SECURE_SSL_REDIRECT=true` when a TLS proxy sits in front.
- **Ballot secrecy.** The audit chain records *that* a vote happened
  (`vote_cast` / `anonymous_vote_cast` with a ballot counter), never *what*
  was chosen: no vote ids, no option ids in audit payloads, and the
  `GET /poll/{token}/confirm/` JSON returns only `confirmed`, not the
  ballot. Result integrity is proven by the `result_finalized` entry (the
  tally) plus DB constraints — not by per-vote audit data. A regression
  test (`test_ballot_secrecy_invariant`) enforces this.
- The audit log is append-only: the ORM blocks `AuditLog` update/delete;
  the chain hash makes even raw-DB edits detectable (`audit/verify/`).
- Anonymous dedupe: the **one-time link is the guarantee**; the browser
  fingerprint (SHA-256 of client signals, sent only when `crypto.subtle` is
  available) is a best-effort secondary signal against casual double-voting
  on shared links, not a defense against determined attackers.
- HTTPS: terminate at your reverse proxy (nginx config here serves port 80
  — put an TLS proxy/CDN in front for production).
- Passwords are hashed by Django's PBKDF2; JWT refresh tokens are
  blacklisted on logout. Public auth endpoints and voting endpoints are
  rate-limited (`auth`: 30/min per IP, `vote`: 120/min per IP).
- Identified voting requires the role permission `vote` (the default `User`
  role has it; you can strip it from custom roles to lock voting down).

---

## Tests

```bash
# local venv
python manage.py test               # full suite (80 tests)

# docker
docker compose exec web python manage.py test
```

CI runs the suite plus `manage.py check --deploy` on Python 3.11/3.12
(`.github/workflows/ci.yml`).

### Scheduled poll lifecycle

Drafts auto-activate at `start_at` and active polls auto-close at `end_at` —
but only if something runs the scheduler. Any one of:

```bash
# host cron, every 5 minutes
*/5 * * * * cd /path/to/evs && python manage.py poll_lifecycle

# or inside the docker web container (cron or a loop), e.g.:
docker compose exec web python manage.py poll_lifecycle
```

Without it, polls open/close only when an admin flips the status by hand.

### Results visibility

Each poll has a `results_visibility` setting (`public` by default):
`hidden` returns 403 on the public results URL for anyone without the
`view_results`/`create_poll` permissions — for internal votes.

### Multi-choice percentages

Percentages are computed **per voter** (an option chosen by both voters in a
two-voter poll shows 100%), not per selection — in multi-choice polls the
selection total exceeds the voter count.

Coverage highlights: auth flows, duplicate-vote prevention (DB constraints
+ fingerprint dedupe), link expiry/reuse, finalize lock, hash-chain
verification incl. tamper detection, panel permission gates (incl.
view-level login regression tests).

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied (publickey)` on clone | Use HTTPS clone or add your SSH key to GitHub. |
| `docker compose up` fails on `db` healthcheck | Check `DB_PASSWORD` is set consistently; wipe with `docker compose down -v` and retry. |
| 502 from nginx | `web` container still booting (migrations run first) or crashed — check `docker compose logs web` and `docker compose ps` (web should show `healthy`). |
| `web` exits right after start | Usually static-volume permissions: wipe the old volume (`docker compose down -v`) and `docker compose up --build` again — the image now pre-creates `/app/staticfiles` owned by the app user. |
| Password-reset mails not arriving | `EMAIL_BACKEND` still console; switch to SMTP (see config reference). |
| `bad request (400)` on pages behind a domain | `ALLOWED_HOSTS` doesn't include your domain — restart with it set. |
| Static files 404 | `collectstatic` runs on boot in Docker; locally run `python manage.py collectstatic`. |
