#!/usr/bin/env bash
# 운영 서버(10.10.21.20 / DB odoo18)의 계정과목표(재정 현지화)와 통화를 확인한다.
# 비밀번호는 화면에 표시되지 않고 파일에도 저장하지 않는다.
# (다만 로그인 요청으로 서버에는 전송되며 기본이 평문 HTTP 다 — 사내망 전제)
set -u
BASE="${BASE:-http://10.10.21.20}"
DB="${DB:-odoo18}"
LOGIN="${LOGIN:-admin}"
COOKIE=$(mktemp)
trap 'rm -f "$COOKIE"' EXIT

read -r -s -p "admin 비밀번호: " PW; echo

auth=$(curl -s -c "$COOKIE" -X POST "$BASE/web/session/authenticate" \
  -H "Content-Type: application/json" \
  -d "{\"jsonrpc\":\"2.0\",\"params\":{\"db\":\"$DB\",\"login\":\"$LOGIN\",\"password\":\"$PW\"}}")

if ! echo "$auth" | grep -q '"uid": *[0-9]'; then
  echo "로그인 실패 — DB/계정/비밀번호를 확인하세요."; echo "$auth" | head -c 300; exit 1
fi

call() {  # $1=model $2=method $3=args json
  curl -s -b "$COOKIE" -X POST "$BASE/web/dataset/call_kw" -H "Content-Type: application/json" \
    -d "{\"jsonrpc\":\"2.0\",\"params\":{\"model\":\"$1\",\"method\":\"$2\",\"args\":$3,\"kwargs\":{}}}"
}

echo "=== 회사 / 계정과목표 ==="
call res.company search_read '[[],["name","chart_template","currency_id","country_id"]]' \
  | python3 -c "import sys,json;d=json.load(sys.stdin).get('result',[]);[print(f\"  {c['name']} | 차트={c.get('chart_template')} | 통화={(c.get('currency_id') or ['',''])[1]} | 국가={(c.get('country_id') or ['',''])[1]}\") for c in d]"

echo "=== 부가세 가격포함 설정 (정산·반입 금액에 직접 영향) ==="
call res.company search_read '[[],["name","account_price_include"]]' \
  | python3 -c "import sys,json;d=json.load(sys.stdin).get('result',[]);[print(f\"  {c['name']}: 회사 기본 = {c.get('account_price_include')}\") for c in d]"
call account.tax search_read '[[["active","=",true]],["name","price_include","price_include_override"]]' \
  | python3 -c "
import sys,json
d=json.load(sys.stdin).get('result',[])
inc=[t for t in d if t.get('price_include')]
print(f'  활성 세목 {len(d)}건 중 가격포함 동작 {len(inc)}건')
if inc: print('   ->', [t['name'] for t in inc[:8]])
ov=set(str(t.get('price_include_override')) for t in d)
print('  세목별 override 값:', sorted(ov))
print('  (회사 기본이 tax_included 면 override 없는 새 세금은 즉시 포함 동작)')"

echo "=== 한국 세목(세금계산서/영세/면세) 존재 여부 ==="
call account.tax search_count '[[["name","like","TI"]]]' \
  | python3 -c "import sys,json;print('  TI 계열 세목:',json.load(sys.stdin).get('result'),'건 (0이면 한국 차트 아님)')"

echo "=== 재고 평가 방식 (입고 시 분개 여부) ==="
call product.category search_read '[[],["name","property_valuation","property_cost_method"]]' \
  | python3 -c "
import sys,json
d=json.load(sys.stdin).get('result',[])
for c in d[:10]: print(f\"  {c['name']}: 평가={c.get('property_valuation')} / 원가={c.get('property_cost_method')}\")
print('  (automated = 입고 시 분개 발생 / manual = 정산 시점에만)')"

echo "=== 타국 모듈 설치 여부 (정리 대상) ==="
call ir.module.module search_read '[[["state","=","installed"],["name","in",["l10n_kr","l10n_kr_reports","l10n_us","account_avatax","account_qr_code_sepa"]]],["name"]]' \
  | python3 -c "import sys,json;print('  설치됨:',[m['name'] for m in json.load(sys.stdin).get('result',[])])"
