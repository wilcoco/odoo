# CAMS — Odoo 18 자동차 부품 사출/도장 공장 생산관리 시스템

> Odoo 18 Community 기반 커스텀 ERP/MES. 자동차 부품(범퍼 등) **사출 → 도장 → 조립 → 출하** 전 공정과
> 품질(IATF 16949)·공급망(SCM)·설비를 통합한다. 본 repo 는 `addons_custom/` 의 커스텀 애드온을 담는다.

## 도메인
- 현대 수요(Oracle) 수신 → 사출 생산계획 → MO → 사출/도장 실적 → 출하
- 품질경영(IATF 16949) 전 영역, 협력사 포탈·자동발주(SCM), 원재료 SILO 관리

---

## 진행 현황 (브랜치별)

### 🏭 생산계획 / 사출
- **`feat/injection-planning-unified-master`** — 사출 생산계획 마스터 데이터 메뉴 통합
  (제품·BOM·사출기·금형·사출기-금형 능력·가동일정을 [생산계획 > 마스터 데이터] 한 곳으로).
- 계획 흐름: 수요(Oracle/Excel/수동) → BOM 전개 → 재고 차감 → 사출기 배정 → **검토(review) → 확정 → MO**.
  확정은 [생산계획 > 계획 실행] 폼의 "확정(MO 생성)" 버튼(review 상태에서 노출).
- Oracle 수요 연동: `injection.planning.config` → 현대 Oracle(T_ZM_PLN1 시간별 / T_ZM_PLN2 일별)
  수신. thick 모드(Instant Client) 필요 — 배포 이미지에 내장.

### 🔩 사출 현장 (별도 repo: gamehon/odoo_gh · injection_worksite)
- 계획 작업장 자동 사출처리(x_is_injection), 단위 MO(개당 시리얼) 채터 최적화.
- **원재료 SILO 관리**: 용량·충전율·재고수준(정상/주의/부족) 리포트(게이지 대시보드),
  저재고 **자동발주**(표준 purchase.order 초안 → 알림 → 사람 확정 → 입고·회계 자동연계),
  **입고 자동충전**(이중적재 방지 토글).

### ✅ 품질 (IATF 16949)
- **`feat/iatf-company-forms`** — 회사 양식(엑셀 기반 명세) 정합으로 IATF 모듈 통합 진행 중.
  수입검사·공정검사·출하검사·MSA 등 구조화 결재선(iatf.approval.mixin) 배선.
- IATF 32개 모듈(검사·감사·MSA·SPC·PPAP·FMEA·관리계획·교정·설비·금형·교육·공급사…).

### 🔗 공급망 (SCM)
- **`feat/scm-portal-fixes`** — 협력사 포탈/자동발주 점검·수정.
  자동발주(완제품 수요 → BOM 외주품 전개 → 협력사별 PO), 다단계 공급망 추적(2차→1차→에스콘),
  협력사 포탈 응답·승인, 협력사간 거래(supplier.order).

### 🛠 품질·데모 수정
- **`fix/odoo18-quality-and-demo`** — Odoo 18 정합성 + demo 데이터 로드 오류 수정.

---

## 배포
배포 인프라(docker-compose / Dockerfile / 설정)는 별도 repo: **wilcoco/cams-deploy**.
- 스택: Odoo 18 + PostgreSQL 17 + MQTT(mosquitto) + go_relay(PLC 릴레이).
- Odoo 이미지: 공식 odoo:18.0 + Oracle Instant Client(thick) + oracledb (현대 수요 연동).

## 관련 repo
| repo | 내용 |
|---|---|
| 이 repo (wilcoco/odoo) | CAMS 커스텀 애드온 (addons_custom: IATF·생산계획·SCM 등) |
| gamehon/odoo_gh | 사출 현장 플러그인(injection_worksite·SILO) + go_relay |
| wilcoco/cams-deploy | 배포 인프라(compose·Dockerfile·설정) |

> 이 repo 는 odoo/odoo 18.0 의 포크이며 `addons_custom/` 에 CAMS 커스텀을 추가한 형태다.
