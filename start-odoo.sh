#!/usr/bin/env bash
# ── Robust Odoo starter for Railway ──
# Odoo refuses db_user=postgres → create odoo_user via admin, then run Odoo with it
# Dockerfile runs as non-root 'odoo' user

log(){ echo "[odoo $(date +%T)] $*"; }
die(){ echo "[odoo $(date +%T)] FATAL: $*" >&2; exit 1; }

trap 'echo "[odoo] Script exited at line $LINENO with code $?" >&2' ERR
[ "${DEBUG:-0}" = "1" ] && set -x

# ════════════ ODOO BIN ════════════
ODOO_BIN=""
[ -x ./odoo-bin ] && ODOO_BIN=./odoo-bin
[ -z "$ODOO_BIN" ] && [ -x ./odoo/odoo-bin ] && ODOO_BIN=./odoo/odoo-bin
[ -n "$ODOO_BIN" ] || die "odoo-bin not found"
log "ODOO_BIN=$ODOO_BIN"

# ════════════ ADDONS PATH ════════════
ADDONS_PATH=""
[ -d ./addons ]         && ADDONS_PATH=./addons
[ -d ./odoo/addons ]    && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./odoo/addons"
[ -d ./addons_custom ]  && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./addons_custom"
log "ADDONS_PATH=$ADDONS_PATH"

ODOO_DATA_DIR="${ODOO_DATA_DIR:-/data}"

# ════════════ ADMIN DATABASE URL ════════════
# Railway provides DATABASE_URL with postgres superuser
ADMIN_URL="${DATABASE_URL:-${DATABASE_PRIVATE_URL:-${DATABASE_PUBLIC_URL:-}}}"

if [ -z "$ADMIN_URL" ] && [ -n "${PGHOST:-}" ]; then
  ADMIN_URL="postgresql://${PGUSER:-postgres}:${PGPASSWORD:-}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE:-railway}"
  log "Built ADMIN_URL from PG* vars"
fi
[ -n "$ADMIN_URL" ] || die "DATABASE_URL (or DATABASE_PRIVATE_URL / PG* vars) is required"

# ════════════ PARSE ADMIN URL ════════════
read -r ADMIN_HOST ADMIN_PORT ADMIN_USER ADMIN_PASS ADMIN_DB <<< "$(python3 -c "
import urllib.parse, os
u = urllib.parse.urlparse(os.environ.get('DATABASE_URL','') or os.environ.get('DATABASE_PRIVATE_URL','') or os.environ.get('DATABASE_PUBLIC_URL','') or '')
print(u.hostname or 'localhost', u.port or 5432, urllib.parse.unquote(u.username or 'postgres'), urllib.parse.unquote(u.password or ''), (u.path or '/railway').lstrip('/'))
")"

# SSL: internal → disable, external → require
SSLMODE=require
echo "$ADMIN_HOST" | grep -q "railway\.internal" && SSLMODE=disable

log "ADMIN: user=$ADMIN_USER host=$ADMIN_HOST port=$ADMIN_PORT db=$ADMIN_DB ssl=$SSLMODE"

# ════════════ WAIT FOR POSTGRES ════════════
log "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  if pg_isready -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -t 2 >/dev/null 2>&1; then
    log "PostgreSQL is ready (attempt $i)"
    break
  fi
  [ "$i" = "30" ] && die "PostgreSQL not reachable after 60s"
  sleep 2
done

PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
  -c "SELECT 1;" >/dev/null 2>&1 \
  || die "Cannot connect to admin DB"
log "Admin DB connection OK"

# ════════════ CREATE RUNTIME USER + DB ════════════
# Odoo refuses db_user='postgres', so we create a dedicated user
ODOO_DB_USER="${ODOO_DB_USER:-odoo}"
ODOO_DB_PASS="${ODOO_DB_PASS:-odoo_$(echo "$ADMIN_PASS" | md5sum | head -c 12)}"
ODOO_DB_NAME="${ODOO_DB_NAME:-odoo}"

log "Setting up runtime DB user=$ODOO_DB_USER db=$ODOO_DB_NAME"

