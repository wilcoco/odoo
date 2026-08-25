# UAT 이슈 목록 (코드 동결 중 — 모아서 일괄 수정)

| # | 일자 | 단계 | 증상 | 원인(확정) | 수정안 | 상태 |
|---|---|---|---|---|---|---|
| 1 | 2026-08-25 | 생산계획 UAT 3단계 (원재료 발주) | 원재료 발주해도 해당 협력사 SCM 포털에 발주가 안 뜨고 알림도 없음 | 원재료 자동발주(`injection_planning/models/planning_run.py:1502` action_create_material_po)는 일반 PO만 생성 — `auto_generated`/`portal_state`/포털 알림 미설정. 포털 발주 목록은 `auto_generated=True`만 표시(`supplier_portal_purchase/controllers/portal.py:143`). 포털 연동은 외주 부품 경로(외주 조달 계획)에만 배선돼 있었음 | supplier_portal_purchase에서 `action_create_material_po` 후처리 확장: 거래처가 포털 사용(is_supplier_portal)이면 `auto_generated=True` + `portal_state='new'` + 포털 알림 발송. 의존 방향 적합(supplier_portal_purchase→injection_planning 의존 기존재) | **수정 완료** — `fix/material-po-portal`(d5b1be4) 푸시, 테스트 3/3 그린. 머지·배포 대기 |

## UAT 진행 중 우회
- 이슈 #1: 원재료사 **ASN 등록은 발주와 무관하게 가능**(공급 품목 기반) → 납품·QR 입고·톤정산은 그대로 진행. "협력사가 포털에서 발주 확인·응답" 확인 항목만 이 건에선 보류.

## 수정 중 함께 적발·수정 (같은 브랜치)
- `_create_portal_notification`의 `_()` 번역 호출이 프레임 로컬 `user=None`을 uid로 오인해 int(None) 크래시 — lang 컨텍스트 없는 cron/서버 액션 경로에서 터질 수 있던 잠복 결함. 로컬명 이동(del)으로 수정.

## 커밋에서 의도적으로 제외한 것 (혼입 방지)
- 로컬 작업본의 `action_approve_response` 응답 검토상태 동기화 hunk — 다른 세션의 미머지 수정분(fix/scm-review-9 계열)이라 이 브랜치에 넣지 않음.
