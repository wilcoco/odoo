# BOM 보호와 제조 EO 변경요청 단일화

- 사용자 직접 요청(2026-10-21): 최신 main + BOM 보호 + 제조 EO 통합 및 격리 시험. 운영 변경 금지.
- 정본: wilcoco/odoo, codex/eo-change-management, 기준 01f4035c442f (18.0).
- 변경: addons_custom/iatf_change_management 18.0.1.1.0. BOM 저장 시 자동 CR 생성/미승인 CR 잠금 훅을 제거한다. 기존 change_locked 필드 및 모든 CR 행은 보존한다. EO는 기존 iatf.change.request 한 건을 사용한다. 일반 4M 흐름은 유지한다.
- 출처: 확보된 UAT Git 객체 01e334e8ab9c101e526412897f3e9561e8b44365의 addons/iatf_change_management 두 파일. 최신 정본과 차이는 해당 두 파일뿐이다.
- 시험 미러: escon-odoo/odoo_gh codex/eo-bom-protection의 iatf_plugins/iatf_change_management. 이 후보 정본과 바이트 일치를 확인하여 격리 통합 시험한다. 정본 18.0 병합 전이므로 운영 동기화 완료로 간주하지 않는다.
- 보호 책임: 활성/구버전 BOM 편집 차단과 개정 결재/불변 변경 이력은 escon_bom_util 3.x, EO 승인/적용은 escon_manufacturing_eo가 담당한다. 이 변경만 단독 설치해 기존 BOM 통제를 해제하지 않는다.
- 검증: 통합 브랜치의 EO·BOM 보호·기존 4M 회귀와 실제 품번/BR/이종검사 및 기존 행 보존 대조 예정. 결과는 같은 문서에 후속 기록한다.
- 적용: 운영 미실행. 두 저장소 PR/최종 조합 검증 및 별도 승인 후 iatf_change_management, escon_bom_util, escon_manufacturing_eo를 함께 반영한다. 복구는 대상 환경의 코드·DB·filestore 동일 시점 백업을 사용한다.
- 담당: 사용자 요청을 받은 서버 측 Codex. 추가 에이전트 위임 없음. 작업·검증 기록은 이 브랜치 및 통합 브랜치에 보존한다.
