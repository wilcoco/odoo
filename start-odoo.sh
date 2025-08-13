#!/usr/bin/env bash
set -euo pipefail

log() { echo "[start-odoo] $*"; }
die() { echo "[start-odoo][ERROR] $*" >&2; exit 1; }

echo "ADMIN_DATABASE_URL present? $([ -n "${ADMIN_DATABASE_URL:-}" ] && echo yes || echo no)"
echo "DATABASE_URL present? $([ -n "${DATABASE_URL:-}" ] && echo yes || echo no)"


# ---------------- ODOO BIN / ADDONS PATH AUTO-DETECT ----------------
# odoo-bin 위치 자동 탐지
if [ -x ./odoo-bin ]; then
  ODOO_BIN=./odoo-bin
elif [ -x ./odoo/odoo-bin ]; then
  ODOO_BIN=./odoo/odoo-bin
else
  die "odoo-bin not found at ./odoo-bin or ./odoo/odoo-bin"
fi
log "Using ODOO_BIN: $ODOO_BIN"

# 기본 애드온 경로 자동 탐지
BASE_ADDONS=""
if [ -d ./addons ]; then
  BASE_ADDONS=./addons
elif [ -d ./odoo/addons ]; then
  BASE_ADDONS=./odoo/addons
fi

# 커스텀 애드온 경로: ./addons_custom 존재하면 자동 추가, ENV로도 추가 가능(EXTRA_ADDONS="path1,path2")
EXTRA_ADDONS="${EXTRA_ADDONS:-}"
if [ -d ./addons_custom ]; then
  EXTRA_ADDONS="${EXTRA_ADDONS:+$EXTRA_ADDONS,}./addons_custom"
fi

ADDONS_PATH="$BASE_ADDONS"
if [ -n "$EXTRA_ADDONS" ]; then
  ADDONS_PATH="${ADDONS_PATH:+$ADDONS_PATH,}$EXTRA_ADDONS"
fi
[ -n "$ADDONS_PATH" ] || log "WARN: addons path could not be auto-detected; Odoo defaults will be used"
[ -n "$ADDONS_PATH" ] && log "Using ADDONS_PATH: $ADDONS_PATH"

# 데이터 디렉터리 (볼륨 마운트 시 /data 권장)
ODOO_DATA_DIR="${ODOO_DATA_DIR:-/data}"

# ---------------- ADMIN vs RUNTIME ----------------
# ADMIN_DATABASE_URL 없으면 DATABASE_URL 사용
ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-${DATABASE_URL:-}}"
[ -n "$ADMIN_DATABASE_URL" ] || die "ADMIN_DATABASE_URL 또는 DATABASE_URL이 필요합니다."

# URL 파싱(안전)
read AHOST APORT AUSER APASS ADB <<PYOUT
$(python3 - <<'PY'
import os, urllib.parse
u = urllib.parse.urlparse(os.environ["ADMIN_DATABASE_URL"])
print(u.hostname or "")
print(u.port or 5432)
print(u.username or "")
print(u.password or "")
print((u.path or "").lstrip("/").split("?")[0] or "postgres")
PY
)
PYOUT

[ -n "$AHOST" ] || die "ADMIN_DATABASE_URL parse failed (host empty)"

# 런타임 자격증명(기본값)
DB_HOST="${DB_HOST:-$AHOST}"
DB_PORT="${DB_PORT:-$APORT}"
DB_NAME="${DB_NAME:-odoo}"
DB_USER="${DB_USER:-odoo_user}"
# 비번 폴백: ODOO_DB_PASSWORD > DB_PASSWORD > 기본
ODOO_DB_PASSWORD="${ODOO_DB_PASSWORD:-${DB_PASSWORD:-}}"
DB_PASS="${DB_PASS:-${ODOO_DB_PASSWORD:-odoo_pass}}"

# SSL 모드 결정
if [[ "$AHOST" == *.railway.internal ]]; then ASSL=disable; else ASSL=require; fi
if [[ "$DB_HOST" == *.railway.internal ]]; then PGSSLMODE=disable; else PGSSLMODE=require; fi
export PGSSLMODE

