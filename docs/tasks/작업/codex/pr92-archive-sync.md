# 작업 기록: PR92 판정·근거 가드 보관용 동기화

- 요청: 대표의 CI 통과 후보 운영 반영 지시와 기존 A→B→C 별도 병합·보관용 동기화 범위. 담당: 서버 통합 담당.
- 정본: escon-odoo/odoo_gh PR92, 병합 61bb230b87bd732186ca575f203d6ddafd4327c4.
- 검증 후보 bd76083e7408d2b0ed84ff6c7f46d7da96cbec3d, base 9496ae138736f57de75a914c6741fed32d13a8cb.
- CI: https://github.com/escon-odoo/odoo_gh/actions/runs/42523171253 (attempt1). 필수 5 job 모두 success. 임시 병합과 최종 병합 트리 일치 확인.
- 보관용 기준 d8028c0838cfd3101575670c8b739cb0ccff28e9, codex/pr92-archive-sync → 18.0. 기준 브랜치 직접 push 없음.

## 변경과 보존

정본 iatf_plugins의 아래 모듈을 addons_custom으로 보관 동기화한다. PR92 가드와 이전 정본에 이미 포함된 의존 코드·시험을 함께 보관한다. 출하 모듈은 시험·버전 동기화이며 운영 갱신 대상 확대가 아니다.

| 모듈 | 버전 |
|---|---|
| `iatf_coating_test` | 18.0.1.2.0 |
| `iatf_document_control` | 18.0.1.3.0 |
| `iatf_incoming_inspection` | 18.0.2.3.0 |
| `iatf_layout_inspection` | 18.0.1.1.0 |
| `iatf_nonconformity` | 18.0.1.1.1 |
| `iatf_process_inspection` | 18.0.1.2.3 |
| `iatf_work_environment` | 18.0.1.5.2 |
| `iatf_shipping_inspection` | 18.0.1.0.2 |

기존 사본에는 아래 회사 규칙 파일과 매니페스트 등록이 없다. 회사별 자료 격리 신규 적용·확대 금지에 따라 파일 부재와 미등록을 보존한다. 이 기존 차이는 의도적으로 남긴다. 운영은 기존 회사 규칙을 가진 정본 소스를 사용하며 이 사본을 배포하지 않는다.

- `addons_custom/iatf_coating_test/security/r238_company_rules.xml`
- `addons_custom/iatf_document_control/security/r238_company_rules.xml`
- `addons_custom/iatf_layout_inspection/security/r238_company_rules.xml`
- `addons_custom/iatf_nonconformity/security/r238_company_rules.xml`
- `addons_custom/iatf_work_environment/security/r238_company_rules.xml`

그 외 내용은 정본 Git 객체와 같고 사본의 LF 줄바꿈을 유지했다. 정본 일부 파일의 CRLF→LF 차이는 비교에서 명시적으로 정규화했다. 기존 파일 삭제, 범위 밖 모듈 변경, 비밀·운영 원자료 전송 없음.

## 검증·인계

- 전용 clone/브랜치, 정확한 기준 SHA 및 시작 전 clean 확인. Git 객체 내용 대조, 의도적인 매니페스트 차이 대조, Python AST/XML 파싱, git diff --check 통과.
- 로컬 준비의 매니페스트 구문 오류, 상태 문자열 해석 가드 오류, 항목 뒤 공백 가정 오류 및 CRLF 검사 오류를 원문으로 보존했다. 항목만 제거하고 파일명 전용 조회·Git 객체 기반 복사·LF 보존으로 보완했다. 원격·운영 영향 없음.
- 정본 CI를 재실행하지 않았다. 보관용 Odoo/DB/브라우저 실행은 NOT_RUN이며 정본 CI 성공으로 대신하지 않는다.
- 운영은 정본의 별도 절차다. 7개 대상 중 도장시험이 미설치라 6개 갱신과 도장시험 신규 설치 포함 여부를 대표에게 확인 중이다. -u 종료를 미설치 모듈 반영으로 주장하지 않는다.
- 운영 중단·백업·설치·업그레이드·재기동 미실행. 실제 직전 기준선·보존·복구 조건 충족 후 승인된 방식으로 한 번 실행하고 로컬 영수증 및 지정 안전 큐에 기록한다. 임의 설정·권한 부여·업무값 입력 없음. 현장 인수는 별도이다.
