# 운영 UAT 오류 수정 동기화 및 배포 기록

## 요청과 범위

2026-10-28 사용자가 이 채팅에서 운영 UAT 오류와 Claude 참고 자료의 재현 가능한 오류 수정을 지시했고, “CI 러너 복구 후 적용”을 조건으로 정했다. CI 운영 분리·운영 접근 차단·자원 상한·작업 전후 컨테이너/방화벽 캡처 조건도 직접 승인했다.

- 정본: escon-odoo/odoo_gh main, PR https://github.com/escon-odoo/odoo_gh/pull/18
- 정본 병합/배포 SHA: `428868c4f88c75ee7a8be4f461b3903429312b17`
- 이 브랜치: `codex/prod-uat-fixes-archive-20261028`, 대상 wilcoco/odoo `18.0` 보관용 사본
- 보관용 기준: `201f8bb2ebbc9b07627d7b2d33e6eb13b63711cc`
- 대응: 정본 `iatf_plugins/iatf_approval`, `iatf_plugins/iatf_change_management` → 보관용 `addons_custom/` 동일 모듈. 6파일을 정본 병합 커밋에서 직접 복사하며 의도적 차이는 없다.
- MES 전용 바코드·사출 모듈과 CI 구성은 odoo_gh 정본에 유지한다. 보관용 저장소를 운영에 직접 탑재하지 않는다.

## 변경과 검증

결재 오류의 한국어 안내를 보완하고 변경관리 검증 시작에도 지정 검증자/실행자 분리 조건을 적용한다. 기존 승인 규칙과 완료 이력은 유지한다. 상세 설계와 C1~C8 판정은 정본 PR의 `docs/tasks/작업/codex/prod-uat-fixes-20261028.md`에 있다.

실제 GitHub CI: https://github.com/escon-odoo/odoo_gh/actions/runs/40620651108. 신규 설치 451건 및 오프라인 복제 DB 업그레이드 후 451건에서 실패/오류 0. 선택 모듈 iatf_quality_precedence 부재로 해당 조건부 시험 18건은 각 실행에서 건너뛰었다. 임계값/권한/승인 가드를 완화하거나 실패 시험을 제외하지 않았다. 초기 실패는 누락 통합 모듈 및 합성 시험 데이터 문제를 수정한 뒤 전체 재검증했다.

시험 checkout `18638381912f9e9de21fb86015bcc3fc6bbfb06a`와 실제 병합 커밋의 Git tree `1a6479fb0ae8fffdff7710eb10e8d55482baddb6`가 같음을 확인했다. CI는 전용 DB/네트워크, non-root, 운영 Docker socket/DB 설정 없음, 운영망 차단 상태다. 러너 4 CPU/10 GiB, PostgreSQL 2 CPU/4 GiB 상한이다. 운영 컨테이너 변경 0/기존 방화벽 규칙 삭제 0인 전후 캡처는 `/db/codex-rehearsal/prod-uat-fixes-20261028/ci-*.json`, `ci-firewall-*.rules`에 있다.

## 실제 운영 반영

- URL `http://10.10.21.20`, 컨테이너 `odoo_green`, DB `odoo18`
- 백업 `/db/backups/prod-uat-fixes-20261028T024741Z`: DB·filestore·코드·설정·이전 Git bundle 및 체크섬
- 중지 `2026-10-28T02:47:56.455384+00:00` / 재기동 `2026-10-28T02:50:19.616355+00:00` (UTC)
- 모듈: `{"escon_mo_barcode": "18.0.0.10", "injection_worksite": "18.0.8.15.2", "iatf_change_management": "18.0.1.1.1", "iatf_approval": "18.0.1.3.2"}`
- 업무 자료 50개 테이블의 건수/내용 해시 보존. SQ·운영 체크리스트·결재·생산·LOT·재고·전표·계정 포함. HTTP 200 및 운영 MO의 HTML/PDF 바코드 출력 성공.
- 활성 시험 계정 0 / 내부 사용자 3 / SQ 제안 ON 0. 계정 추가/활성화 및 미정 기준값 입력 없음.
- 실제 프린터·물리 스캐너 인수시험은 미실행. 공유 8070의 변경 작업은 이번 배포에 포함하지 않는다.
- 업그레이드 및 재기동 이후 애플리케이션 ERROR/CRITICAL/Traceback 없음. 모듈 설명문 렌더링의 docutils 서식 경고는 남아 있으며 같은 경고를 복제 CI에서도 확인했다. 운영 출력 오류와 구분한다.

원본 실행 기록: `/db/codex-rehearsal/prod-uat-fixes-20261028/deployment.json`, `production-verification.json`, 백업 폴더의 `upgrade.log`, `preservation.json`. 실패 시 중지 백업으로 복구하며 검증 실패 상태로 운영을 열지 않는 절차를 준비했다.
