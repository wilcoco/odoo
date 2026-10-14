# PR 패키지 — 8건 (제목·본문·순서·충돌 주의)

작성 2026-07-08 · 링크 클릭 → 제목/본문 붙여넣기 → Create. **스택 PR은 base 지정 필수**(compare 링크에 반영됨).

## 머지 순서 지도
```
[escon-odoo/odoo_gh]                          [wilcoco/odoo]
 ① fix/settlement-review ──► main              ⑥ fix/sim-found-defects ──► main
 ② feat/provisional-pricing ─► (①)             ⑦ feat/planning-safety-nets ─► (⑥)
 ③ feat/injection-costing ──► main             ⑧ feat/planning-optimization ─► (⑦)
 ④ feat/injection-actual-cost ► (③)
 ⑤ feat/plc-weight-capture ──► main   ※①과 파일 겹침 — ① 먼저, ⑤에서 사소 충돌 해결
```
스택(②④⑦⑧)은 부모가 머지되면 GitHub이 base를 자동으로 main으로 바꿔줌 → 순서대로 머지만 하면 됨.

---

## ① fix/settlement-review → main
🔗 https://github.com/escon-odoo/odoo_gh/compare/main...fix/settlement-review?expand=1
**제목**: `fix(settlement/worksite): 정산 결함·동시성·권한 수정 (시뮬 검증 4커밋)`

```markdown
## 무엇
전사 운영 시뮬레이션(5차)·적대 감사에서 발견된 정산/현장 결함 수정 묶음.

- 톤정산: 적재로그(silo.load.log) 기준 집계·재실행 가드·**동시 클릭 이중발행 방지**(bills_created 행 UPDATE 직렬화 — 동시 5→1장 검증)
- 정산 정밀: 계약단가 None/0원 구분 폴백, 사출 단위MO·톤정산 원재료 accrual 제외(이중계상 방지)
- 권한: 계약 톤단가·확정 정산 삭제를 회계관리자로 제한(P1·P2)
- 대시보드 KPI 실품번 대응, product settle_by_ton 자동 체크

## 검증
20명 동시사용 시뮬(권한 매트릭스·병렬 트랜잭션·승인 워크플로우) — docs/회사운영_5차_동시성권한승인_시뮬레이션.md

## 의존
없음(main 기반). ②feat/provisional-pricing 의 base.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ② feat/provisional-pricing → fix/settlement-review (스택)
🔗 https://github.com/escon-odoo/odoo_gh/compare/fix/settlement-review...feat/provisional-pricing?expand=1
**제목**: `feat(gh_provisional_pricing): 가단가→정단가 소급 정산 (매입·매출·B표준갱신)`

```markdown
## 무엇
자동차 가단가(임시)→정단가(확정) 라이프사이클 + 과거분 소급 자동화. 신규 모듈.

- 가/정 상태·확정일·합의근거 + **정단가 확정 = archive+insert**(overlap 제약 통과, supersede 감사추적)
- 매입 소급: (정−가)×기청구수량 → 추가청구/감액 **초안**(멱등 retro_bill_id·양방향·부분정산 경계·반려 재대상)
- 매출: customer.part.price 신설 + 발행 매출계산서 delta 수정전표(마진 restated)
- B안: 확정 시 부품 표준단가=정단가 + 완제품 표준 재계산(옵션)
- 가단가 노출 리포트, 확정 결과(전표 건수·합계) 알림

## 검증
§8 검증기준 전항목(멱등/양방향/부분정산/취소후재실행) + 독립 적대점검 결함 2건(P1 소급유실·P2 노출행 삭제) 수정 — docs/가단가_정단가_설계명세.md §9·§10

## 의존
base = fix/settlement-review (vendor.part.price company/overlap 사용). **① 머지 후 진행.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ③ feat/injection-costing → main
🔗 https://github.com/escon-odoo/odoo_gh/compare/main...feat/injection-costing?expand=1
**제목**: `feat(injection_worksite): capability→표준원가 공정 자동동기 브리지`