# Create user (idempotent)
ESC_PASS=$(printf "%s" "$ODOO_DB_PASS" | sed "s/'/''/g")
PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
  -Atc "SELECT 1 FROM pg_roles WHERE rolname='${ODOO_DB_USER}'" 2>/dev/null | grep -q 1 \
  || PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
       -c "CREATE USER ${ODOO_DB_USER} WITH LOGIN PASSWORD '${ESC_PASS}';" 2>&1 \
  && log "User $ODOO_DB_USER ready" \
  || log "WARNING: Could not create user $ODOO_DB_USER"

# Update password (in case it changed)
PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
  -c "ALTER USER ${ODOO_DB_USER} WITH PASSWORD '${ESC_PASS}';" >/dev/null 2>&1 || true

# Create database (idempotent)
PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
  -Atc "SELECT 1 FROM pg_database WHERE datname='${ODOO_DB_NAME}'" 2>/dev/null | grep -q 1 \
  || PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
       -c "CREATE DATABASE ${ODOO_DB_NAME} OWNER ${ODOO_DB_USER};" 2>&1 \
  && log "Database $ODOO_DB_NAME ready" \
  || log "WARNING: Could not create database $ODOO_DB_NAME"

# Grant privileges
PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ADMIN_DB" \
  -c "GRANT ALL PRIVILEGES ON DATABASE ${ODOO_DB_NAME} TO ${ODOO_DB_USER};" >/dev/null 2>&1 || true

# Extensions (need superuser, target DB)
PGPASSWORD="$ADMIN_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ADMIN_USER" -d "$ODOO_DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS unaccent;" \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null \
  && log "Extensions OK" \
  || log "WARNING: Extension install skipped"

# ════════════ VERIFY RUNTIME CONNECTION ════════════
PGPASSWORD="$ODOO_DB_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ODOO_DB_USER" -d "$ODOO_DB_NAME" \
  -c "SELECT current_user, current_database();" >/dev/null 2>&1 \
  || die "Cannot connect as $ODOO_DB_USER to $ODOO_DB_NAME"
log "Runtime DB connection OK ($ODOO_DB_USER@$ODOO_DB_NAME)"

# Clear env vars so Odoo doesn't pick up 'postgres' from PGUSER
unset PGUSER PGPASSWORD PGDATABASE PGHOST PGPORT

# ════════════ FIRST-RUN INIT ════════════
INIT_CHECK=$(PGPASSWORD="$ODOO_DB_PASS" psql -h "$ADMIN_HOST" -p "$ADMIN_PORT" -U "$ODOO_DB_USER" -d "$ODOO_DB_NAME" \
  -At -c "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" 2>/dev/null || echo "")

if [ "$INIT_CHECK" != "1" ]; then
  log "First run — initializing Odoo (may take 3-8 min)..."
  INIT_START=$(date +%s)
  "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
    -d "$ODOO_DB_NAME" \
    --db_host="$ADMIN_HOST" --db_port="$ADMIN_PORT" \
    --db_user="$ODOO_DB_USER" --db_password="$ODOO_DB_PASS" \
    --db_sslmode="$SSLMODE" \
    -i web \
    --without-demo=all --stop-after-init --workers=0 2>&1 \
    && log "Init completed in $(($(date +%s) - INIT_START))s" \
    || log "WARNING: Init exited with code $? after $(($(date +%s) - INIT_START))s — attempting start anyway"
else
  log "Schema already present, skipping init."
fi

# ════════════ START ODOO ════════════
HTTP_PORT="${PORT:-8069}"
log "Starting Odoo on 0.0.0.0:$HTTP_PORT (user=$ODOO_DB_USER db=$ODOO_DB_NAME)..."
exec "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
  -d "$ODOO_DB_NAME" \
  --db_host="$ADMIN_HOST" --db_port="$ADMIN_PORT" \
  --db_user="$ODOO_DB_USER" --db_password="$ODOO_DB_PASS" \
  --db_sslmode="$SSLMODE" \
  --db-filter="^${ODOO_DB_NAME}$" \
  ${ODOO_DATA_DIR:+--data-dir="$ODOO_DATA_DIR"} \
  --http-interface=0.0.0.0 \
  --http-port="$HTTP_PORT" \
  --proxy-mode \
  --workers=0 \
  --without-demo=all
