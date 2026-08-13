# Deployment & Operations (Phase 10)

Production runbook for the Mentisrex Capital quant research OS. Assumes a single
Linux host (Ubuntu 22.04+) with Docker Engine + the compose plugin.

## 1. Host prep

```bash
sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin postgresql-client
sudo usermod -aG docker "$USER"   # re-login after this
git clone <repo> /opt/mentisrex && cd /opt/mentisrex
```

## 2. Secrets management

Config is read from the environment by `pydantic-settings` (`Settings`), which
**hard-crashes at startup** on missing/insecure prod values — `SECRET_KEY` and
`APP_DEBUG=false` are enforced when `ENVIRONMENT=production`.

- Never commit real secrets. `.gitignore` excludes `.env*` except `.env.example`.
- Create `/opt/mentisrex/.env.production` (mode `600`, owned by the deploy user)
  from `.env.example`; fill `SECRET_KEY`, `DATABASE_PASSWORD`, `ALPACA_*`.
  Generate the key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- Prefer Docker/host secret managers for anything shared: mount as files and
  point env vars at them, or use `docker secret` (Swarm) / your cloud KMS.
  The app only reads env vars, so any injector works.

## 3. Run the stack

```bash
export DATABASE_PASSWORD=...          # or rely on .env.production
docker compose --env-file .env.production up -d --build
docker compose ps                     # postgres + redis healthchecked, app after
alembic upgrade head                  # apply DB migrations
```

## 4. Monitoring

| Signal | Endpoint / source | Use |
|---|---|---|
| Liveness | `GET /health/live` | restart the container if it fails |
| Readiness | `GET /health/ready` | pull from LB until deps reachable |
| Metrics | `GET /metrics` (Prometheus text) | `mentisrex_up`, uptime, build_info |
| Logs | structured JSON (structlog) to stdout | ship via Docker log driver |
| Paper engine | `Health` counters + heartbeats + `AlertSink` | alert on `restarts`/`errors` |

Point Prometheus at `/metrics`; alert on `mentisrex_up == 0` or a jump in
`mentisrex_uptime_seconds` resetting (crash-loop). Container restarts are handled
by `restart: unless-stopped` in compose.

## 5. Backups

`scripts/backup.sh` runs `pg_dump` (custom format, compressed), **verifies** the
dump with `pg_restore --list`, then prunes older than `BACKUP_RETENTION_DAYS`.

```bash
# hourly via cron on the host
0 * * * * cd /opt/mentisrex && set -a && . ./.env.production && \
          BACKUP_DIR=/var/backups/mentisrex ./scripts/backup.sh >> /var/log/mentisrex-backup.log 2>&1
```

Restore: `./scripts/restore.sh /var/backups/mentisrex/<file>.dump` (destructive —
restore into a scratch DB first if unsure). Push `BACKUP_DIR` off-host (S3/restic)
for real durability.

## 6. CI/CD

- **CI** (`.github/workflows/ci.yml`): ruff + mypy, unit + integration tests,
  Docker build — on every push/PR.
- **CD** (`.github/workflows/cd.yml`): on a `vX.Y.Z` tag, builds and pushes an
  immutable image to `ghcr.io/<repo>`.
- **Deploy** (gated, manual — we never auto-deploy trading infra):

```bash
docker compose pull app && docker compose up -d app && alembic upgrade head
curl -fsS localhost:8000/health/ready   # smoke test before taking traffic
```

Roll back by pinning the previous image tag and re-running the two lines above.

## 7. The AI Research Assistant is advisory only

`mentisrex.assistant` reads papers/reports/code and writes hypotheses + reports.
It imports **no execution path** (enforced by a test) and holds no capital — a
human researcher owns every accept/deploy decision. It is not on the trading
hot path and needs no special production wiring beyond the app itself.
```
