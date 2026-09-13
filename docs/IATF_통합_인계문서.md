# IATF 회사양식 통합 — 작업 인계 문서 (HANDOFF)

> 작성: 2026-06-22 (사출/Oracle 작업하던 세션이 작성). 새 전용 세션은 이 문서 + 메모리(`cams-odoo-local-env`, `cams-oracle-demand-integration`)를 먼저 읽고 시작할 것.

## 0. 목표 (사용자 요구 — 확정)
1. **wilcoco/iatf(Next.js+Prisma 앱)의 회사 맞춤 IATF 양식·데이터구조를 Odoo IATF 모듈에 반영** (코드 이식 아님 = 명세서로 활용)
2. **Odoo의 모든 요소(MO·품번·협력사·설비·BOM 등)와 IATF 연동** (Many2one 등으로 자연 연결)
3. **승인(결재) 프로세스를 Odoo에서** (mail.activity / iatf_approval 활용)
4. → 별개 시스템(②) 아님. **Odoo 통합(①)** 으로 확정. (요구가 "전 요소 연동+승인"이라 별개 시스템은 동기화 지옥 → 통합이 정답)

## 1. 입력 자료 = 명세서
- **위치**: `~/cams-odoo/_incoming/wilcoco_iatf/` (github.com/wilcoco/iatf, gitignore된 스테이징)
- **정체**: Next.js 14 + Prisma ORM + Tailwind 웹앱. **Odoo 아님 → 코드 이식 불가.**
- **핵심 자산**: `prisma/schema.prisma` = **회사 IATF 양식 47개 모델 명세**. + `prisma/seed-from-excel.ts`(회사 엑셀 양식 시드), `prisma/seed-control-items.ts`. + `src/app/(dashboard)` 화면 구조 = UI 참고.
- 이 스키마를 "이 회사가 원하는 IATF 데이터/필드/관계의 요구사항"으로 읽는다.

## 2. 현황 = 이미 풍부한 토대
- **Odoo IATF 32개 모듈, 모델 71개** 이미 설치·동작 (cams_demo DB). 바닥부터가 절대 아님.
- 토대 `iatf_document_control`, 승인 `iatf_approval`(iatf.approval.request/line/mixin), 검사/감사/MSA/SPC/PPAP/FMEA/관리계획/교정/설비/금형/교육/공급사 등 다 존재.
- IATF는 사출(injection/gh)과 의존 거의 없음 → 독립 작업 안전.

## 3. 갭 분석 결과 (Prisma 47 ↔ Odoo IATF 71)
- **~36개: Odoo에 대응 모델 있음** → 회사양식에 맞게 **필드/뷰 정합**(추가·수정) 작업. (대부분 여기)
- **~9개: 신규 개발 필요** (Odoo에 대응 없음):
  - `ShippingInspection`(출하검사), `ReliabilityTest`(신뢰성), `AdhesionTest`(밀착성), `ColorMeasurement`(색상), `CoatingThickness`(도막두께) ← **도장/사출 특화 시험 5종**
  - `Jig`/`JigRecord`(지그), `Process`(공정 마스터), `VehicleModel`(차종 — 기존 escon_car_info와 통합 검토)
- 주요 매핑(대응 있음): IncomingInspection→iatf.incoming.inspection, GageRnrStudy→iatf.msa.study, ProcessCapability→iatf.spc.study, Calibration→iatf.calibration.record, Nonconformance→iatf.nonconformity, CorrectiveAction→iatf.corrective.action, Audit*→iatf.audit(.finding), Equipment/Mold→iatf.equipment/iatf.mold, Supplier→res.partner+iatf.supplier.evaluation, Part→product.template, Department→hr.department, User→res.users, Attachment→ir.attachment, AuditLog→mail.tracking, Reminder→mail.activity.

## 4. ⚠️ 충돌 주의 (사출 모듈과 같은 표준모델 확장) — super() 안전성 검증 완료(2026-06-22)
IATF와 사출이 **같은 표준모델 동시 확장**. 필드충돌 0건. 메서드 override 교차점을 전수 확인한 결과 **현재 기준선은 안전**(활성 override 전부 super() 정상 호출):

| 모델·메서드 | override 모듈 | super() | 비고 |
|---|---|---|---|
| mrp.production.create | iatf_control_plan, iatf_ppap / escon_serial, injection_worksite | ✅ 전부 | 다 @api.model_create_multi |
| mrp.production.button_mark_done | iatf_mold, iatf_process_inspection, iatf_training / injection_worksite | ✅ 활성분 전부 | gh_vendor_settlement은 주석처리(비활성) |
| mrp.production._update_mold_shots | iatf_mold(만) | super 없음이나 **사출쪽 동명 메서드 없음=IATF 고유** → 충돌 아님 | 안전 |
| stock.move._action_done | iatf_traceability / gh_stock_ex | ✅ 둘 다 | |

