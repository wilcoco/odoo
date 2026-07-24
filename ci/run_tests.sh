#!/bin/sh
# 사내 테스트 러너 — Enterprise 의존(quality 등) 때문에 공용 GitHub 러너에선 설치 불가.
# 로컬 docker 스택(Enterprise 마운트 포함)에서 실행한다. CI 는 self-hosted 러너로 이 스크립트를 호출.
#
# 사용법: ci/run_tests.sh [모듈,콤마목록]   (기본: 핵심 3모듈)
set -eu
MODULES="${1:-gh_provisional_pricing,injection_worksite,injection_costing}"
# post_install 자동 수집이 모듈을 누락하는 사례가 있어 --test-tags 로 명시 지정한다
TAGS="$(echo "$MODULES" | sed 's/^/\//;s/,/,\//g')"
DB="ci_test_$$"
# 비밀값은 conf 에 없음(CLAUDE.md 규칙 #3) — 컨테이너 환경변수에서 읽는다(출력 금지)
PW="$(docker exec cams-odoo-odoo-1 sh -c 'printf %s "$DB_PASSWORD"')"
[ -n "$PW" ] || { echo "🔴 DB_PASSWORD 를 컨테이너에서 읽지 못함"; exit 1; }

echo "▶ 테스트 DB: $DB / 모듈: $MODULES"
docker exec cams-odoo-odoo-1 python3 /mnt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d "$DB" \
  -i "$MODULES" --test-enable --test-tags "$TAGS" --http-port=8199 --stop-after-init \
  --db_password="$PW" > /tmp/ci_test.log 2>&1 || true

RESULT=$(grep -E "odoo.tests.result" /tmp/ci_test.log | tail -1)
echo "▶ $RESULT"
grep -E "FAIL:|ERROR:" /tmp/ci_test.log | head -20 || true

docker exec cams-odoo-db-1 dropdb -U odoo --if-exists "$DB" 2>/dev/null || true

STARTED=$(grep -cE "INFO .* odoo\.addons\..*\.tests\..*: Starting " /tmp/ci_test.log || true)
echo "▶ 실행된 테스트: ${STARTED}건"

case "$RESULT" in
  *"0 failed, 0 error"*)
    if [ "$STARTED" -lt 1 ]; then
      echo "🔴 FAIL — 테스트가 하나도 수집되지 않음(위장 통과 방지)"; exit 1
    fi
    echo "✅ PASS"; exit 0;;
  *) echo "🔴 FAIL — /tmp/ci_test.log 확인"; exit 1;;
esac
