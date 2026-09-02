# [개발 요청] SQ 평가 대응 — 사출·조립 공통 기능 개발

발신: UAT/문서 세션 · 2026-09-03 · 수신: 개발 세션
근거: `docs/SQ평가_사출_ERP준비상태.md`, `docs/SW조립장_SQ_ERP대응_분류표.md`
(원본: 현대·기아 SQ 마크평가 Ver4 — PL사출 평가서, SW 조립장 준비 LIST)

## 0. 왜 하는가 (한 문단)

현대·기아 SQ 평가는 **배점 환산이 우수 100% / 양호 80% / 보완 60%** 이고,
**우수와 양호를 가르는 조건이 "이행실적의 정기적 이상유무 확인 또는 지속 모니터링"** 이다.
즉 종이·수기로는 80%가 천장이고, **시스템 기록·집계·이상탐지가 있어야 100%** 다.
동일 업종 평가 실사례(㈜크리아, 698.5/1000)에서 감점 사유 대부분이
**"기준은 있는데 실적 기록이 누락/부족"** 이었다 — 우리가 시스템으로 막을 수 있는 유형이다.

---

## 1. 우선순위 1 — 금형 관리 이력 (배점 130점, 현재 완전구현 0/7)

**정본 모듈: `iatf_mold`** (신규 모듈 만들지 말 것 — 대장·보전이력이 이미 있음)

기존:
- `iatf.mold` — 금형 대장 (product_id, ownership, state, responsible_id …)
- `iatf.mold.maintenance` — 보전/수리 이력 (maintenance_type, date, result, state)
- `mrp.production.mold_id` — MO 연결 (기구현)

### 1-1. 금형 관리등급 (선행 — 나머지 기능의 주기 기준)

`iatf.mold` 에 추가:
```python
grade = fields.Selection([("a","A"),("b","B"),("c","C")], string="관리등급", tracking=True)
check_cycle_days   = fields.Integer(string="일상점검 주기(일)", default=1)
clean_cycle_days   = fields.Integer(string="세척 주기(일)")      # 예: 180/240
preheat_temp_min   = fields.Float(string="예열 하한(℃)")
preheat_temp_max   = fields.Float(string="예열 상한(℃)")
mold_temp_min      = fields.Float(string="금형온도 하한(℃)")
mold_temp_max      = fields.Float(string="금형온도 상한(℃)")
```
> 등급 체계(A/B/C)가 사내에 이미 있는지 **확인 후 반영** — 없으면 위 3단계로 시작.

### 1-2. 금형 일상/정기 점검 (SQ 4_1 · 20점)

**`iatf.mold.check`** — `iatf.daily.check`(설비) 패턴을 그대로 따를 것.
설비 일상점검(`iatf_equipment/models/daily_check.py`)이 헤더+라인+종합판정+시퀀스로
잘 만들어져 있으니 **구조를 복사**하고 대상만 금형으로 바꾼다.

```python
class IatfMoldCheck(models.Model):
    _name = "iatf.mold.check"
    _description = "금형 일상/정기 점검"
    name        = Char (시퀀스)
    mold_id     = Many2one("iatf.mold", required, index)
    check_type  = Selection([("daily","일상"),("periodic","정기")])
    check_date  = Date, shift = Selection(day/evening/night)
    checker_id  = Many2one("res.users")
    line_ids    = One2many("iatf.mold.check.line")
    overall_result = compute (라인에 ng 있으면 issue)
    production_id  = Many2one("mrp.production")   # 어느 생산과 연결된 점검인지
```
**감점 방지 포인트(크리아 4_1 지적: "점검표 작성 일부 누락")**
→ **누락 집계**가 핵심이다. `iatf.mold` 에 계산 필드로
`last_check_date`, `next_check_due`, `is_check_overdue` 를 두고,
**기한 경과 금형 목록/카운트**를 볼 수 있게 할 것. (이게 "지속 모니터링" 증빙이 된다)

### 1-3. 금형 세척 계획 대비 실적 (SQ 4_2 · 20점)

`iatf.mold.maintenance` 의 `maintenance_type` 에 **"세척"** 이 없으면 추가하고,
`iatf.mold` 에 `last_clean_date` / `next_clean_due` / `is_clean_overdue` 계산 필드 추가.
→ **계획 대비 실적 목록**(예정일 지난 금형)이 화면으로 나와야 한다.

### 1-4. 금형 예열 일보 + 온도 측정 이력 (SQ 4_6·4_7 · 합 40점)

```python
class IatfMoldTempLog(models.Model):
    _name = "iatf.mold.temp.log"
    _description = "금형 예열/온도 측정 이력"
    mold_id     = Many2one("iatf.mold", required)
    log_type    = Selection([("preheat","예열"),("operating","가동중 온도")])
    measured_at = Datetime, shift
    method      = Selection([("ir","적외선"),("contact","접촉식"),("sensor","설비센서")])
    point       = Selection([("fixed","고정측"),("moving","이동측")])  # 크리아 4_7 지적사항
    temperature = Float
    is_in_spec  = compute  # mold_id 의 상·하한과 대조
    production_id = Many2one("mrp.production")
```
**크리아 지적**: "적외선 온도계로 고정측/이동측 측정 방식 개선 필요"
→ **측정 부위(고정/이동)와 방식을 필수 기록**하게 하면 그 지적을 선제 차단한다.

### 1-5. 시사출(T/O) 보고서 (SQ 4_5 · 20점)

