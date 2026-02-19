#!/usr/bin/env bash
set -euo pipefail

# Optional: DEBUG=1 로 세부 trace 활성화
[ "${DEBUG:-0}" = "1" ] && set -x

log(){ echo "[start-odoo] $*"; }
die(){ echo "[start-odoo][ERROR] $*" >&2; exit 1; }

# ---------------- ODOO BIN / ADDONS AUTO-DETECT ----------------
if [ -x ./odoo-bin ]; then
  ODOO_BIN=./odoo-bin
elif [ -x ./odoo/odoo-bin ]; then
  ODOO_BIN=./odoo/odoo-bin
else
  die "odoo-bin not found at ./odoo-bin or ./odoo/odoo-bin"
fi
log "Using ODOO_BIN: $ODOO_BIN"

ADDONS_PATH=""
[ -d ./addons ] && ADDONS_PATH=./addons
[ -d ./odoo/addons ] && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./odoo/addons"
[ -d ./addons_custom ] && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./addons_custom"
[ -n "$ADDONS_PATH" ] && log "Using ADDONS_PATH: $ADDONS_PATH"

ODOO_DATA_DIR="${ODOO_DATA_DIR:-/data}"

# ---------------- DB URL (ADMIN) ----------------
# 우선순위: ADMIN_DATABASE_URL > DATABASE_URL > DATABASE_PUBLIC_URL > (PG*로 조립)
ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-${DATABASE_URL:-${DATABASE_PUBLIC_URL:-}}}"

if [ -z "${ADMIN_DATABASE_URL:-}" ] && [ -n "${PGHOST:-}" ] && [ -n "${PGPORT:-}" ] \
   && [ -n "${PGUSER:-}" ] && [ -n "${PGPASSWORD:-}" ] && [ -n "${PGDATABASE:-}" ]; then
  ADMIN_DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"
  log "Built ADMIN_DATABASE_URL from PG* variables"
fi

[ -n "${ADMIN_DATABASE_URL:-}" ] || die "ADMIN_DATABASE_URL 또는 DATABASE_URL이 필요합니다."

# 내부/외부에 따른 SSL
if echo "$ADMIN_DATABASE_URL" | grep -q "postgres\.railway\.internal"; then
  ASSL=disable
else
  ASSL=require
fi

# 런타임 Odoo 접속 정보 (odoo_user/odoo DB 기본)
DB_NAME="${DB_NAME:-odoo}"
DB_USER="${DB_USER:-odoo_user}"
ODOO_DB_PASSWORD="${ODOO_DB_PASSWORD:-${DB_PASSWORD:-odoo_pass}}"
DB_PASS="${DB_PASS:-$ODOO_DB_PASSWORD}"

# 호스트/포트 안전 추출 + 기본값 강제
mapfile -t _HP < <(python3 - <<'PY'
import os, urllib.parse
u = urllib.parse.urlparse(os.environ.get("ADMIN_DATABASE_URL",""))
print(u.hostname or "")
print(u.port or "")
PY
)
DB_HOST="${_HP[0]:-}"
DB_PORT="${_HP[1]:-}"
[ -n "${DB_HOST:-}" ] || DB_HOST=postgres.railway.internal
if [ -z "${DB_PORT:-}" ] || ! [[ "$DB_PORT" =~ ^[0-9]+$ ]]; then DB_PORT=5432; fi

export PGSSLMODE=$([ "$ASSL" = "disable" ] && echo disable || echo require)

# (가시적 확인용; 필요 없으면 지워도 무방)
echo "ADMIN_DATABASE_URL present? $([ -n "${ADMIN_DATABASE_URL:-}" ] && echo yes || echo no)"
echo "DATABASE_URL present? $([ -n "${DATABASE_URL:-}" ] && echo yes || echo no)"

log "ADMIN URL detected (ssl=$ASSL)"
log "RUNTIME -> user=$DB_USER host=$DB_HOST port=$DB_PORT db=$DB_NAME ssl=$PGSSLMODE"

# ---------------- WAIT FOR POSTGRES (ADMIN URL로 직접 확인) ----------------
log "Waiting for PostgreSQL (admin url)..."
for i in {1..30}; do
  if psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "select 1" >/dev/null 2>&1; then
    break
  fi
  log "  retry $i/30"; sleep 2
done
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "select 1;" >/dev/null \
  || die "ADMIN 접속 실패 (URL로 연결 불가)"

# ---------------- BOOTSTRAP: ROLE/DB/EXTENSIONS ----------------
log "Bootstrap: role/database/extensions"

# 1) 사용자 생성(없을 때만)
ESC_PASS=$(printf "%s" "$DB_PASS" | sed "s/'/''/g")
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  || psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE USER ${DB_USER} WITH LOGIN PASSWORD '${ESC_PASS}';"

# 2) DB 생성(없을 때만)
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# 3) 확장 설치(대상 DB로 접속 전환)
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 \
  -c "\connect ${DB_NAME}" \
  -c "CREATE EXTENSION IF NOT EXISTS unaccent;" \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
  -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" || true

# ---------------- SWITCH TO RUNTIME (odoo_user) ----------------
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASS" PGDATABASE="$DB_NAME"

log "Testing runtime connection (odoo_user -> $DB_NAME)"
psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -v ON_ERROR_STOP=1 -c \
  "select current_user,current_database();" >/dev/null || die "RUNTIME 접속 실패(odoo_user)"

# ---------------- INITIALIZE BASE SCHEMA (FIRST RUN ONLY) ----------------
INIT_CHECK=$(psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -At -c \
  "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" || true)

if [ "$INIT_CHECK" != "1" ]; then
  # 이전 실패로 DB가 불완전한 상태일 수 있으므로 리셋
  TABLE_COUNT=$(psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -At -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public';" || echo "0")
  if [ "$TABLE_COUNT" != "0" ] && [ "$TABLE_COUNT" != "" ]; then
    log "Incomplete DB detected ($TABLE_COUNT tables but no ir_module_module). Dropping and recreating..."
    psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c \
      "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB_NAME}' AND pid <> pg_backend_pid();" || true
    sleep 1
    psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${DB_NAME};"
    psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
    psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 \
      -c "\connect ${DB_NAME}" \
      -c "CREATE EXTENSION IF NOT EXISTS unaccent;" \
      -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;" \
      -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" || true
  fi
  log "Initializing Odoo base+web schema..."
  INIT_START=$(date +%s)
  "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
    -i web \
    --database="$PGDATABASE" \
    --db_host="$PGHOST" --db_port="$PGPORT" \
    --db_user="$PGUSER" --db_password="$PGPASSWORD" \
    --db_sslmode="$PGSSLMODE" \
    --without-demo=all --stop-after-init --workers=0
  INIT_END=$(date +%s)
  log "Schema initialized in $((INIT_END - INIT_START))s."
else
  log "Odoo base schema already present. Skipping initialization."
fi

# ---------------- START ODOO ----------------
HTTP_PORT="${PORT:-8069}"
log "Starting Odoo on port $HTTP_PORT (workers=0) ..."
exec "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
  --database="$PGDATABASE" \
  --db_host="$PGHOST" --db_port="$PGPORT" \
  --db_user="$PGUSER" --db_password="$PGPASSWORD" \
  --db_sslmode="$PGSSLMODE" \
  --db-filter="^${PGDATABASE}$" \
  ${ODOO_DATA_DIR:+--data-dir="$ODOO_DATA_DIR"} \
  --http-port="$HTTP_PORT" \
  --proxy-mode \
  --workers=0 \
  --without-demo=all
