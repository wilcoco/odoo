# BOM 보호와 제조 EO 변경요청 단일화

- 사용자 직접 요청(2026-10-21): 최신 main + BOM 보호 + 제조 EO 통합 및 격리 시험. 운영 변경 금지.
- 정본: wilcoco/odoo, codex/eo-change-management, 기준 01f4035c442f (18.0).
- 변경: addons_custom/iatf_change_management 18.0.1.1.0. BOM 저장 시 자동 CR 생성/미승인 CR 잠금 훅을 제거한다. 기존 change_locked 필드 및 모든 CR 행은 보존한다. EO는 기존 iatf.change.request 한 건을 사용한다. 일반 4M 흐름은 유지한다.
- 출처: 확보된 UAT Git 객체 01e334e8ab9c101e526412897f3e9561e8b44365의 addons/iatf_change_management 두 파일. 최신 정본과 차이는 해당 두 파일뿐이다.
- 시험 미러: escon-odoo/odoo_gh codex/eo-bom-protection의 iatf_plugins/iatf_change_management. 이 후보 정본과 바이트 일치를 확인하여 격리 통합 시험한다. 정본 18.0 병합 전이므로 운영 동기화 완료로 간주하지 않는다.
- 보호 책임: 활성/구버전 BOM 편집 차단과 개정 결재/불변 변경 이력은 escon_bom_util 3.x, EO 승인/적용은 escon_manufacturing_eo가 담당한다. 이 변경만 단독 설치해 기존 BOM 통제를 해제하지 않는다.
- 검증: 배포 미러 코드 `5777291df6d7bca476dfa406d480e954e6ba6af1`, 독립 DB `odoo18_eo_integration_20261021`에서 EO·BOM 보호·BR·EJ·생산 게이트·결재 회귀 133건(기존 4M 포함) 실패0/오류0. 실제 품번 `865A0-5S140CA`의 EO 반려·재승인·적용·검증 종료와 구/신 BR·검사14건, 43조건 통과. CR 증가1/추가 결재0. 기존 CR29건을 포함한 9테이블8,119행의 전체 기존 컬럼 해시 및 원본 시험 DB 해시 동일. 운영/기존8070/8071 이미지·시작시각 및 운영GitSHA 유지.
- 검증 명령/환경/로그: 배포 미러 `scripts/eo_integration/run.py`의 13모듈 업그레이드·선별 테스트, `scenario_run.py`, `verify.py`. 서버 로그 `/db/codex-testdb/eo-bom-protection-20261021/evidence/upgrade-tests-20261020T212135.log`. Odoo18 Enterprise+MES 이미지 `sha256:59eff15ab7d5bb3cfb880b6c7153c6d35d39ea50bd2bc5a6c565fbab91675e2d`. 전체 결과와 원본 대응 SHA는 [미러 검증 보고서](https://github.com/escon-odoo/odoo_gh/blob/codex/eo-bom-protection/docs/testing/eo-bom-protection/REPORT.md)에 있다.
- 이 정본 코드 커밋은 `92148cf3`이며 이후 이 브랜치 변경은 결과 문서뿐이다. 미러의 `iatf_plugins/iatf_change_management` 두 변경 파일과 Git blob이 동일하다. 검토 PR은 초안으로 제출하고 18.0/main 병합·운영 반영은 수행하지 않는다.
- 적용: 운영 미실행. 두 저장소 PR/최종 조합 검증 및 별도 승인 후 iatf_change_management, escon_bom_util, escon_manufacturing_eo를 함께 반영한다. 복구는 대상 환경의 코드·DB·filestore 동일 시점 백업을 사용한다.
- 담당: 사용자 요청을 받은 서버 측 Codex. 추가 에이전트 위임 없음. 작업·검증 기록은 이 브랜치 및 통합 브랜치에 보존한다.
- 큐: wilcoco/odoo handoff `docs/tasks/20261021-01_to-아스트라_from-서버_제조EO_BOM보호_통합시험완료.md`. 최신 후보 브라우저 클릭/실물 인수 및 운영의 EO 신규 설치 리허설은 별도이며 이번 결과로 SQ 전체 심사 충족을 주장하지 않는다.