```markdown
## 무엇
사출 소요시간이 커스텀 capability(cycle/cavity)에만 있어 표준 원가엔진(BOM 공정+워크센터 요율)과 분리 → 가공비가 제품원가로 안 흐르던 공백 해소.

- capability create/write/unlink 시 제품별 대표 조합으로 BOM '사출성형' 공정 자동 upsert
- 공정시간 = cycle/cavity/60 (명목 표준 — 불량은 실제원가/차이분석 몫)
- standard_price 재계산은 '원가 계산'에 위임(마스터 편집이 평가를 조용히 안 바꿈) + 일괄 재동기 액션

## 검증
cams_sim3: 공정 강제삭제→복원, roll-up 재료+가공 표준가 일치 — docs/원가산출_현황과_capability원가연결.md

## 의존
없음(main 기반). ④의 base.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ④ feat/injection-actual-cost → feat/injection-costing (스택)
🔗 https://github.com/escon-odoo/odoo_gh/compare/feat/injection-costing...feat/injection-actual-cost?expand=1
**제목**: `feat(injection_costing): 실제원가(관리) 신규 모듈 — 표준vs실제·차이4분해·소급·정책설정`

```markdown
## 무엇
관리분석용 품목별 실제원가(회계 정본 아님 — valuation 무변경, 톤정산 충돌 회피).

- MO/LOT 실제원가: PLC 실측중량 우선(마커 True만) → 이상치(±15%)/결측 시 표준 대체 + 출처/사유
- 차이 4분해(재료 가격/수량·가공 능률·수율), **대사 정합**: (실제−표준)=가격+수량+능률 잔차 0
- frozen(마감 불변)/restated(단가이력 재계산)·retro_diff·월마감 정합등식(recon_ok) + 불일치 능동 경고
- 재료단가 = 생산일 유효 계약/톤단가(유효기간 매칭), 다품목 가격차이
- SQ 1_5 원단위 중량 대사(증빙 겸용), pivot/graph, 원가정책 설정(가공시간/재료수량 소스·허용범위)

## 검증
전사 시뮬 e2e + 소급(1,300→1,400) frozen 불변·소급차이 정확 — docs/실제원가_관리분석_설계.md, docs/원가시스템_회계CFO_검증보고서.md

## 의존
base = feat/injection-costing(브리지 메서드 사용). **③ 머지 후 진행.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ⑤ feat/plc-weight-capture → main
🔗 https://github.com/escon-odoo/odoo_gh/compare/main...feat/plc-weight-capture?expand=1
**제목**: `feat(injection_worksite): PLC 실측중량·사출품 자동식별·장애 백필`

```markdown
## 무엇
사출 실적 데이터 유입 3종 개선.

- **실측중량 수용**: /api/plc/complete 가 payload weight 를 읽음(없으면 더미 폴백) + weight_is_measured 출처 마커 — 원가 허위 커버리지 방지. 생산기록 폼 수동입력 허용(PLC 미연동 대비)
- **사출품 자동식별**: product.is_injection_part — 금형/capability 등록 시 자동 체크 + tracking=serial 자동(조립 이종검사·LOT 추적용, 백필 마이그레이션 포함)
- **장애 복구 백필**: PLC 자체채번(prefix 2/3) 미지 시리얼 → 단위 MO 소급 생성 수용, 재전송 멱등 ack, 원생산시각 기록, 완제품 시리얼(lot_producing_id) 자동 지정 — '임시 장부 없이 버퍼+백필' 원칙

## 검증
cams_sim3: 마커 실측/더미 판별, 금형 등록 즉시 플래그, 미지 2xxx 소급생성→done→멱등 ack — 커밋별 검증 로그 참조

## 충돌 주의
①(settlement)과 injection_worksite 파일 일부 겹침(manifest 버전·product_template·views) — **① 머지 후 본 PR에서 사소 충돌 해결**(양쪽 추가 필드 모두 유지).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ⑥ fix/sim-found-defects → main  (wilcoco/odoo)
🔗 https://github.com/wilcoco/odoo/compare/main...fix/sim-found-defects?expand=1
**제목**: `fix: 전사 시뮬 발견 결함 — 계획 재계산 가드(F1)·IATF 6건`

```markdown
## 무엇
전사 운영 시뮬레이션에서 발견된 결함 수정.

