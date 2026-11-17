# StockBill production stack

> **Status: checked on the development PC only (Docker Desktop, test data).
> Not yet run on the Oracle VPS. Treat every command here as untested on the
> real server until Phase 4 (staging) passes.**

Four containers, defined in `docker-compose.prod.yml` at the repository root:

| Service | What it does | Network exposure |
|---|---|---|
| `db` | PostgreSQL (`POSTGRES_VERSION`, default 16), data in the `stockbill_pgdata` volume | none (compose network only) |
| `backend` | Django + Gunicorn (`Dockerfile.prod`, target `backend`), non-root user | none (compose network only) |
| `nginx` | Serves the built React app, proxies `/api/` (and `/admin/`) to Gunicorn | `127.0.0.1:8080` only |
| `cloudflared` | Cloudflare Tunnel; optional, profile `tunnel` | outbound only |

Migrations are **never** run automatically. Run them explicitly after every
deploy that brings new ones.

All commands run from the repository root on the server.

## First-time setup

```bash
cp .env.production.example .env.production
# Edit .env.production: SECRET_KEY, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS,
# POSTGRES_PASSWORD / DB_PASSWORD (same value), TUNNEL_TOKEN.
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # a SECRET_KEY
chmod 600 .env.production

docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d db
docker compose -f docker-compose.prod.yml run --rm backend python manage.py migrate
docker compose -f docker-compose.prod.yml run --rm backend python manage.py createcachetable
docker compose -f docker-compose.prod.yml run --rm backend python manage.py createsuperuser
```

`createcachetable` is also done by migration `accounts/0002`; running it again
is harmless. The user created by `createsuperuser` gets the `staff` role by
default; make it an admin with:

```bash
docker compose -f docker-compose.prod.yml run --rm backend python manage.py shell -c "from accounts.models import User; User.objects.filter(username='ADMIN_USERNAME').update(role='admin')"
```

## Start, stop, status, logs

```bash
docker compose -f docker-compose.prod.yml up -d                      # without the tunnel
docker compose -f docker-compose.prod.yml --profile tunnel up -d     # with the tunnel
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs -f --tail=200 backend
docker compose -f docker-compose.prod.yml logs -f --tail=200 nginx
docker compose -f docker-compose.prod.yml --profile tunnel down       # stop (data volume kept)
```

Never add `-v` to `down`: that deletes the database volume.

## Deploying a new version

```bash
git pull
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml run --rm backend python manage.py migrate
docker compose -f docker-compose.prod.yml --profile tunnel up -d
```

Take a `pg_dump` before any deploy that includes migrations.

## Checks

```bash
curl -s http://127.0.0.1:8080/api/health/          # {"status": "ok"}
docker compose -f docker-compose.prod.yml ps        # only nginx shows a port: 127.0.0.1:8080->80/tcp
```

From your own PC, without exposing anything:
`ssh -L 8080:127.0.0.1:8080 <user>@<vps>` then open `http://127.0.0.1:8080`.

## Settings reference

Every variable is listed with a placeholder in `.env.production.example`.
Important behaviour:

- `DEBUG` defaults to **False**. With DEBUG off, Django refuses to start if
  `SECRET_KEY` is missing or a placeholder.
- `SECURE_SSL_REDIRECT` is off on purpose: TLS ends at Cloudflare and nginx
  passes `X-Forwarded-Proto` on, which Django trusts.
- Login tokens (django-rest-knox) expire `TOKEN_TTL_HOURS` after login
  (default 168 = 7 days) and are not extended by use. Each login is its own
  token, so one account can be signed in on the shop PC and phones at once.
  Logout revokes only that device's token; `POST /api/auth/logoutall/`
  revokes every device of the calling user. With `ENABLE_DJANGO_ADMIN=true`,
  an admin (Django `is_staff` user) can list and revoke sessions under
  Knox > Auth tokens.
- After the first deploy with knox, existing logins stop working once:
  everyone signs in again.
- Login is throttled per client address (`LOGIN_THROTTLE_RATE`, default
  `5/min`). nginx sends Cloudflare's `CF-Connecting-IP` as the client address
  and `NUM_PROXIES=1` makes Django use it.
- `/admin/` exists only with `ENABLE_DJANGO_ADMIN=true`.
- `/api/health/` needs no login and returns only `{"status": "ok"}` (or 503).
  Behind Cloudflare Access, an external monitor needs an Access bypass (or
  service token) for that one path.

## Building for ARM64 from another machine

The images are multi-arch (amd64 and arm64). To check an arm64 build from an
x86 PC (slow, emulated):

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.prod --target backend .
docker buildx build --platform linux/arm64 -f Dockerfile.prod --target nginx .
```

On the Oracle Ampere VM itself, the normal `docker compose build` is native.