```python
class IatfMoldTryout(models.Model):
    _name = "iatf.mold.tryout"
    _description = "시사출(T/O) 보고서"
    mold_id, tryout_date, tryout_no (차수)
    reason      = Selection([("new","신규제작"),("transfer","이관"),("repair","수정 후")])
    shot_count  = Integer            # 초기 허용불량과 연계 (아래 3-3)
    ok_qty / ng_qty = Integer
    conclusion  = Selection([("pass","합격"),("rework","재수정"),("hold","보류")])
    inspection_id = Many2one("iatf.process.inspection")   # 수정 초품 검사 연계 (SQ 4_3)
    attachment   = 첨부
```
크리아 4_5 감점 사유가 **"이관품 시사출 보고서 작성 누락"** 이므로,
**금형 state 가 '이관/양산전환' 으로 갈 때 T/O 보고서가 없으면 경고**를 띄우면 좋다.

---

## 2. 우선순위 2 — 범용 점검 일지 (사출·조립 공통, 다수 항목 동시 해결)

**하나의 모델로 아래를 전부 덮는다** (개별 모듈 금지):

| 적용 대상 | 관련 SQ 항목 |
|---|---|
| 전동공구 토크 점검 / 통전검사 마스터 / 바코드 마스터 | SW 조립장 1_5·1_6 (각 5개 항목 반복 요구) |
| 원소재 건조기(호퍼드라이) 필터·공급라인 | 사출 3_3 |
| 분쇄기·배합기 일상점검 | 사출 3_4 |
| 냉각수·작동유 온도 F-PROOF 점검 | 사출 1_7 |
| 조도 측정 / 3정5행 / 소화기 | 사출 6_8·6_9 / SW 5_1·5_9 |

```python
class IatfCheckSheet(models.Model):        # 점검 마스터(무엇을 어떤 주기로)
    _name = "iatf.check.sheet"
    name, code
    target_type = Selection([("tool","공구"),("master","검사마스터"),("facility","설비/시설"),
                             ("area","구역"),("etc","기타")])
    equipment_id / workcenter_id / area_ref  (선택적 연결)
    cycle       = Selection([("shift","교대"),("daily","일"),("weekly","주"),
                             ("monthly","월"),("event","발생시")])
    line_ids    = One2many("iatf.check.sheet.item")   # 점검 항목·판정기준·상하한

class IatfCheckRecord(models.Model):       # 실적(언제 누가 무엇을)
    _name = "iatf.check.record"
    sheet_id, check_date, shift, checker_id
    line_ids = One2many("iatf.check.record.line")     # 항목별 측정값/합부
    overall_result = compute
```
**필수**: 시트마다 `last_record_date` / `next_due` / `is_overdue` 계산 →
**미실시 목록**을 한 화면에서 볼 수 있어야 한다(= 지속 모니터링 증빙).

---

## 3. 우선순위 3 — 개별 신규 (배점 큰 순)

### 3-1. 안전관리 (사출 6_1 · **30점** — 크리아 최대 감점 7.5/30)
최소 범위: 위험성평가 대장 + 안전점검 이력 + 아차사고/사고 이력.
`iatf_work_environment` 확장으로 붙일지 신규 `iatf_safety` 로 갈지는 개발 판단.

### 3-2. 개선활동 등록·집계 (사출 6_7 · 20점)
크리아 지적: "25년 9월 1건 외 실적 없음".
`iatf_quality_objective`(목표)에 **개선활동(제안·실행·효과)** 을 붙이고 월별 집계.

### 3-3. 초기 허용불량 기준·이력 (사출 1_8 · 20점)
품목별 초기 허용불량 수량 기준(예: 8PCS) + **T/O·재가동 시 초물 폐기 실적**.
1-5 시사출, 그리고 **설비 재가동 시 LOT 구분**(사출 1_2, 이미 시리얼로 커버)과 연결.

### 3-4. 한도견본 관리 (사출 2_3 / SW 2_4)
견본 대장(품목·OK/NG·유효기간·보관위치·게시상태) + 갱신 이력.

### 3-5. 리워크 관리대장 (사출 6_10 / SW 5_10)
리워크 대상 선정기준·작업이력·재검사 결과. `iatf_nonconformity` 와 연결.

### 3-6. 정성품질 (사출 6_12 · 20점)
고객사 프로그램 — **요구 산출물 형태를 확인한 뒤** 착수(문서/게시판이면 개발 불필요).

---

## 4. 지켜야 할 것

1. **신규 모듈 남발 금지** — 금형은 `iatf_mold`, 점검은 위 공통 모델 하나로.
   (addons_custom/CLAUDE.md 의 정본 규칙)
2. **작업 단위별 브랜치 → PR.** 다른 세션 활성 브랜치에 얹지 말 것.
3. **메뉴 위치**: 최근 재구성(회사 운영 센터·원부자재 관리)과 정합되게 배치.
   경로 확인은 `scripts/menu_paths.py` 사용.
4. **테스트 동봉**: 각 기능마다 최소 ①정상 기록 생성 ②기한 경과(overdue) 판정
   ③상·하한 벗어난 측정값의 합부 판정 — 3종.
5. 완료 시 `docs/신호_테스트세션_할일.md` 에 회신 남길 것 (UAT 문서·매뉴얼 갱신 필요).

## 5. 담당자 확인 대기 (개발 착수 전 확인되면 좋음)

- **SQ 평가 예정일** — 우선순위 조정 기준
- **분쇄·배합 공정 유무** — 없으면 사출 1_10·3_4 '해당없음'(20점 제외) → 2항에서 제외 가능
- **융착 공정 유무** — 사출 2_9 및 조립장 연계
- **금형 관리등급(A/B/C) 체계 존재 여부** — 1-1 의 전제
