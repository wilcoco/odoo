#!/bin/sh
# 머지 무결성 점검 — "재작성 흡수" 후 유실을 절차로 잡는다.
#
# 사용법:
#   ci/merge_integrity_check.sh <base-ref> [branch ...]
#   예) ci/merge_integrity_check.sh escon/main feat/serial-scan-guard feat/ops-process
#
# 하는 일:
#   1) base-ref 에서 ci/critical_symbols.txt 의 심볼이 전부 살아있는지 스캔 (0곳 = 유실 의심)
#   2) 각 branch 의 커밋이 base 에 전부 포함됐는지 (미포함 수 표시)
#   3) 미포함 브랜치는 임시 워크트리에서 시험 머지 → 충돌 파일 목록 + 머지 후 base 대비 잔여 diff
#      (잔여 diff 0 = base 가 이미 내용 흡수, 커밋만 미포함)
set -eu

BASE="${1:?base-ref 필요 (예: escon/main)}"; shift || true
ROOT="$(git rev-parse --show-toplevel)"
SYMS="$ROOT/ci/critical_symbols.txt"
FAIL=0

echo "══ 1) 핵심 심볼 생존 스캔 @ $BASE ══"
while IFS= read -r sym; do
    case "$sym" in ''|\#*) continue;; esac
    # 주의: ref 지정 grep -c 출력은 ref:path:count → count 는 마지막 필드($NF)
    n=$(git grep -c "$sym" "$BASE" -- addons_custom 2>/dev/null | awk -F: '{s+=$NF} END{print s+0}')
    if [ "$n" -eq 0 ]; then
        echo "  🔴 유실 의심: $sym (0곳)"
        FAIL=1
    else
        echo "  ✅ $sym ($n)"
    fi
done < "$SYMS"

for BR in "$@"; do
    echo "══ 2) 브랜치 포함 여부: $BR ══"
    missing=$(git rev-list --count "$BASE".."$BR" 2>/dev/null || echo "?")
    echo "  base 미포함 커밋: $missing"
    [ "$missing" = "0" ] && continue

    echo "══ 3) 시험 머지: $BASE + $BR ══"
    WT=$(mktemp -d)
    git worktree add -q --detach "$WT" "$BASE"
    (
        cd "$WT"
        if git merge --no-commit --no-ff "$BR" >/dev/null 2>&1; then
            echo "  머지: 충돌 없음"
        else
            echo "  ⚠ 충돌 파일:"
            git diff --name-only --diff-filter=U | sed 's/^/    /'
            git merge --abort 2>/dev/null || true
            git worktree remove -f "$WT" >/dev/null 2>&1 || true
            FAIL=1
            exit 0
        fi
        extra=$(git diff "$BASE" --stat | tail -1)
        if [ -z "$extra" ]; then
            echo "  잔여 diff: 없음 → base 가 내용을 이미 흡수(무유실)"
        else
            echo "  잔여 diff(=base 에 없는 내용): $extra"
        fi
        git merge --abort 2>/dev/null || git reset --hard -q "$BASE"
    )
    git worktree remove -f "$WT" >/dev/null 2>&1 || true
done

echo "══ 결과 ══"
if [ "$FAIL" -eq 0 ]; then echo "✅ 무결성 이상 없음"; else echo "🔴 유실 의심 항목 있음 — 위 로그 확인"; fi
exit "$FAIL"
