# IATF 필드 매핑 (Prisma 회사양식 ↔ Odoo IATF 모델)

> 루프 자율 작성 중. 클러스터별로 채워나감.
> 범례: ✅있음(필드 대응) / ➕추가필요 / 🔁이름다름(매핑) / 🆕신규 / 💡연동(Odoo표준)

## ★ 확정 정책 (사용자 결정, 2026-06-22) — 메모리 `iatf-decision-policy` 참조
**명백하면 묻지 말고 자율 판단. 진짜 모호할 때만 질문(규격값·실제결재자·양식상충).**
1. **신규 vs 흡수**: 회사양식 고유필드 3개 이상 → 별도 신규 모델, 아니면 기존에 필드 추가 흡수.
2. **승인**: 모든 양식 `iatf.approval.mixin` 상속(구조화 결재선). 예외 없음.
3. **연동**: 표준 자동 배선 — product_id, lot_id, picking_id/production_id, partner(협력사), workcenter(설비). BOM=표준 mrp.bom.
4. **필드 출처**: `prisma/schema.prisma` 단일 진실원천(SoT). 추정 금지, 양식에 있는 것만.
5. **충돌**: mrp.production/stock.move override 시 super()+반환값 보존. 대수정 후 cams에서 MO e2e 회귀.
6. **검증·커밋**: 매 양식 -u 클린 + 결재플로우 + e2e 회귀 후 커밋. feat/iatf-company-forms.
7. **우선순위**: 검사 → 측정/시험 → 설비/금형 → 품질경영 → 교육/공급사. 클러스터 내 데이터 많은 것부터.
- **검증 DB**: `cams` (IATF+사출 동시설치 통합 dev DB). 테스터 `cams_demo`는 건드리지 않음.

## 진행 현황 (루프)
| iter | 양식 | 상태 | 커밋 |
|---|---|---|---|
| 1 | A-1 수입검사 (iatf.incoming.inspection) | ✅ 구현·검증·커밋 | `3c03760d` |
| 2 | A-2 공정검사 (iatf.process.inspection) | ✅ 구현·검증·커밋 | `3df07eef` |
| 3 | A-3 출하검사 (iatf.shipping.inspection 신규) | ✅ 신규모듈·검증·커밋 | `5997795c` |
| — | 검사 클러스터 레이아웃 통일(iter1 뷰) | ✅ 커밋 | `241835d9` |

