수신: 아스트라(Codex Spark)
발신: 개발(지휘)
상태: 요청

## 사용자 질문 (2026-09-14 19:2x KST, 원문) — "깃 메인에 푸시 안했나??" → "아스트라한테 물어봐"

## 현재 사실
- `wilcoco/odoo-uat` **main 은 `751b6e6` 그대로**(push 안 함, ls-remote 로 확인). 올린 것은 새 브랜치 3개만: `cand/r134-carryover-20260914` 2dde5ea · `cand/r135-sequencing-20260914` 1538fa7 · `cand/r136-factory-flow-20260914` fce625c (각각 main 위 커밋 1개, 모듈 디렉터리 통째 교체).
- `railway.toml` 은 Dockerfile 빌드·`/uat-health` 헬스체크만 있고 브랜치 지정 없음 → Railway 가 어느 브랜치를 배포하는지는 Railway 대시보드 설정(우리가 못 봄). 통상 main.
- 큐 규칙 §7: 운영·배포 변경은 사용자 `승인:` 줄이 있어야 실행. odoo-uat main 은 Railway UAT 가 배포하는 브랜치일 가능성이 높아 "Railway UAT 변경 금지" 에 걸린다고 개발은 판단해 main 에 올리지 않았음.

## 질의
1. 사용자 의도가 **odoo-uat main 반영**(= Railway UAT 재배포)인지, 원도영 열람용 브랜치 게시로 충분한지 — 아스트라(사용자 창구) 가 확인해 주십시오.
2. main 반영이 맞다면: (a) 세 후보를 main 에 머지하는 순서·방식(PR 3개 vs 통합 브랜치 1개), (b) R136 후보는 화면 미구현·시험만 통과(41b2c1b, cand 는 b7fa70b 판)라 제외 권고인지, (c) 사전 조건(합성 DB 만 검증됨, 운영 복제 마이그레이션 미검증 — R135 `sequencing_mode` upgrade 시 legacy 유지 확인 필요) 을 사용자에게 어떻게 보고할지.
3. 사용자 `승인:` 줄이 이 파일 또는 회신에 오면 개발이 실행합니다. 그 전엔 main 무변경.

수신 ACK 를 남겨 주십시오.
