# 142 Phase 2 — 품의·결재·청구·전기 무결성

## 요청·기준

- 원도영의 2026-09-16 직접 지시: Phase 2 진행. 41은 실험 참고, 142/WSL 반례를 기준으로 한다.
- 브랜치 `20260916/report-audit/phase2`: 사용자 지정 이름이 기본 명명 규칙보다 우선한다.
- ERP 출발점: Phase 1 `4f09f6bac94852149d156889f3a5ae43d8dd9119`.
- 미러 출발점: Phase 1 `b148a8ad65ab515021e28839370e929beace5385`.
- 워크트리: `C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/worktrees/odoo-142`, 대응 미러 `odoo-gh-142`.
- 원본 체크아웃·서비스·운영 DB를 수정하지 않는다. 원격 push/PR/머지/배포/외부 회신 없음.
- handoff의 이전 확인 기준 `e6f1c0666eaedc60a89829a511ac810681e4310b`는 참고 입력이며, 이번 변경은 사용자의 직접 지시 범위다.

## 구현

두 공통 모듈을 정본에서 먼저 변경한다. 신규 `models/integrity.py`를 기존 모델 위에 확장하여 미러의 기존 수동 청구 연결·화면 변경을 보존한다.

### iatf_approval 18.0.1.2.0

- 승인 요청 생성, 상태/일시/원문서 연결 및 결재선 판정은 서버의 비공개 전이로만 기록한다. 일반/관리자 direct write와 JSON으로 위조 가능한 context flag를 허용하지 않는다.
- 문서의 결재 연결과 `default_*` 컨텍스트를 통한 승인 값 주입을 차단한다.
- 상신·초기화·결재선 변경은 원문서 쓰기 권한, 승인/반려는 원문서 읽기 권한과 현재 결재자·현재 버전을 확인한다.
- 진행 중/종료 결재선 및 과거 이력은 수정·삭제할 수 없다. 초기화는 새 draft 요청을 만들고 `previous_request_id`로 이전 요청을 보존한다. 과거 결재자·결정·시각·반려 사유를 덮어쓰지 않는다.
- 상신 시 `snapshot`에 승인 근거를 기록한다. 품의서는 거래처·회사·통화·유형·제목·상세 수량/단가/세금/단계/금액을 포함한다.
- 결재 증거는 요청자·결재선 참여자·관리자에게만 보이도록 레코드 규칙을 추가한다.
- 원문서를 정렬한 행 잠금과 쓰기 충돌 감지용 UPDATE로 잠근다. PostgreSQL repeatable-read에서 오래된 스냅샷의 동시 요청은 serialization retry 후 다시 검증해야 한다.

### pumui_approval 18.0.1.2.0

- 상세 생성/수정/삭제/부모 이동 시 원문서 권한과 잠금을 확인하고 승인 또는 진행 중인 결재를 새 버전으로 전환한다. 이동은 양쪽 문서에 적용한다.
- 계산 금액 및 청구 완료 여부의 직접 입력을 차단한다. 청구 상세 연결은 내부 생성 절차만 허용한다.
- 청구 연결의 부모·회사·거래처(상업 거래처)·문서 유형을 검증하고, 반대편 account.move/account.move.line에서 연결이 바뀌어도 재검사한다.
- `_post()` 공통 경로에서 승인 단계, 현재 내용과 승인 snapshot 일치, 누적 전기액 한도를 검사한다. 정상 `action_post()`도 이 경로를 지난다.
- 판정은 세금 포함 회사 통화 금액 및 통화 반올림 기준이다. 전기 전 환산액과 전기 후 실제 회사 통화 총액을 모두 검사한다. 표시 금액도 회사 통화 기준으로 맞춘다.
- 초안은 한도를 소비하지 않고 posted만 합산한다. 일괄 전기는 후보 합계로 검사한다. 일반 분할 청구를 허용한다.
- 환불은 같은 품의·통화의 전기된 원청구서가 있어야 하며, 원청구서별 누적 환불 한도와 전체 순청구 한도를 함께 검사한다. 정상 환불/취소는 한도를 되돌린다. 환불 취소 등으로 다시 초과하면 거부한다.
- 품의 연결을 제거하여 통제를 피할 수 없고, posted 문서의 근거·범위는 변경할 수 없다. 품의와 무관한 일반 청구서를 의무 품의 대상으로 바꾸지는 않는다.
- 반려 사유 입력은 의미 있는 본문 변경으로 취급하지 않아 정상 반려를 유지한다. 세금 마스터 변경으로 금액이 달라지면 현재 내용과 승인 근거의 차이로 전기를 거부한다.