log "ADMIN   -> user=$AUSER host=$AHOST port=$APORT db=$ADB ssl=$ASSL"
log "RUNTIME -> user=$DB_USER host=$DB_HOST port=$DB_PORT db=$DB_NAME ssl=$PGSSLMODE"

# ---------------- WAIT FOR POSTGRES (ADMIN) ----------------
log "Waiting for PostgreSQL (admin)..."
for i in {1..30}; do
  if PGPASSWORD="$APASS" pg_isready -h "$AHOST" -p "$APORT" -U "$AUSER" -d "$ADB" >/dev/null 2>&1; then
    break
  fi
  log "  retry $i/30"
  sleep 2
done
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c "select 1;" >/dev/null || die "ADMIN 접속 실패"

# ---------------- BOOTSTRAP (ROLE/DB/EXTENSIONS) ----------------
log "Bootstrap: ensure role/database/extensions"

# 1) 사용자 생성 (이미 있으면 skip)
HAS_ROLE=$(PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -At -c \
  "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" || true)
if [ "$HAS_ROLE" != "1" ]; then
  # 비밀번호에 ' 가 있을 수 있으므로 이스케이프
  ESC_PASS=$(printf "%s" "$DB_PASS" | sed "s/'/''/g")
  PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
    "CREATE USER ${DB_USER} WITH LOGIN PASSWORD '${ESC_PASS}';" || die "CREATE USER 실패"
  log "  created role ${DB_USER}"
fi

# 2) 데이터베이스 생성 (이미 있으면 skip)
HAS_DB=$(PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -At -c \
  "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" || true)
if [ "$HAS_DB" != "1" ]; then
  PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
    "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};" || die "CREATE DATABASE 실패"
  log "  created database ${DB_NAME}"
fi

# 3) 확장 설치
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$DB_NAME sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
  "CREATE EXTENSION IF NOT EXISTS unaccent;" || die "CREATE EXTENSION unaccent 실패"
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$DB_NAME sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
  "CREATE EXTENSION IF NOT EXISTS pg_trgm;" || die "CREATE EXTENSION pg_trgm 실패"

# 권한 보강
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
  "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};" || true

# ---------------- SWITCH TO RUNTIME ----------------
export PGHOST="$DB_HOST"
export PGPORT="$DB_PORT"
export PGUSER="$DB_USER"
export PGPASSWORD="$DB_PASS"
export PGDATABASE="$DB_NAME"

log "Testing runtime connection (odoo_user -> $DB_NAME)"
PGPASSWORD="$PGPASSWORD" psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -v ON_ERROR_STOP=1 -c \
  "select current_user,current_database();" >/dev/null || die "RUNTIME 접속 실패"

# ---------------- INITIALIZE BASE SCHEMA (FIRST RUN) ----------------
INIT_CHECK=$(PGPASSWORD="$PGPASSWORD" psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -At -c \
  "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" || true)
if [ "$INIT_CHECK" != "1" ]; then
  log "Initializing Odoo base schema..."
  "$ODOO_BIN" \
    ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
    -i base \
    --database="$PGDATABASE" \
    --db_host="$PGHOST" --db_port="$PGPORT" \
    --db_user="$PGUSER" --db_password="$PGPASSWORD" \
    --db_sslmode="$PGSSLMODE" \
    --without-demo=all \
    --stop-after-init
  log "Base schema initialized."
else
  log "Odoo base schema already present. Skipping initialization."
fi

# ---------------- START ODOO ----------------
HTTP_PORT="${PORT:-8069}"
log "Starting Odoo on port $HTTP_PORT ..."
exec "$ODOO_BIN" \
  ${ADDONS_PATH:+--addons-path="$ADDONS_PATH"} \
  --database="$PGDATABASE" \
  --db_host="$PGHOST" --db_port="$PGPORT" \
  --db_user="$PGUSER" --db_password="$PGPASSWORD" \
  --db_sslmode="$PGSSLMODE"_
