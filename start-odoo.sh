#!/usr/bin/env bash
# ── Robust Odoo starter for Railway ──
# Key: use DATABASE_URL credentials directly, no CREATE USER/DB

log(){ echo "[odoo $(date +%T)] $*"; }
die(){ echo "[odoo $(date +%T)] FATAL: $*" >&2; exit 1; }

# Catch unexpected exits for debugging
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

# ════════════ DATABASE URL ════════════
# Railway: DATABASE_URL, DATABASE_PRIVATE_URL, DATABASE_PUBLIC_URL
DB_URL="${DATABASE_URL:-${DATABASE_PRIVATE_URL:-${DATABASE_PUBLIC_URL:-}}}"

# Fallback: build from PG* vars
if [ -z "$DB_URL" ] && [ -n "${PGHOST:-}" ]; then
  DB_URL="postgresql://${PGUSER:-postgres}:${PGPASSWORD:-}@${PGHOST}:${PGPORT:-5432}/${PGDATABASE:-railway}"
  log "Built DB_URL from PG* vars"
fi

[ -n "$DB_URL" ] || die "DATABASE_URL (or DATABASE_PRIVATE_URL / PG* vars) is required"

# ════════════ PARSE DB URL ════════════
read -r DB_HOST DB_PORT DB_USER DB_PASS DB_NAME <<< "$(python3 -c "
import urllib.parse, os
u = urllib.parse.urlparse(os.environ.get('DATABASE_URL','') or os.environ.get('DATABASE_PRIVATE_URL','') or os.environ.get('DATABASE_PUBLIC_URL','') or '$DB_URL')
print(u.hostname or 'localhost', u.port or 5432, urllib.parse.unquote(u.username or 'postgres'), urllib.parse.unquote(u.password or ''), (u.path or '/railway').lstrip('/'))
")"

# SSL: internal → disable, external → require
SSLMODE=require
echo "$DB_HOST" | grep -q "railway\.internal" && SSLMODE=disable
export PGSSLMODE="$SSLMODE"

log "DB: user=$DB_USER host=$DB_HOST port=$DB_PORT db=$DB_NAME ssl=$SSLMODE"

# ════════════ WAIT FOR POSTGRES ════════════
log "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
  if pg_isready -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -t 2 >/dev/null 2>&1; then
    log "PostgreSQL is ready (attempt $i)"
    break
  fi
  [ "$i" = "30" ] && die "PostgreSQL not reachable after 60s"
  sleep 2
done

# Verify actual connection
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "SELECT 1;" >/dev/null 2>&1 \
  || die "Cannot connect to $DB_NAME as $DB_USER"

log "DB connection OK"

# ════════════ EXTENSIONS (non-fatal) ════════════
log "Installing extensions..."
PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -c "CREATE EXTENSION IF NOT EXISTS unaccent;" \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" 2>/dev/null \
  && log "Extensions OK" \
  || log "WARNING: Extension install skipped (not superuser?)"

# ════════════ FIRST-RUN INIT ════════════
INIT_CHECK=$(PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" \
  -At -c "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" 2>/dev/null || echo "")

if [ "$INIT_CHECK" != "1" ]; then
  log "First run detected — initializing Odoo (this may take 3-8 min)..."
  INIT_START=$(date +%s)
  "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
    -d "$DB_NAME" \
    --db_host="$DB_HOST" --db_port="$DB_PORT" \
    --db_user="$DB_USER" --db_password="$DB_PASS" \
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
log "Starting Odoo on 0.0.0.0:$HTTP_PORT ..."
exec "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
  -d "$DB_NAME" \
  --db_host="$DB_HOST" --db_port="$DB_PORT" \
  --db_user="$DB_USER" --db_password="$DB_PASS" \
  --db_sslmode="$SSLMODE" \
  --db-filter="^${DB_NAME}$" \
  ${ODOO_DATA_DIR:+--data-dir="$ODOO_DATA_DIR"} \
  --http-interface=0.0.0.0 \
  --http-port="$HTTP_PORT" \
  --proxy-mode \
  --workers=0 \
  --without-demo=all
