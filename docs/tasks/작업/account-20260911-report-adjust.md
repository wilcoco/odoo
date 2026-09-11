# account/20260911-report-adjust — 손익계산서 보정

- 요청: 서버(회계 이관 담당), 2026-09-11
- 모듈: `account_kr_reports` 18.0.1.5.1 → **18.0.1.6.0**
- 운영 DB 직접 수정: **하지 않음** — 앱 업그레이드로만 반영

## 왜

손익계산서(KR)(`l10n_kr_reports.l10n_kr_pl`)를 정본 손익계산서로 쓰기로 했는데, 표준 모듈 데이터에 결함이 있었다.
기본 손익계산서(`account_reports.profit_and_loss`)는 계정 유형으로 집계하므로 계정 유형 설정이 틀린 곳이 그대로 드러났다.

| # | 보고서 | 결함 | 증상 |
|---|---|---|---|
| 1 | 손익계산서(KR) | 영업이익 = `KR_GRP + KR_EXP` | 영업이익·당기순이익이 판관비의 2배만큼 과대. 재무상태표(KR) 당기순이익도 같은 금액만큼 과대(전기이월이 상쇄해 합계만 일치) |
| 2 | 손익계산서(KR) | 법인세비용 = 계정 `63`만 | 더존 '법인세등'의 이관 계정 670001 누락 |
| 3 | 기본 손익계산서 | 42xxxx 14개 유형 `income` | 이자수익·잡이익이 매출액에 섞임 |
| 4 | 기본 손익계산서 | 610006 유형 `expense_depreciation` | 감가상각비가 영업외비용 칸으로 빠짐 |
| 5 | 기본 손익계산서 | NEP에 화면 추가 TAX 라인 미반영 | 법인세 계상 시 당기순이익 과대 |

## 무엇을 바꿨나

| 커밋 | 내용 | 실행 시점 |
|---|---|---|
| 1 | #1 `KR_GRP - KR_EXP`, #2 `63 + 67` | 마이그레이션 post-10 + 설치·업그레이드마다 재확인 |
| 2 | #3 42xxxx `income` → `income_other` | 마이그레이션 post-20 (1회) |
| 3 | #4 61xxxx `expense_depreciation` → `expense`, #5 NEP `- TAX.balance` | 마이그레이션 post-30 (1회) + #5는 업그레이드마다 재확인 |

- 로직: `tools/report_adjust.py` / 훅: `data/report_adjust_data.xml` → `kr.fs.line._kr_adjust_standard_reports`
- 수식은 **예상한 결함 수식과 같을 때만** 고친다. 화면에서 다른 수식으로 바꿔 둔 경우는 로그만 남긴다.
- 계정 유형 변경은 같은 그룹 안의 이동(수익↔수익, 비용↔비용)이라 전표·잔액·결산 이월에 영향이 없다.
- 남기는 한계: 오두에 '영업외비용' 계정 유형이 없어 620xxx는 기본 손익계산서에서 판관비로 잡힌다 → 한국식 구분은 손익계산서(KR)를 쓴다.

## 배포 (README §10)

1. PR → `wilcoco/odoo` 18.0 병합
2. `escon-odoo/odoo_gh` `iatf_plugins/account_kr_reports` 정본 동기화
3. 운영: `git pull` → `-u account_kr_reports` → 재기동
4. `l10n_kr_reports`나 `account_reports`만 따로 업그레이드했다면 `account_kr_reports`도 함께 `-u` 한다(수식 재확인)

## 배포 후 확인

- [ ] 서버 로그: `KR P&L formula backfill: fixed=2`, `non-operating income account type backfill: changed=14`, `Standard P&L backfill: depreciation_types=1, net_profit_tax=True`
- [ ] 손익계산서(KR): 영업이익 = 매출총이익 − 판매비와관리비
- [ ] 손익계산서(KR): 법인세차감전순이익 = 영업이익 + 영업외수익 − 영업외비용
- [ ] 재무상태표(KR): 당기순이익 = 손익계산서(KR) 당기순이익(같은 기간), 자산총계 = 부채와자본총계
- [ ] 기본 손익계산서: 이자수익·잡이익이 영업외수익 칸으로 이동
- [ ] 금액 대조는 회계 이관 작업 문서(사내 보관)의 분개장·시산표 대조값으로 한다

## 검증 상태

- 운영 DB 읽기 전용 조회로 결함·계정 코드 범위를 확인했다(사용 계정 29개 전부 KR 보고서 범위 안).
- `tests/test_report_adjust.py` 7건 추가. 로컬에서는 py_compile·XML 파싱만 확인했고 **Odoo 테스트 러너는 미실행** — 복제 DB에서 실행 필요.
