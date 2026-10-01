# 142 Phase 1 준비 기록 — ERP 정본

## 접수와 범위

- 요청: 원도영의 2026-09-16 직접 지시. 142 개선의 Phase 0 준비만 수행.
- 공통 ERP 앱은 odoo에서 수정한 후 odoo_gh에 정본 동기화한다. 통합 검증 대상은 odoo_gh다.
- 현재 상태: Phase 0 완료, Phase 1 제품 코드 수정 미착수.
- 41번은 실험 참고자료, 142번은 개선 판단의 주 대상.
- 담당: 현재 Codex 작업. 별도 AI 배정·handoff 발송·원격 push·PR은 수행하지 않음.
- Phase 1 예정 범위: LOT 직접 해제, 보류 LOT MES 스캔, OQC hold 출하, 중량 상하한 판정.

## 기준과 동기화 원칙

- ERP 기준: origin/18.0 = 17e9fac0eeeb7564e72e826caaf1865ba3b466a1.
- 통합 기준: origin/main = 8326349e9f086c21f004dfe2df11276531130bd8.
- 양쪽 브랜치명: fix/142-phase1-runtime-gates. Phase 0 작업 기록과 향후 코드를 같은 브랜치에 관리.
- ERP 워크트리: C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/worktrees/odoo-142.
- 통합 워크트리: C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/worktrees/odoo-gh-142.
- iatf_incoming_inspection, iatf_process_inspection 등 공통 앱: odoo/addons_custom 수정 → 해당 ERP 변경을 odoo_gh/iatf_plugins로 포팅.
- injection_worksite, gh_total_mes 등 미러에만 있는 자체 앱: odoo_gh/odoo_plugins에서 수정.
- 공식 정본 동기화는 ERP PR/병합 SHA와 연결한다. 그 전 로컬 시험 포팅은 통합 후보임을 기록하며 공식 반영으로 표시하지 않는다.
- iatf_process_inspection은 manifest, models/mrp_production.py, models/process_inspection.py가 다르다. 미러에 있는 회사 지정/SPC 중복 방지·부분군 누적 보완을 보존한다. OQC 출하 가드 파일 stock_picking.py는 현재 동일하다.
- pumui_approval 6파일, injection_planning 4파일에도 차이가 있다. 전체 폴더 덮어쓰기 금지.
- 다른 기본 체크아웃의 미커밋 파일·로컬 커밋·워크트리는 보존한다.

## Phase 0 변경과 영향

제품 Python/XML/권한/manifest 파일을 수정하지 않았다. 새 워크트리 등록, 검증 도구 및 증거 작성, 새 복제 DB 생성만 수행했다. 이번 문서 자체에는 모듈 업그레이드나 배포가 필요 없다.

복제 DB: codex_142_p0_20260916_01. 원본: esconodoo202609.
복제 시각: 2026-09-16 14:42:33~14:43:04 KST.
cron 6개, 발신 메일 서버 1개 비활성화. 복제본의 FDW 사용자 매핑 2개 제거.
시험은 unshare -n, PostgreSQL UNIX socket, HTTP/cron 비실행. filestore 미복제로 첨부·브라우저 검증 제외.
복제본을 원본에 덮어쓰는 절차는 없다.

## 검증

- WSL Ubuntu 22.04, Odoo 18.0+e-20251117, Enterprise quality_control/web_enterprise 설치.
- 실행 코어: /opt/odoo. 새 ERP worktree의 Community 코어로 실행하지 않는다.
- 통합 시험 addons_path: /opt/odoo/addons + 통합 워크트리/odoo_plugins + 통합 워크트리/iatf_plugins.
- WSL 대조: /opt/odoo/addons + /opt/plugins/odoo_plugins + /opt/plugins/iatf_plugins.
- 실제 import된 4개 대상 모듈 경로를 검사한 후 fixture 실행. 동일 기술명 중복 0.
- 수정 전 8사례를 각 코드 구성으로 실행. 정상 중량 대조 1개, 결함 증거 7개(4개 문제 영역). 모든 시험 status=executed, harness_error=0.
- 보류 직접 해제 허용, 해제 후 실제 소비 완료, 보류 LOT 스캔 성공, OQC hold 출하 완료, 범위 밖/역전/미측정 중량 pass를 재현.
- 이는 수정 전 기준 시험이며 제품 회귀 테스트 통과나 결함 해결을 뜻하지 않는다.
- 각 사례 savepoint rollback + 전체 transaction rollback.
- 원본 시험용 사용자/품목/LOT 0건 유지, active cron 6개 유지. 서비스 PID 8804 및 시작 시각 14:21:42 KST 유지.
- 비교한 9개 대상 모듈의 Python/XML/CSV/JS/SCSS는 줄바꿈 정규화 후 WSL=통합 워크트리. 전체 배포 파일 동일성 보증은 아님.
- 최초 candidate 실행은 설정 초기화 시점 때문에 WSL 소스를 읽어 채택하지 않았다. 검증 도구를 고쳐 실제 import 경로를 단언한 재실행 결과만 candidate_baseline.json에 기록했다.

재현 명령(Windows PowerShell):

```powershell
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase0_baseline.py candidate
wsl.exe -d Ubuntu-22.04 -u root -- unshare -n -- runuser -u postgres -- /opt/odoo/venv/bin/python /mnt/c/Users/user/Documents/Codex/2026-09-15/new-chat-2/work/phase0_baseline.py wsl
```

증거 경로: C:/Users/user/Documents/Codex/2026-09-15/new-chat-2/outputs/phase0_evidence/
- clone_preparation.json: DB 복제·중립화.
- candidate_baseline.json / wsl_baseline.json: 각 구성의 실행 결과와 실제 로드 경로.
- candidate.log / wsl.log: Odoo 로그.
- source_comparison.json: 파일 해시·정본 차이·원본 최종 확인.
- rejected_initial_candidate_path.json: 채택하지 않은 첫 시도의 경로 확인 기록.
- scripts/: 이번 검증 도구 및 재사용 fixture 사본.

## 배포와 후속 작업

- 제품 코드 수정·정본 포팅·PR·병합·배포 모두 미실행. Phase 1 시작 지시 후 진행.
- Phase 1에서 수정한 모듈에 필요한 업그레이드와 회귀 테스트를 복제 DB에서 수행하고, 정상 IQC 해제·정상 출하·일반 사용자 권한을 함께 검증한다.
- 541c5891 정산 보완이 통합 기준에 이미 포함되어 있다. Phase 6은 새 기준에서 재판정하며 과거 결함을 그대로 다시 수정하지 않는다.
- handoff e6f1c0666eaedc60a89829a511ac810681e4310b의 UAT/미러 분기 공지는 참고 입력이다. 사용자의 최신 지시인 odoo → odoo_gh 구조를 유지한다.
- 업무 인수시험·외부 PLC/스캐너·동시성·전체 회귀는 Phase 0에서 미실행.
