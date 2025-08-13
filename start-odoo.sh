#!/usr/bin/env bash
set -euo pipefail

log(){ echo "[start-odoo] $*"; }
die(){ echo "[start-odoo][ERROR] $*" >&2; exit 1; }

# ---------- odoo-bin / addons 자동 탐지 ----------
if [ -x ./odoo-bin ]; then ODOO_BIN=./odoo-bin
elif [ -x ./odoo/odoo-bin ]; then ODOO_BIN=./odoo/odoo-bin
else die "odoo-bin not found at ./odoo-bin or ./odoo/odoo-bin"; fi
log "Using ODOO_BIN: $ODOO_BIN"

ADDONS_PATH=""
[ -d ./addons ] && ADDONS_PATH=./addons
[ -d ./odoo/addons ] && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./odoo/addons"
[ -d ./addons_custom ] && ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}./addons_custom"
[ -n "$ADDONS_PATH" ] && log "Using ADDONS_PATH: $ADDONS_PATH"

# ---------- DB URL 준비 (반드시 하나는 있어야 함) ----------
ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-${DATABASE_URL:-}}"
[ -n "${ADMIN_DATABASE_URL:-}" ] || die "ADMIN_DATABASE_URL 또는 DATABASE_URL이 필요합니다."

# 내부/외부 판단(SSL)
if echo "$ADMIN_DATABASE_URL" | grep -q "postgres\.railway\.internal"; then
  ASSL=disable
else
  ASSL=require
fi

# 런타임(DB 접속 정보)
DB_NAME="${DB_NAME:-odoo}"
DB_USER="${DB_USER:-odoo_user}"
ODOO_DB_PASSWORD="${ODOO_DB_PASSWORD:-${DB_PASSWORD:-odoo_pass}}"
DB_PASS="${DB_PASS:-$ODOO_DB_PASSWORD}"

# 호스트/포트만 안전하게 뽑기(호스트는 필요, 포트 없으면 5432 기본)
read DB_HOST DB_PORT <<<"$(python3 - <<'PY'
import os, urllib.parse
u = urllib.parse.urlparse(os.environ.get("ADMIN_DATABASE_URL",""))
print(u.hostname or "postgres.railway.internal")
print(u.port or 5432)
PY
)"
export PGSSLMODE=$([ "$ASSL" = "disable" ] && echo disable || echo require)

log "ADMIN URL detected (ssl=$ASSL)"
log "RUNTIME -> user=$DB_USER host=$DB_HOST port=$DB_PORT db=$DB_NAME ssl=$PGSSLMODE"

# ---------- Postgres 준비 대기 (URL로 직접 테스트) ----------
log "Waiting for PostgreSQL (admin url)..."
for i in {1..30}; do
  if psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "select 1" >/dev/null 2>&1; then
    break
  fi
  log "  retry $i/30"; sleep 2
done

# 마지막 한 번은 에러 출력 보면서 확인
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "select 1;" >/dev/null \
  || die "ADMIN 접속 실패 (URL로 연결 불가)"

# ---------- BOOTSTRAP: 유저/DB/확장 ----------
log "Bootstrap: role/database/extensions"

# 1) 사용자 생성
ESC_PASS=$(printf "%s" "$DB_PASS" | sed "s/'/''/g")
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  || psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE USER ${DB_USER} WITH LOGIN PASSWORD '${ESC_PASS}';"

# 2) DB 생성
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -At -c "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

# 3) 확장 (해당 DB로 접속)
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "\connect ${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS unaccent;" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

# 권한 보강(무해)
psql "$ADMIN_DATABASE_URL" -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" || true

# ---------- 런타임 접속 확인(odoo_user) ----------
export PGHOST="$DB_HOST" PGPORT="$DB_PORT" PGUSER="$DB_USER" PGPASSWORD="$DB_PASS" PGDATABASE="$DB_NAME"
log "Testing runtime connection (odoo_user -> $DB_NAME)"
psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -v ON_ERROR_STOP=1 -c "select current_user,current_database();" >/dev/null \
  || die "RUNTIME 접속 실패(odoo_user)"

# ---------- 최초 스키마 초기화 ----------
INIT_CHECK=$(psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -At -c \
  "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" || true)
if [ "$INIT_CHECK" != "1" ]; then
  log "Initializing Odoo base schema..."
  "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
    -i base \
    --database="$PGDATABASE" \
    --db_host="$PGHOST" --db_port="$PGPORT" \
    --db_user="$PGUSER" --db_password="$PGPASSWORD" \
    --db_sslmode="$PGSSLMODE" \
    --without-demo=all --stop-after-init
fi

# ---------- Odoo 기동 ----------
HTTP_PORT="${PORT:-8069}"
log "Starting Odoo on port $HTTP_PORT ..."
exec "$ODOO_BIN" ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
  --database="$PGDATABASE" \
  --db_host="$PGHOST" --db_port="$PGPORT" \
  --db_user="$PGUSER" --db_password="$PGPASSWORD" \
  --db_sslmode="$PGSSLMODE" \
  --db-filter="^${PGDATABASE}$" \
  --http-port="$HTTP_PORT" \
  --proxy-mode \
  --without-demo=all