**→ 기준선 안전 = 현재 cams_demo에 IATF+사출 둘 다 깔려 MO 생성·완료·재고이동 e2e 정상인 것과 일치.**
**IATF 신규/수정 시 규칙**: 위 표준 메서드(특히 mrp.production.create/button_mark_done, stock.move._action_done)를 override하면 **반드시 super() 호출 + 반환값 보존**. 안 그러면 다른 모듈(사출 등) 로직이 사일런트로 누락됨. 크게 수정 후엔 **둘 다 깔린 DB에서 MO 생성→완료→입고 e2e 재검증** 필수.

## 5. 권장 작업 순서
1. **상세 갭 매핑**(모델별 필드 1:1): Prisma 각 모델 필드 ↔ Odoo 모델 필드 표 → 추가/수정/삭제 확정. (현업 확인 포인트 표시)
2. **우선순위 양식 3~5개 먼저**: 회사가 매일 쓰는 것부터 (예: 수입검사·출하검사·관리계획서·MSA·공정검사).
3. **양식 정합 구현**: Odoo 모델 필드 보강 + 뷰를 회사양식 레이아웃대로 + 연동(Many2one: MO/품번/협력사/설비) + 승인(activity/iatf_approval) 배선.
4. **신규 5종 시험**(도장 특화)은 한 모듈로 묶어 신규 개발 검토.
5. 영역별 반복 확장.

## 6. 일정 관점 (정직하게)
- 사람 팀 기준 "수 주~수개월"은 **사람 속도**. AI(이 작업자)가 하면 **순수 구현은 시간 단위**.
- **실제 병목은 코딩이 아니라**: ① 회사양식·필드·승인선 **현업 확인**, ② 빌드/설치/검증 사이클, ③ 우선순위 결정. → 전체는 **사용자 확인 속도에 종속**. 핵심 양식은 며칠~2주 내 동작 가능.

## 7. 작업 환경 / 규칙
- **코드 위치**: IATF 모듈은 `~/cams-odoo/addons_custom/iatf_*` (출처 github.com/wilcoco/odoo의 addons_custom). 수정분은 **wilcoco/odoo repo에 feature 브랜치 → PR**. (addons_custom/은 로컬 마운트 사본 + gitignore. 커밋은 `_incoming/wilcoco_odoo` 클론에서.)
- **DB**: 개발/검증은 IATF 전용 DB 권장(`cams_iatf` 새로 만들거나 cams_demo 재생성). **테스터용 cams_demo는 가급적 안정 유지**(tester1/tester2 사용 중).
- **컨테이너**: 이 세션과 같은 docker compose 스택 공유. 같은 odoo 컨테이너 restart/`-u`는 서로 영향 → 작업 시 인지.
- **설치/업그레이드**: `docker compose exec odoo bash -lc 'python3 /mnt/odoo/odoo-bin -c /etc/odoo/odoo.conf -d <DB> -u <모듈> --stop-after-init --db_password=$DB_PASSWORD'` 후 restart.
- **검증**: odoo shell(`--no-http`)로 모델 필드/메서드 점검, playwright(`/tmp/pw`)로 UI 스크린샷 가능(8069, cams_demo, admin/admin).
- **금지**: enterprise 소스 커밋, main 직접 push, credential 하드코딩.

## 8. 첫 액션 (새 세션이 바로 할 일)
1. 이 문서 + `prisma/schema.prisma` 정독.
2. **모델별 상세 필드 매핑표** 작성(섹션 5-1) → 사용자에게 우선순위 양식 확인받기.
3. 충돌 메서드 3개(4번) super() 안전성 먼저 확인 → 기준선.

## 8.5. ★ Odoo 연동 갭 수정 (QA세션 분석, 2026-06-26)
별도 명세: **`docs/IATF_연동갭_수정명세.md`**. 결정=자체모델 유지+연동보강.
잘된것: process.inspection 등 현장검사는 production·workcenter·lot·PO 잘 연동(모범).
갭 5개: G1 BOM미연동 / G2 quality_control 미연동(품질결과 2곳분산) / G3 iatf.process가 workcenter 미연동 / **G4 dashboard가 실적(부적합/검사/감사) 미집계** / **G5 quality.objective가 검사·부적합 실적 미집계**. 우선순위 G4→G5→G3→G1→G2. 표준모델 override 아닌 필드/compute 추가라 충돌규칙 안전.

## 9. 작업 브랜치 (준비됨)
- **브랜치: `feat/iatf-company-forms`** — 이미 생성됨, `18.0`(origin/18.0, a703e71d)에서 분기. repo=`_incoming/wilcoco_odoo`(github.com/wilcoco/odoo).
- 다른 브랜치(feat/injection-planning-unified-master, fix/odoo18-quality-and-demo)와 분리되어 사출 작업과 안 섞임.
- 편집은 `~/cams-odoo/addons_custom/iatf_*`, 커밋은 `_incoming/wilcoco_odoo`에서 `feat/iatf-company-forms` 브랜치로. main(18.0) 직접 push 금지.
- 새 세션 시작 지시 예: "docs/IATF_통합_인계문서.md 읽고 feat/iatf-company-forms 브랜치에서 IATF 통합 작업 시작해줘"