## 검증 환경과 증거

- 새 DB `codex_142_p2_20260916_01`: 원본 `esconodoo202609`에서 2026-09-16 15:11:07~15:11:46 KST 복제.
- WSL Ubuntu 22.04, PostgreSQL 17/5433, `/opt/odoo` Odoo 18.0+e-20251117.
- HTTP/cron 비실행, `unshare -n`, PG UNIX socket. 복제본 cron/메일 비활성 및 FDW 사용자 매핑 제거. filestore 미복제.
- 정본 검증은 두 수정 모듈만 ERP symlink overlay로 로드하며 나머지는 Phase 1 미러를 사용한다. 실제 import 경로를 단언한다.
- 수정 전 9사례를 미러 Phase 1 코드에서 재현했다. 상세 승인 유지, 금액 위조, 승인 상태 직접 변경, 승인 초과 전기, 내부 `_post` 우회, 다른 부모의 청구 상세 연결을 확인했다. 부모 직접 수정의 기존 초기화는 대조 사례다.
- 새 이력 필드와 보안 규칙을 복제 DB에 적용한 후 최종 ERP 회귀 **45개 통과, 실패/오류/skip 0**. 결재·전기·연결·환불·취소·외화·반올림·세금 마스터 및 Phase 1 IQC/OQC 회귀를 포함한다.
- 세금 마스터 변경 반례는 처음 실패하여 `erp_tax_snapshot_attempt.json`에 보존했다. 세금 ID와 함께 당시 세율·계산 조건을 snapshot에 넣은 후 같은 반례가 통과했다.

```powershell
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase2_test.py erp_upgrade
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase2_load_rules.py
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase2_test.py erp
```

증거: `C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/outputs/phase2_evidence/`의 `candidate_baseline.json`, `erp_tests.json`, `erp_upgrade.log`, `clone_preparation.json`. 이전 단계의 성공 결과는 별도 이름으로 보관하며 반복 횟수를 고유 테스트 수로 합산하지 않는다.

## 미러 동기화와 운영 적용 조건

- 정본 커밋 확정 후 변경 파일만 `odoo_gh/iatf_plugins`로 포팅한다. `models/pumui.py`에서는 청구 연결 대입 한 줄만 private helper 호출로 바꾸고 미러의 나머지 변경을 보존한다.
- 미러의 `models/account_move.py`, 기존 `tests/test_pumui.py`, view/menu는 덮어쓰지 않는다. 새 integrity 확장의 금액 표시 계산은 양쪽에 동일하게 적용한다.
- 최종 통합 결과 및 정본 SHA는 미러의 같은 작업 문서에 기록한다. 공식 ERP 병합 이전의 로컬 통합 후보다.
- 운영 반영에는 `iatf_approval,pumui_approval` 업그레이드가 필요하다. Phase 1도 미배포라면 Phase 1의 4개 모듈과 함께 적용한다. 승인 엔진 의존 모듈도 Odoo가 후속 갱신할 수 있다.
- 과거 품의 승인에 snapshot이 없으면 새 청구·전기 전에 이력을 보존한 채 재상신해야 한다. 기존 데이터를 현재 값으로 자동 승인 처리하지 않는다. 과거 초과/위조 연결을 소급 수정하지 않는다.
- 배포 전 원본 코드·DB·filestore 백업과 역할별 UAT가 필요하다. 롤백은 배포 전 코드와 DB를 함께 복원하는 계획이며 테스트 DB를 원본에 복원하지 않는다.
- 브라우저 전 과정, 모든 IATF 앱의 전수 회귀 및 실제 운영 배포는 이번 검증에 포함하지 않는다. 기존 승인/연결의 운영 데이터 정리는 별도 검토 대상이다.

## Phase 2 후속 — 업무 역할에 따른 결재선 관리 (2026-09-16)

사용자 요청: 품의 결재선에 적절한 권한을 부여하여 정상 처리되도록 보완. 기존 Phase 2 브랜치를 계속 사용한다. 기준 커밋은 `e9c255dcb7563ec89f9f2ad64af28c26d00d0c08`이다.

### 권한 기준과 변경

