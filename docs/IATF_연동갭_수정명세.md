# IATF ↔ Odoo 핵심 데이터 연동 갭 분석 + 수정 명세 (IATF 세션 인계용)

작성: 2026-06-26 (QA 세션). 결정: **자체모델 유지 + 연동 보강**(IATF 검사/공정 모델은 그대로, Odoo 핵심을 Many2one/compute로 끌어오게 연결만 추가). 수정은 feat/iatf-company-forms 에서.

## 1. 통합 비교표 (IATF 80모델 ↔ Odoo 핵심)

### ✅ 잘 연동됨 (수정 불필요)
| IATF 모델 | Odoo 핵심 연동 |
|---|---|
| process.inspection ⭐ | mrp.production·mrp.workorder·mrp.workcenter·stock.lot·iatf.control.plan |
| nonconformity | mrp.production·stock.move·stock.lot·product |
| incoming.inspection | purchase.order·stock.picking·stock.lot·product |
| shipping/layout.inspection·scar·customer.complaint | stock.picking·stock.lot·product |
| equipment | mrp.workcenter·maintenance.equipment |
| recall.simulation | mrp.production·stock.move·stock.lot |
| competence.matrix | hr.employee·hr.department |
| (대부분) | product.product·res.partner·res.users |

### 🔴 연동 갭 (수정 대상)
| # | 갭 | 현재 상태 |
|---|---|---|
| G1 | BOM 미연동 | IATF 어느 모델도 mrp.bom 참조 안 함 |
| G2 | quality_control 미연동 | 자체 검사모델만, Odoo quality.check/alert 안 씀 (injection_worksite는 quality_control 사용 → 품질결과 2곳 분산) |
| G3 | 공정마스터 단절 | iatf.process 가 mrp.workcenter/라우팅 연동 없음 |
| G4 | 대시보드 미집계 | iatf.dashboard compute 46개가 실적모델(부적합/검사/감사) 안 끌어옴 |
| G5 | 품질목표 부분집계 | iatf.quality.objective 가 stock.picking(납기)만, 검사/부적합 실적 미연동 |

---

## 2. 갭별 수정 명세 (자체모델 유지 + 연동 보강)

### G1 — BOM 연동 (관리계획서·PPAP·FMEA)
- **control.plan / ppap.submission / fmea** 에 `bom_id = Many2one('mrp.bom')` 추가 (product_id 기반 default/onchange로 해당 제품 BOM 자동 제안).
- (선택) control.plan.line 이 BOM 구성품(bom_line)을 끌어와 관리특성 자동 생성 보조.
- 효과: "이 부품의 BOM 구조"를 품질문서가 공유. product 만으로는 다단계 못 봄.

### G2 — quality_control 브리지 (이중관리 해소)
- 자체 IATF 검사 유지하되, **부적합(iatf.nonconformity) ↔ quality.alert 양방향 링크** 추가:
  `nonconformity.quality_alert_id = Many2one('quality.alert')`, 생성 시 옵션으로 quality.alert 동기 생성.
- injection_worksite(현장 품질=quality_control)에서 발생한 alert → IATF 부적합으로 승격하는 액션.
- 효과: 현장(quality_control)과 IATF 품질결과가 한 줄로 연결(분산 해소). 모델 통합은 안 함.

### G3 — 공정마스터 연동
- **iatf.process** 에 `workcenter_id = Many2one('mrp.workcenter')` (+ 선택 `operation_id = mrp.routing.workcenter`) 추가.
- 효과: IATF 공정 기준정보가 제조 작업장과 연결 → 공정검사·관리계획의 공정이 실제 작업장 기준.

### G4 — 대시보드 실적집계 (★핵심, 가치 큼)
- iatf.dashboard 의 지표 compute 들을 **실제 결과 모델 집계**로 교체:
  - 부적합 건수/추이 ← `env['iatf.nonconformity'].search_count/read_group(기간·상태)`
  - 검사 합격률 ← iatf.process.inspection / incoming.inspection 의 result 집계
  - 시정조치 진행 ← iatf.corrective.action 상태별 집계
  - 감사 지적 ← iatf.audit / audit.finding 집계
- 효과: 품질지수가 실제 공정 평가결과를 반영(현재는 수동/플레이스홀더).

### G5 — 품질목표 실적연동
- iatf.quality.objective._compute_achievement 가 **목표유형별 실제값**을 끌어오게:
  - 불량률 목표 ← nonconformity / 생산수량(mrp.production) 기반 PPM
  - 검사합격률 ← inspection result 집계
  - 납기준수 ← (기존 stock.picking) 유지
- `actual_value` 를 수동입력이 아닌 compute(stored) 로 — 목표 카테고리에 따라 소스 분기.

---

## 3. 검증 방법 (수정 후)
- 각 보강 필드/compute -u 클린.
- 실데이터로: 부적합 1건 생성 → 대시보드/품질목표 수치 증가 확인.
- 회귀: P3(MO 생성→완료) 영향 없음 확인.
- 충돌규칙(인계문서 4번) 준수: 표준모델 override 없음(필드 추가만이라 안전).

## 4. 우선순위 (권장)
G4 → G5 (품질지수 실적연동, 가치 최대) → G3(공정마스터, 작음) → G1(BOM) → G2(quality_control 브리지, 설계 더 필요).

---

## ✅ 5. 구현 완료 (2026-06-26, feat/iatf-company-forms)
| 갭 | 구현 | 커밋 | 비고 |
|---|---|---|---|
| **G4** | 대시보드 실적집계 보강 — 검사 합격률(iqc/pqc_pass_rate) + 시정조치(ca_open/ca_overdue) 타일 | `e6b0fb08` | 기존엔 부적합/검사/감사 건수만, 합격률·시정조치 누락분 추가 |
| **G5** | 품질목표 자동집계: 검사합격률/부적합 소스 추가 **+ 선행 버그 수정** | `e0457fde` | ★`env.get()` 빈recordset falsy로 _calc_* 가 항상 0 반환하던 버그 발견·수정 → 자동KPI 실작동 |
| **G3** | iatf.process.workcenter_id/operation_id (공정마스터↔작업장/라우팅) | `6a6a1d9d` | iatf_jig depends += mrp |
| **G1** | control.plan·ppap·fmea 에 bom_id + 제품→BOM 자동제안 onchange | `94126f9d` | iatf_fmea depends += mrp |
| **G2** | iatf.nonconformity ↔ quality.alert 양방향 브리지(승격/동기생성) | `ca8dbe26` | ★별도 옵션모듈 iatf_quality_bridge 로 enterprise 의존 격리 |

**검증**: 각 보강 -u/-i 클린 + 실데이터 집계 정확(합격률 50%, PPM 600000, ca/pass_rate/bom onchange/
양방향 링크 전부 확인). 표준모델 override 없음 → MO e2e 무관(기준선 유지).

**설계 메모**
- G5 에서 드러난 `env.get(model)` 진리값 버그는 동일 패턴이 타 모듈에도 있을 수 있음 → 점검 권장
  (존재판정은 `model in self.env` 사용).
- G2 는 핵심 IATF 의 enterprise 비의존 원칙 유지를 위해 브리지 모듈로 분리. quality_control 미설치
  환경에선 iatf_quality_bridge 만 미설치하면 됨.