**검사 클러스터(A) 완료 + 정책 재감사 통과**: 3종 모두 결재mixin·SoT필드·표준연동·시퀀스·보안
패턴 일관. defect_rate는 출하검사 미적용(회사양식에 reject수량 없음=정책#4 준수, 정상).

## 클러스터 B — 측정/시험 (Metrology/Test)
| iter | 양식 | 상태 | 커밋 |
|---|---|---|---|
| 4 | B-1 MSA (GageRnrStudy → iatf.msa.study) | ✅ 정합·검증·커밋 | `7cfde41c` |
| 5 | B-2 SPC (ProcessCapability → iatf.spc.study) | ✅ 정합·검증·커밋 | `0303ddb9` |
| 6 | B-3 도장 특화 시험 4종 (iatf_coating_test 신규) | ✅ 신규모듈·검증·커밋 | `2fa7127c` |

**측정/시험 클러스터(B) 완료**: MSA·SPC 정합 + 도장 특화 시험(신뢰성/밀착성/색상/도막두께)
신규 4모델. 규격 기준값(ΔE·도막spec·크로스컷등급)은 필드만 두고 수치는 현업 입력(데이터).

## 클러스터 C — 설비/금형 (Equipment/Mold)
| iter | 양식 | 상태 | 커밋 |
|---|---|---|---|
| 7 | C-1 설비(iatf.equipment) + 금형(iatf.mold) 결재선 | ✅ 검증·커밋(MO e2e 포함) | `3176c57b` |
| 8 | C-2 지그(Jig/JigRecord) · 공정마스터(Process) — iatf_jig 신규 | ✅ 신규모듈·검증·커밋 | `40b44efd` |

**설비/금형 클러스터(C) 완료.**

- Equipment/Mold는 prisma 필드 이미 완비 → 결재mixin만 배선. **부수: iatf_control_plan
  depends += iatf_equipment**(One2many 참조 의존성 누락 latent bug 수정, Key~workcenter_id 해소).
- ⚠️ MO e2e 회귀 포인트: iatf_mold가 mrp.production override 보유 → 검증 시 MO 생성→완료 필수(통과).

## 클러스터 D — 품질경영 (Quality Management) [진행중]
| iter | 양식 | 상태 | 커밋 |
|---|---|---|---|
| 9 | D-1 관리계획서(iatf.control.plan) 결재선 | ✅ 검증·커밋(MO e2e 포함) | `3ecb8b31` |
| 10 | D-2 FMEA·PPAP·부적합·시정조치·감사·경영검토·품질목표 결재선(7모델 배치) | ✅ 검증·커밋(MO e2e 포함) | `5c430720` |

**품질경영 클러스터(D) 완료** (관리계획서 + 7개 양식 결재선). ppap MO e2e 통과.

- 관리계획서: prisma에 ControlPlan 헤더 없음(ControlItem 집합) → Odoo 상위호환, 결재mixin만 배선.
- ⚠️ D-2 중 **iatf_ppap는 mrp.production override 보유** → MO e2e 회귀 필수.

## 클러스터 E — 교육/공급사 + 교정 [완료]
| iter | 양식 | 상태 | 커밋 |
|---|---|---|---|
| 11 | 교육·SCAR·공급사평가·외주·교정·측정장비 결재선(7모델) + 교정 SoT필드 | ✅ 검증·커밋(MO e2e) | `920eeb33` |
| 12 | 비상사태 대응계획(iatf.contingency.plan) 결재선 | ✅ 검증·커밋 | `9e6b639d` |

---

# ✅ prisma 회사양식 47모델 대응 완료 (2026-06-22)

**구현(결재선+SoT 정합):** 검사3 · 도장시험4(신규) · MSA · SPC · 설비 · 금형 · 지그/공정3(신규)
· 관리계획서 · FMEA · PPAP · 부적합 · 시정조치 · 감사 · 경영검토 · 품질목표 · 교육 · SCAR
· 공급사평가 · 외주2 · 교정 · 측정장비 · 비상대응.

**흡수/표준대응(작업 불필요):**
- KPI(KpiDefinition/Result) → iatf.quality.objective(kpi_name 등)
- 공급사실적(SupplierDelivery/QualityPerformance) → iatf.supplier.evaluation(ppm_rate/납기준수율)
- 검사상세(InspectionRecord/Detail) → 각 검사모델 line_ids로 흡수
- 자격(QualificationStandard/Assessment) → iatf.competence.matrix(역량 매트릭스)
- 설비/금형 하위(DailyCheck/Maintenance/MoldRecord) → 각 모듈 기존 모델
- 마스터: Department→hr.department, User→res.users, Part→product, Supplier→res.partner,
  Attachment→ir.attachment, AuditLog→mail.tracking, Reminder→mail.activity, VehicleModel→escon_car_info

**공통 결과:** 전 양식 iatf.approval.mixin 구조화 결재선 배선(정책#2). 필드는 prisma SoT 그대로
(정책#4), 규격 수치(ΔE·도막spec·크로스컷)는 필드만·데이터 입력. 표준모델 override 보유 모듈
(control_plan/ppap/mold/training)은 MO 생성→완료 e2e 회귀 전부 통과(정책#5). 검증 DB=cams.

**커밋 총 15건** (feat/iatf-company-forms): 3c03760d 3df07eef 5997795c 241835d9 7cfde41c
0303ddb9 2fa7127c 3176c57b 40b44efd 3ecb8b31 5c430720 920eeb33 9e6b639d (+iter 초기 2건).

**후속 검토(선택, 별도 지시 시):** 자격기준(QualificationStandard) 전용 마스터화 여부,
prisma 미대응 표준 IATF 모듈(csr·drawing·packaging·work_environment·risk·customer_property)
결재선 적용 여부, 회사양식 PDF 대비 뷰 레이아웃 정밀화, 실제 결재자(승인선) 데이터 설정.

### iter4 (B-1 MSA) 정합
- 추가: product_id(partId 연동), study_date(연구일), specification(nominal),
  instrument_id→iatf.measurement.equipment(회사양식 instrument FK). + 결재 mixin.
- depends += product, iatf_calibration, iatf_approval. 검증: -u 클린, 결재 플로우 정상.
- ⚠️ B-3~ 도장 특화 시험은 규격값(ΔE 기준, 도막두께 spec, 크로스컷 등급)이 회사 현업
  수치 → 정책상 "멈추고 질문" 트리거. 모델 골격은 짜되 규격 기준값은 사용자 확인 후.

### iter1 구현 내역 (A-1)
- 추가 필드: `visual_result`/`dimension_result`/`material_result`(외관/치수/재질 판정 Selection),
  `defect_rate`(불량률% 자동계산), `supplier_cert_no`(성적서번호).
- `iatf.approval.mixin` 상속 + 헤더 결재버튼/상태배지 + 결재선 탭. manifest depends += iatf_approval.
- 검증: -u 클린, 결재 draft→in_progress→approved, defect_rate=10.0, MO e2e 회귀 정상.

### iter2 구현 내역 (A-2)
- `article_stage`(초물/중물/종물 — 회사양식 inspectionType), `shift`(교대조), `production_date`(생산일).
- 항목별 판정 요약: `visual_result`/`dimension_result`/`function_result`(외관/치수/기능).
- `iatf.approval.mixin` 상속 + 헤더 결재버튼/배지 + 결재선 탭. manifest depends += iatf_approval.
- `defect_rate`는 기존 존재. 검증: -u 클린, 결재 플로우 정상, defect_rate=2.0, MO e2e 회귀 정상.

### iter3 (A-3 출하검사) — 회사양식 ShippingInspection 고유필드
- Prisma 고유: `destination`(도착지), `packagingCheck`(포장검사), `labelCheck`(라벨검사),
  visualCheck/dimensionCheck, shippingDate, lotNo, quantity, result.
- 선택지 (★사용자 결정): (a) 별도 경량 `iatf.shipping.inspection` 신규 / (b) 기존
  `iatf.process.inspection` OQC 단계(oqc_inspection_ids)로 흡수 + 포장/라벨 필드 추가.

---

## 클러스터 A — 검사 (Inspection)  [작성: 1회차]

### A-1. IncomingInspection (수입검사) → `iatf.incoming.inspection`
**판정: Odoo 모델이 더 풍부. 회사양식 필드 대부분 대응됨. 소수 추가.**

| Prisma 필드 | Odoo 대응 | 상태 |
|---|---|---|
| supplierId/supplier | (purchase_id→partner) / 💡 res.partner 연동 | ✅(연동보강) |
| partId/part | product_id, part_number | ✅ |
| receivingDate | inspection_date | ✅ |
| lotNo | lot_id (stock.lot) | 🔁 |
| quantity | quantity_received | ✅ |
| inspectionType (전수/샘플/무검사) | inspection_type + sampling_plan | ✅ |
| sampleSize | sample_size | ✅ |
| inspectorId | inspector_id | ✅ |
| visualResult | (line/characteristic 기반) | 🔁 line_ids로 |
| dimensionResult | measured_value/characteristic_type | 🔁 |
| materialResult (Mill Sheet) | ➕ **material_result/mill_sheet 필드 추가 권장** | ➕ |
| defectQty | quantity_rejected | ✅ |
| defectRate | (process엔 defect_rate 있음, incoming엔 ➕) | ➕ |
| overallResult | result | ✅ |
| disposition (합격입고/반품/특채) | disposition | ✅ |
| supplierCertNo | ➕ **supplier_cert_no 필드 추가** | ➕ |
| remarks | notes | ✅ |
| 승인 | approved_by + 💡 iatf_approval/activity | ✅ |
→ **작업량 小**: 필드 3개 추가(material_result, defect_rate, supplier_cert_no) + 협력사 연동 보강 + 뷰 회사양식 정렬.

### A-2. ProductionInspection (공정검사: 초/중/종물) → `iatf.process.inspection`
**판정: 대응 충분. inspection_stage(초물/중물/종물) 이미 존재 가능성.**

| Prisma | Odoo | 상태 |
|---|---|---|
| partId | product_id/part_number | ✅ |
| productionDate/shift | inspection_date / ➕ shift | ✅/➕ |
| lotNo | lot_id | 🔁 |
| inspectionType (초/중/종물) | inspection_stage | ✅(값 확인) |
| inspectionTime | inspection_date(Datetime) | ✅ |
| inspectorId | inspector_id | ✅ |
| visual/dimension/functionCheck | line_ids + characteristic | 🔁 |
| measuredValues(Json) | line_ids(measured_value) | 🔁 정규화 |
| result | result | ✅ |
| remarks | notes | ✅ |
| 💡 MO 연동 | production_id (mrp.production) | ✅이미연동 |
→ **작업량 中**: shift 추가, inspection_stage 값 회사양식(초/중/종물) 정합, 뷰 정렬, measuredValues→line 정규화 확인.

### A-3. ShippingInspection (출하검사) → ⚠️갭분석 정정
**기존 "신규 필요"였으나 — `iatf.process.inspection`에 OQC(출하) 단계 필드(`oqc_count`, `oqc_inspection_ids`) 존재.**
→ **선택지**: (a) process_inspection의 OQC 단계로 흡수 / (b) 별도 `iatf.shipping.inspection` 신규.
회사양식(ShippingInspection: 포장검사/라벨검사 packagingCheck/labelCheck 고유 필드)이 **포장·라벨 항목을 강조**하므로, **별도 경량 모델(b) 권장** 가능성. → ★사용자/현업 확인 필요.
Prisma 고유필드: destination, packagingCheck, labelCheck (포장·라벨은 OQC에 없음 → 추가 대상)

### A-4. InspectionRecord / InspectionDetail (범용 검사기록/상세)
→ Odoo는 각 검사유형이 line_ids(상세) 구조로 이미 분리돼 있음. 범용 InspectionRecord는 **직접 1:1 대응보다, 각 검사모델의 line으로 흡수**가 자연스러움. (중복 신규 불필요)

**클러스터 A 요약**: 수입·공정검사는 **기존 모델 보강(필드 몇 개+뷰)** 으로 충분. 출하검사만 신규/흡수 결정 필요. 검사 전반이 Odoo에 이미 잘 구현돼 있어 **신규 개발보다 "회사양식 정합"이 주작업**.

---

## 클러스터 B — 측정/시험 (Measurement & Test)  [작성: 2회차]

### B-1. GageRnrStudy (MSA) → `iatf.msa.study`  ✅거의 완벽 대응
grr, ndc, repeatability, reproducibility, part_variation, num_operators/parts/trials, usl/lsl/tolerance, study_type, pct_grr/av/ev/pv, measurement_ids(상세) **전부 존재**. Prisma의 `result`→`grr_status`, `gageRnr`→`grr`, `rawData`→measurement_ids로 정규화.
→ **작업량 極小**: part 링크(product_id) 보강 + 뷰 회사양식 정렬. **신규 0.**

### B-2. ProcessCapability (SPC) → `iatf.spc.study`  ✅거의 완벽 대응
cp/cpk/pp/ppk, usl/lsl, std_dev, grand_mean(→mean), nominal(→target), capability_status(→result), subgroup_ids, workcenter_id 연동 **전부 존재**.
→ **작업량 極小**: 뷰 정합. **신규 0.**

### B-3. 도장특화 시험 4종 → 🆕**신규 (Odoo 대응 전무)**  ★진짜 신규 작업
공장 도장 공정 전용. 한 신규 모듈(`iatf_paint_test` 등)로 묶는 것 권장:
| Prisma 모델 | 핵심 필드 | 비고 |
|---|---|---|
| **AdhesionTest**(밀착성) | color, position1/2Grade·Result, overallResult | 크로스컷 등급 |
| **ColorMeasurement**(색상) | deltaL/A/B/E, standardPlateNo, color | 색차계 ΔE |
| **CoatingThickness**(도막두께) | position1~5, averageThickness, specMin/Max | 5점 측정 |
| **ReliabilityTest**(신뢰성) | testType, testStandard, testConditions(Json), measuredValues, reportNo | 범용 신뢰성 |
공통: partId(product), testDate, result, testerId(user), 첨부. → product/lot/MO 연동 + 승인(activity) 배선.
→ **작업량 中**: 모델 4개 + 뷰 + 메뉴 신규. 단 구조 단순(측정값+판정). **이 클러스터가 IATF 신규개발의 핵심 덩어리.**

**클러스터 B 요약**: MSA/SPC = 보강만(신규0). **신규는 도장특화 4종뿐** → 갭분석의 "신규 ~9개" 중 4개가 여기 집중. 도장 공장 특화라 회사양식·규격(ΔE 기준, 도막 spec, 크로스컷 등급) **현업 확인 필요**.
