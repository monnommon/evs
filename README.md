# EVS — Electronic Voting System

Django 5 backend for self-hosted polls with anonymous (link-based) and
identified voting, role-based access, and an append-only hash-chained audit
log for immutable results.

## Stack

- Django 5.2 + DRF + SimpleJWT (15-min access / 7-day refresh tokens)
- PostgreSQL 15 (SQLite fallback when `DATABASE_URL` is unset)
- Gunicorn + Nginx via Docker Compose

## Quick start (Docker)

```bash
cd evs/
export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(50))')
export DB_PASSWORD=$(python -c 'import secrets; print(secrets.token_hex(16))')
docker compose up --build
```

- App: `http://localhost/` (via nginx; gunicorn on `web:8000`)
- Django admin: `/admin/` — create the first superuser:
  `docker compose exec web python manage.py createsuperuser --email you@example.com`
- Migrations run automatically on container start.

## Local development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate      # SQLite when DATABASE_URL unset
python manage.py runserver
```

Create canonical roles (Admin / Secretariat / User) + a superuser:

```bash
python manage.py shell -c "from accounts.models import Role; Role.ensure_defaults()"
python manage.py createsuperuser --email admin@example.com
```

## API surface

**Auth** (`/api/auth/…`): `register/`, `login/`, `logout/` (refresh-token
blacklist), `password-reset/`, `token/refresh/`, `me/`.

**Admin** (`/api/admin/…`, requires Admin role):
`polls/` CRUD, `polls/{id}/results/` (tally + audit trail),
`polls/{id}/finalize/` (immutable close; terminal audit entry),
`polls/{id}/generate-link/` (anonymous voting links),
`users/`, `users/{id}/role/`, `roles/`, `audit/verify/` (recompute the chain).

**Authenticated voting**: `GET /polls/active/`, `GET /polls/{id}/`,
`POST /polls/{id}/vote/`, `GET /my-votes/`.

**Anonymous voting**: `GET /poll/{token}/`, `POST /poll/{token}/vote/`
(requires a browser `fingerprint`, stored as SHA-256; one vote per
fingerprint per poll, one vote per link), `GET /poll/{token}/confirm/`.

## Immutability

Every significant event (poll created/updated, vote cast, role change,
finalization, …) is appended to `audit_auditlog` with
`hash_N = SHA256(canonical(event) + hash_{N-1})`. The ORM blocks
update/delete on `AuditLog`; `GET /api/admin/audit/verify/` recomputes the
whole chain and reports any break. Results become immutable after
`finalize`.

## Tests

```bash
python manage.py test evs.tests
```