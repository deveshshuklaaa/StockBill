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

### Quick tunnel (testing, no domain yet)

```bash
docker compose -f docker-compose.prod.yml --profile quick-tunnel up -d
docker compose -f docker-compose.prod.yml logs cloudflared-quick | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com'
```

The hostname is random and changes whenever the `cloudflared-quick`
container restarts (including a server reboot). Put it in `ALLOWED_HOSTS`
and `CSRF_TRUSTED_ORIGINS` (as `https://...`), then
`docker compose -f docker-compose.prod.yml up -d backend` to reload the
settings. Switch to the named tunnel (profile `tunnel`) before real use.

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
  `5/min`); see "Client address and login throttling" below.
- `/admin/` exists only with `ENABLE_DJANGO_ADMIN=true`.
- `/api/health/` needs no login and returns only `{"status": "ok"}` (or 503).
  Behind Cloudflare Access, an external monitor needs an Access bypass (or
  service token) for that one path.

## Client address and login throttling

Request path in production:

```
client -> Cloudflare edge -> cloudflared (container) -> nginx :80 -> Gunicorn
```

Django's `REMOTE_ADDR` is always the nginx container, so throttling on it
would put every user in one bucket: one person's wrong passwords would lock
out the whole shop. The throttle therefore needs the real client address,
and it must come from something a client cannot forge:

- **`CF-Connecting-IP`** is set by Cloudflare to the address that connected
  to it, overwriting anything the client sent. With
  `TRUST_CF_CONNECTING_IP=True`, the login throttle
  (`accounts/throttling.py`) keys on it (after checking it parses as an IP
  address).
- **Only cloudflared can deliver that header.** nginx has two listeners:
  `:80` is the tunnel target and is not published, so only containers on the
  compose network (cloudflared) reach it; it passes `CF-Connecting-IP`
  through unchanged. `:8081` is published as `127.0.0.1:8080` for local
  checks and SSH port-forwarding, and strips the header. No path except the
  tunnel can choose a throttle key. Requests on the loopback listener share
  one bucket (nginx's address), which only matters for someone already on
  the server.
- **`NUM_PROXIES=0`** (the default). With 0, DRF ignores
  `X-Forwarded-For` and uses `REMOTE_ADDR` whenever `CF-Connecting-IP` is
  not trusted. Other values are worse for this chain:
  - unset (`None`, DRF's own default) keys on the *entire*
    `X-Forwarded-For` string as sent, so a client could send a new value
    on every attempt and never be throttled;
  - `1` or more picks an entry counted from the end. Cloudflare appends the
    real client to whatever `X-Forwarded-For` the client sent, and
    cloudflared/nginx may add hops of their own, so the right index cannot
    be confirmed until the tunnel runs. A wrong index either lets clients
    choose their key or puts everyone in one bucket.
- Keep `TRUST_CF_CONNECTING_IP` off anywhere that is not behind this exact
  setup (dev PC, shop PC): there the header would be client-controlled.
- nginx's tunnel access log records `CF-Connecting-IP` first on each line.

Phase 4 check: from two different networks (e.g. shop Wi-Fi and a phone on
mobile data), fail the login 6 times on one; the other must still log in.

## Building for ARM64 from another machine

The images are multi-arch (amd64 and arm64). To check an arm64 build from an
x86 PC (slow, emulated):

```bash
docker buildx build --platform linux/arm64 -f Dockerfile.prod --target backend .
docker buildx build --platform linux/arm64 -f Dockerfile.prod --target nginx .
```

On the Oracle Ampere VM itself, the normal `docker compose build` is native.