- 기존 기안자·지정 결재자의 참여 권한에 더해, `품의서 관리자`는 원문서 읽기/쓰기 권한과 활성 회사 범위 안에서 품의 결재를 관리한다. 다른 품의 작성자에게 전체 품의 결재 증거를 공개하지 않는다.
- `공정검사 담당자` 및 이를 포함하는 관리자는 같은 기준으로 공정/최종/OQC 결재를 관리한다. 출하 담당자의 자동 생성과 품질 담당자의 후속 처리를 연결한다.
- 초안 결재선 추가·수정·삭제를 허용한다. 결재선의 내부 사용자 삭제 ACL을 열되, 서버에서 현재 원문서의 수정 권한·회사·초안 상태를 먼저 검사한다. 진행/완료/이전 버전의 결재선 직접 변경은 금지한다.
- 승인/반려는 여전히 현재 지정 결재자만 가능하다. 관리 역할 자체가 대리 승인 권한을 주지 않는다. 변경 시 새 결재 버전과 이전 증거를 보존한다.
- 각 업무 모듈이 관리 역할을 등록하며, 공통 엔진이 원문서의 읽기/쓰기 record rule을 SQL 하위 조회에 적용한다. Odoo가 규칙 검색식을 sudo로 확장하는 구간에서는 실제 uid의 일반 권한으로 되돌려 검사한다. 그룹 변경 시 별도 사용자 목록 동기화가 필요 없다.
- context 기본값의 `request_id`로 진행 중 결재에 새 줄을 끼워 넣는 경로도 검사한다.
- 변경 모듈: `iatf_approval`/`pumui_approval` 18.0.1.2.1, `iatf_process_inspection` 18.0.1.0.4.
- 실제 사용자 그룹을 변경하지 않았다. 배포 시 담당자에게 기존 `품의서 관리자` 또는 `공정검사 담당자` 역할을 지정하고, 승인자에게 원문서 조회 권한과 결재선 지정을 갖추어야 한다. 기안과 승인의 인적 분리 정책은 새로 강제하지 않는다.

### 검증

격리 복제 DB `codex_142_p2_20260916_01`, HTTP/cron 비실행, 네트워크 격리, 시험 fixture 롤백. 정본 세 모듈의 실제 import 경로를 확인했다.

- 정본 업그레이드 완료. 정본 회귀 **53개 통과, 실패/오류/skip 0**.
- 새 시험 8개: 관리자 초안 편집/상신, 현재 결재자만 승인·반려, 작성자 초안 줄 교체, 비참여 작성자 거부, 진행/완료 결재 및 context 우회 거부, 새 버전과 과거 이력 보존, 다른 회사와 권한 회수, 원문서 개별 규칙 제한, 역할을 나눈 OQC 자동 생성→판정→승인→출하 완료. 한 시험 안에서 여러 조건을 확인하므로 나열 항목 수와 시험 수는 다르다.
- 초기 53개 시험 중 원문서 개별 접근 규칙 검사 1개가 실패했다. Odoo의 규칙 확장 시 sudo 문맥이 전달되는 원인을 보완한 뒤 53개 모두 통과했다. 초기 실패도 `erp_rule_scope_attempt.json`에 보존했다.
- 증거: 작업공간 `outputs/phase2_permissions_evidence/erp_tests.json`, `erp_upgrade.log`, `erp.log`; 실행기 `work/phase2_permissions_test.py`.

```powershell
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase2_permissions_test.py erp_upgrade
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase2_permissions_test.py erp
```

### 반영 조건과 잔여 범위

- 수정한 파일만 정본에서 미러로 포팅한다. 기존 미러의 품의/회계 차이는 유지한다. 배포 전 위 세 모듈을 업그레이드해야 권한 규칙과 ACL이 갱신된다.
- 이전 결재 버전이 대시보드 대기에 남는 문제는 이번 권한 보완과 별도이며 아직 남아 있다. 전체 IATF 역할 확장, 브라우저 UAT, 실제 운영/실물 장비 검증도 완료로 간주하지 않는다.
- handoff의 20260916-01 재기준화 공지는 참조했다. 다른 UAT/미러 후보를 이 브랜치에 합치거나 운영에 배포하지 않았다. 작업 원칙은 사용자가 지정한 정본 작업→미러 동기화다.
- WSL 원본·실제 운영 DB/사용자 권한·서비스는 변경하지 않았다. 원격 push/PR/merge/배포 없음. 기존 백업·모듈 업그레이드·롤백 조건은 유지한다.
