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

## 회신 (테스트, 2026-09-14 19:50) — 수신 ACK
- 14 수신. odoo-uat main `9901ecf` 반영(사용자 승인) 인지. 테스트 몫: 배포·main 변경 없음(역할 밖), 독립 판정·원로그 보존 유지.
- 10 UI 구현 기준을 exchange `41b2c1b` 로 갱신: `test/r136-cascade-ui-20260914` 를 41b2c1b 위로 rebase 후 같은 브랜치에 push(SHA 는 10 파일에 회신). 실행은 슬롯 배정 후.
- 배포 전 확인 항목 중 "upgrade 후 `sequencing_mode == legacy`" 는 합성 DB 에서 probe 로 확인한 바 있음(R135-TEST.md R141 절, 7/7) — seed/운영 복제 DB 에서의 확인은 별개이며 미검증.

## 회신 (개발, 2026-09-14 20:0x KST) — main 갱신: `9901ecf` → **`aa795ef`** (R136 캐스케이드 UI, 테스트 구현 cb0d7c8)
- 합성 DB 모듈 갱신·서버 시험 0/10 통과, **web_tour 는 격리 이미지에 websocket-client 없어 skip — 브라우저 미검증**. 배포 시 `cams_ops_dashboard` `-u` 필요(18.0.3.0.0). 메뉴: 운영 > "회사 운영 흐름".
- 서버/아스트라: 배포 회신(ACK) 아직 없음 — 배포 가능 시점과 private-runtime 보유자를 알려 주십시오.

## 회신 (개발, 2026-09-14 20:3x KST) — main 갱신: `aa795ef` → **`0954818`** (R136 어댑터 2차 확장, 격리 `6650335`)
- 연결 추가 6 노드: 공급사 계획(`outsource.planning.run`)·부품 입고(`stock.picking` incoming 만)·고객 클레임(`iatf.customer.complaint`)·설비 고장(`iatf.equipment.breakdown`)·계측기(`iatf.measurement.equipment`)·결재(`iatf.approval.request` 체계만). 부분 연결은 응답 `note` 로 드러냄. 합계 16/30 L2 연결.
- 시험 0 failed/11 (로그 `artifacts/r134_update_6650335_20260914T103254Z.log`). **정직히**: 검증 DB 에 `supplier_portal_purchase`·`iatf_customer_complaint`·`iatf_calibration` 이 설치돼 있지 않아 그 3 노드는 `not_installed` 경로만 확인됨(설치 후 재시험 진행 중, 결과 추가 회신). `-u cams_ops_dashboard` 필요.
