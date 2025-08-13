#!/usr/bin/env bash
set -e

echo "--- Starting Odoo bootstrap ---"

# ===== ADMIN vs RUNTIME =====
export ADMIN_DATABASE_URL="${ADMIN_DATABASE_URL:-$DATABASE_URL}"
if [ -z "$ADMIN_DATABASE_URL" ]; then
  echo "!!! ADMIN_DATABASE_URL 또는 DATABASE_URL이 필요합니다."; exit 1
fi

# 안전하게 파싱
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

# RUNTIME 기본값
export DB_HOST="${DB_HOST:-$AHOST}"
export DB_PORT="${DB_PORT:-$APORT}"
export DB_NAME="${DB_NAME:-odoo}"
export DB_USER="${DB_USER:-odoo_user}"
# 비번 폴백
export ODOO_DB_PASSWORD="${ODOO_DB_PASSWORD:-${DB_PASSWORD}}"
export DB_PASS="${DB_PASS:-${ODOO_DB_PASSWORD:-odoo_pass}}"

# SSL 모드
if [[ "$AHOST" == *.railway.internal ]]; then ASSL=disable; else ASSL=require; fi
if [[ "$DB_HOST" == *.railway.internal ]]; then PGSSLMODE=disable; else PGSSLMODE=require; fi
export PGSSLMODE

# 준비/접속 체크
getent hosts "$DB_HOST" >/dev/null 2>&1 || { echo "DNS 실패: $DB_HOST"; exit 1; }

echo "--> Waiting for PostgreSQL..."
for i in {1..30}; do
  if PGPASSWORD="$APASS" pg_isready -h "$AHOST" -p "$APORT" -U "$AUSER" -d "$ADB" >/dev/null 2>&1; then
    break; fi
  echo "  retry $i/30"; sleep 2
done

# ADMIN 접속 테스트
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c "select 1;" >/dev/null

# ===== BOOTSTRAP: 유저/DB/확장 =====
echo "--> Bootstrap role/db/extensions"
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
  || PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
  "CREATE USER ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"

PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
  || PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB sslmode=$ASSL" -v ON_ERROR_STOP=1 -c \
  "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"

PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$DB_NAME sslmode=$ASSL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$DB_NAME sslmode=$ASSL" -v ON_ERROR_STOP=1 -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
PGPASSWORD="$APASS" psql "host=$AHOST port=$APORT user=$AUSER dbname=$ADB     sslmode=$ASSL" -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"

# ===== 런타임 자격증명 전환 =====
export PGHOST="$DB_HOST"
export PGPORT="$DB_PORT"
export PGUSER="$DB_USER"
export PGPASSWORD="$DB_PASS"
export PGDATABASE="$DB_NAME"

echo "--> Testing RUNTIME connection (odoo_user -> $DB_NAME)"
PGPASSWORD="$PGPASSWORD" psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -v ON_ERROR_STOP=1 -c "select current_user, current_database();" >/dev/null

# ===== 최초 스키마 초기화(없을 때만) =====
INIT_CHECK=$(PGPASSWORD="$PGPASSWORD" psql "host=$PGHOST port=$PGPORT user=$PGUSER dbname=$PGDATABASE sslmode=$PGSSLMODE" -tAc \
  "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='ir_module_module';" || true)
if [ "$INIT_CHECK" != "1" ]; then
  echo "--> Initializing Odoo base schema..."
  ./odoo-bin \
    -i base \
    --database="$PGDATABASE" \
    --db_host="$PGHOST" --db_port="$PGPORT" \
    --db_user="$PGUSER" --db_password="$PGPASSWORD" \
    --db_sslmode="$PGSSLMODE" \
    --without-demo=all --stop-after-init
fi

# ===== Odoo 기동 =====
echo "--> Starting Odoo on port ${PORT:-8069}"
./odoo-bin \
  --addons-path=addons,addons_custom \
  --database="$PGDATABASE" \
  --db_host="$PGHOST" --db_port="$PGPORT" \
  --db_user="$PGUSER" --db_password="$PGPASSWORD" \
  --db_sslmode="$PGSSLMODE" \
  --db-filter="^${PGDATABASE}$" \
  --http-port="${PORT:-8069}" \
  --proxy-mode \
  --without-demo=all
