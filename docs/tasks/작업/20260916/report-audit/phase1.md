# 142 Phase 1 — LOT 해제 및 OQC 출하 가드

## 요청과 기준

- 원도영의 2026-09-16 직접 작업 지시. 142 검토의 Phase 1 구현, 41은 참고자료.
- 브랜치: `20260916/report-audit/phase1`. 사용자 지정 이름이 기본 브랜치 정규식보다 우선한다.
- ERP 기준: `17e9fac0eeeb7564e72e826caaf1865ba3b466a1` + Phase 0 기록 `4048b5c6d73e`.
- 통합 기준: odoo_gh `8326349e9f086c21f004dfe2df11276531130bd8` + Phase 0 기록 `eec31708`.
- handoff 참고 기준: `e6f1c0666eaedc60a89829a511ac810681e4310b`. 큐 문서로 운영 변경을 승인받은 작업이 아니다. 이번 요청은 로컬 작업 및 격리 복제 DB 검증이다.
- 원격 push/PR/병합/외부 회신/운영 배포는 수행하지 않는다.

## 변경

- `iatf_incoming_inspection` 18.0.1.0.1: 보류 LOT의 직접 해제 write를 차단한다. RPC 컨텍스트로 만들 수 없는 내부 토큰과 LOT ID를 묶어 IQC 정상 해제만 허용한다. IQC 쓰기 권한, 동일 LOT·품목·회사, 판정 완료 및 합격/조건부 합격을 확인한다.
- 소비 시점에도 보류 필드를 다시 읽는다. 정상 IQC 합격 후 실제 소비는 유지한다.
- `iatf_process_inspection` 18.0.1.0.3: 출하 버튼, picking 완료, move 완료에서 OQC 회사·품목·단계·판정·처분·기존 결재 완료 여부를 검사한다. hold, 미판정, 미승인, 누락은 출하할 수 없다.
- 첫 출하 시 OQC가 없으면 내부 생성 후 대기 알림을 반환한다. 예외로 신규 검사까지 롤백되는 무한 반복을 방지한다. 창고 사용자에게 검사 편집권을 추가하지 않고 출하 검증만 내부 조회한다.
- 작업 문서와 회귀 테스트를 같은 브랜치에 둔다.

## 검증

- WSL Ubuntu 22.04, `/opt/odoo`의 Odoo 18.0+e-20251117 코어.
- 원본 `esconodoo202609`에서 새로 복제한 `codex_142_p1_20260916_01`. cron/발신 메일 비활성, FDW 사용자 매핑 제거. 네트워크 네임스페이스 격리, UNIX socket 접속, HTTP/cron 프로세스 없음.
- ERP 검증: 공통 두 모듈은 ERP 워크트리, 나머지는 odoo_gh 워크트리의 symlink overlay. 실제 Python import 경로를 단언한다. 테스트는 TransactionCase 롤백.
- **15개 테스트 통과, 실패/오류/skip 0**. 직접 및 위조 컨텍스트 해제, 정상 IQC/소비, 다른 품목 검사, OQC hold/처분/미승인/누락/다른 품목, 정상 출하/특채, 신규 검사 생성, 기존 PQC 집계 회귀 포함.
- 창고 권한만으로 OQC 가드는 통과한다. 출하 전체 완료에는 기존 `iatf_packaging`의 포장 담당 권한도 필요해 해당 테스트에만 부여했다. 이 기존 권한 정책은 수정하지 않았다.
- 최초 실패 2회는 증거에 보관: 테스트의 상품 copy가 이 환경에서 빈 recordset을 반환하여 명시적 create로 수정; 신규 OQC 조회 ACL은 내부 조회로 보완; 기존 포장 ACL은 위와 같이 구분.

```powershell
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase1_test.py erp
```

증거: `C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/outputs/phase1_evidence/erp_tests.json`, `erp.log`, `erp_attempt1.json`, `erp_attempt2.json`, `clone_preparation.json`.

## 정본 → 미러

이 ERP 커밋을 먼저 확정한 뒤 변경한 10개 Python 파일만 `odoo_gh/iatf_plugins`에 포팅한다. `iatf_process_inspection/models/mrp_production.py`, `models/process_inspection.py`의 기존 미러 회사/SPC 보완은 보존한다. 미러 manifest 기존 18.0.1.0.2보다 높은 18.0.1.0.3으로 정렬한다. 정본 commit SHA 및 통합 검증 최종 결과는 미러의 동일 작업 문서에 기록한다. 정본 PR/병합 전의 로컬 통합 후보이며 공식 운영 반영이 아니다.

## 배포 조건과 범위 밖

- 미러 통합본에서 MES 스캔 및 사출 중량 변경과 함께 4개 모듈 `-u` 후 복제 DB 재검증이 필요하다.
- 실제 운영 반영은 별도 코드/DB/filestore 백업, 모듈 업그레이드, 재기동, 역할별 UAT 후 판단한다. 이번 세션에서 원본 서비스나 DB를 변경하지 않는다.
- 롤백은 배포 전 코드 및 DB 백업으로 한 쌍 복원하는 계획이다. 시험 복제 DB를 원본에 복원하지 않는다.
- 결재 원장 변조 방어는 Phase 2. IQC 다중 LOT/수량, 새 보류에 대한 과거 승인 재사용, 2단계 수동 해제, LOT별 출하 자격 및 동시성은 Phase 3 이후다. 기존 승인 엔진을 호출하는 이번 가드만으로 전체 품질 수명주기 보완을 완료했다고 보지 않는다.
- 브라우저/실제 PLC·스캐너/전체 ERP 회귀는 미실행.