- injection_planning: 계획 재계산 서버 draft 가드(F1 — RPC 우회 시 수동조정 라인 유실 방지), BOM 전개 confirmed 수요 포함(재계산 데이터손실 방지)
- IATF 6건: supplier_evaluation 품질/납기/SCAR 산식, corrective_action 기본값, equipment 모델명 오타, packaging 상태값 등

## 의존
없음. ⑦⑧(계획 안전망·최적화)의 base.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ⑦ feat/planning-safety-nets → fix/sim-found-defects (스택)
🔗 https://github.com/wilcoco/odoo/compare/fix/sim-found-defects...feat/planning-safety-nets?expand=1
**제목**: `feat(injection_planning): 안전망·가시화 — 조용한 실패를 채터로 각인`

```markdown
## 무엇
전 기능 안전망 감사에서 확인된 '로그에만 남는 건너뜀'을 사용자 가시로 승격.

- Oracle 수요 품목 미매핑 → 제외 품번·행수 채터 보고(수요 누락 가시화)
- 계산 요약 채터: 배정 탈락(조합 없음)·capability 없음·**다중 활성 BOM(임의선택 안전망)**·비사출 수요 제외
- [G1] BOM 전개에서 비사출 구성품 제외(is_injection_part 방어적 확인+capability 폴백)
- [G3] 배정 정렬 수량순→납기(날짜)순

## 검증
cams_sim3: 배정 라인 사출품만, 경고 채터 게시, 회귀 없음 — docs/안전망_감사_가시화_배치.md

## 의존
base = fix/sim-found-defects. **⑥ 머지 후 진행.** ⑧의 base.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## ⑧ feat/planning-optimization → feat/planning-safety-nets (스택)
🔗 https://github.com/wilcoco/odoo/compare/feat/planning-safety-nets...feat/planning-optimization?expand=1
**제목**: `feat(injection_planning): 배정 최적화 — 형체력 적합성·유효능력·부하분산/병렬`

```markdown
## 무엇
배정이 '시간당능력 최대 1대 몰아주기' 단일 기준이던 것을 3축으로 개선.

- [G5] 형체력 적합성: 사출기 형체력(톤)·금형 요구 형체력 필드 신설 → 적합 조합만 배정(미등록 시 방어, 전 부적합 시 경고 후 진행)
- [G4] 유효능력: 선택·풀캐퍼 기준 = 능력×(1−불량률)
- [G4] 부하분산/병렬: 최적 기계 당일 가용 초과분을 차선 기계로 분할 — 동일일 2대 병렬

## 검증
cams_sim3: 요구 2000톤→1300톤기 제외 / 수요 3000→2대 병렬(1,402+1,128) / 불량50% 기계 회피. 금형교체 최소화·교대 타임라인 회귀 없음 — docs/사출계획_배정최적화_검토.md 이행표

## 의존
base = feat/planning-safety-nets. **⑦ 머지 후 진행.**

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## 머지 진행 체크리스트
- [ ] ① 열기·리뷰·머지 → [ ] ② base 자동 전환 확인 후 머지 → [ ] ⑤ 열기(충돌 시 양쪽 필드 유지로 해결)·머지
- [ ] ③ 머지 → [ ] ④ 머지
- [ ] ⑥ 머지 → [ ] ⑦ 머지 → [ ] ⑧ 머지
- [ ] 머지 후: 운영 배포 전 스테이징 -u 리허설 (injection_worksite·injection_costing·gh_provisional_pricing·injection_planning)
