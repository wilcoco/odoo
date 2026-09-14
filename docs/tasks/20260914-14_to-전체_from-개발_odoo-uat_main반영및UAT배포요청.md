수신: 전체 (서버·아스트라·테스트)
발신: 개발(지휘)
상태: 요청

## 사용자 지시 (2026-09-14 19:4x KST, 채팅 직접) — "지금 많이 고쳤으니 그거 메인에 계속 수정해서 올려야 사용자 테스트를 할거 아닌가"
승인: 사용자(채팅 직접 지시) 2026-09-14 — odoo-uat main 반영. (13 의 질의는 이 지시로 답이 됨.)

## 반영 결과 — `wilcoco/odoo-uat` main `751b6e6` → **`9901ecf`** (fast-forward, 머지 커밋 3개)
| 머지 | 후보 | 내용 |
|---|---|---|
| `7d02273` | `cand/r134-carryover-20260914` 2dde5ea | gh_vendor_settlement 미결 이월 후속 |
| `cea396b` | `cand/r135-sequencing-20260914` 1538fa7 | injection_planning 교체 인지 순서·R141 (기존 DB `legacy` 유지, 신규 설치만 setup_aware) |
| `9901ecf` | `cand/r136-factory-flow-20260914` **7f90868**(41b2c1b 판, 시험 0/9) | cams_ops_dashboard 서버 어댑터 + 지도 — 화면은 아직 없음 |
합계 64 files +18792/−173. 격리 이력과 무관한 이식 커밋이라 모듈 디렉터리 통째 교체 — 범위 정본은 각 CHANGE-LEDGER.

## 배포는 별도 (README §11: Git push 만으로 배포되지 않음, private-runtime 준비한 번들을 `railway up --no-gitignore`)
- **서버(원도영) / 아스트라**: private-runtime(Enterprise·seed.dump·filestore) 보유자가 UAT 배포를 진행해 주십시오. 변경 모듈 `gh_vendor_settlement`·`injection_planning`·`cams_ops_dashboard` 는 **`-u` 업데이트 필요**(`deploy/start.py` 는 seed 복원만 하고 모듈 업데이트를 하지 않는 것으로 보임 — 확인 요망). 개발은 Enterprise·DB·비밀을 갖지 않으며 직접 배포하지 않습니다.
- 배포 전 확인: seed DB 에 `injection_planning` 설정이 있으면 upgrade 후 `sequencing_mode == legacy` 인지, `gh_vendor_settlement` 18.0.4.2.0 업그레이드 로그 오류 0.
- 앞으로도 수정분은 같은 방식(격리 검증 통과 → cand/* → main fast-forward)으로 main 에 계속 올립니다. 각 반영은 이 큐에 SHA 로 기록.

## 테스트
- 10(캐스케이딩 UI) 구현 기준을 exchange `41b2c1b` 로 갱신(시험 정정만). UI 완료분도 같은 경로로 main 에 갑니다.

수신 ACK 를 남겨 주십시오.
