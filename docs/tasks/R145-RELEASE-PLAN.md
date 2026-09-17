# R145 운영 릴리스 절차서(초안 v1) — odoo-uat main → escon-odoo/odoo_gh → 운영 odoo18

- 작성: Claude 개발, 2026-09-17. 기준: odoo-uat main **321530e**(후보 bc8be21, UAT 배포 f588dec3), 운영 미러 **0b36e7f**, 운영 설치 목록(서버 담당 2026-09-17 회신).
- 실행 주체: 서버 담당(원도영). 개발은 SSH 없음. 이 문서는 **초안**이며 아래 전제가 닫히면 v2 로 확정한다.

## 0. 전제(미충족 시 진행 금지)
1. 사용자 결정 A(톤 정산 원천)·B(마감 후 조정 승인 유무)·Q2(이월 종료). 결정에 따라 후보가 바뀌면 3라운드 후 이 문서 갱신.
2. 운영 사출품 BOM 18건(현재 전부 odoo_standard) 데이터 정리 완료 여부. 미완이면 사출 계획은 BOM 을 못 찾는다(운영 코드 규칙; 이번 릴리스로 새로 생기는 문제 아님, 이미 운영 상태).
3. 복제본 리허설 통과: 서버 담당이 복제본 서버에서 아래 3~4절을 그대로 실행 → 오류 0, 5절 확인 통과 → DB 덤프(파일스토어 포함)·중립화 사본 전달(8번 합의).
4. 미러 main 에 0b36e7f 이후 새 커밋이 없을 것(있으면 3라운드 병합 먼저).

## 1. 범위
- **-u(업그레이드) 20모듈**(odoo-uat 버전 > 운영 버전): account_kr_plus_patch 2.5.7, account_kr_reports 1.7.0, cams_ops_dashboard 3.0.0, escon_br 1.8, escon_serial 4.1, gh_total_mes 1.30, gh_vendor_settlement 4.2.0, iatf_approval 1.2.1, iatf_document_control 1.0.1, iatf_incoming_inspection 2.1.2, iatf_mold 1.2.7, iatf_nonconformity 1.0.1, iatf_process_inspection 1.0.13, iatf_spc 1.0.10, iatf_traceability 1.1.1, iatf_work_environment 1.3.7, injection_costing 2.0.3, injection_planning 1.24.0, injection_worksite 8.9.0, supplier_portal_purchase 1.4.0.
- **-i(신규 설치) 3모듈**: escon_br_intake(→ 의존 mrp_bom_scan_guard 자동 설치; 미러엔 있으나 운영 미설치), cams_quality_rework, cams_sq_dashboard. ※ cams_quality_rework 는 `iatf_quality_precedence` 의존 — **odoo-uat 에 없음** → 설치 불가. 미이식 격리 모듈 파동 결정 전까지 **-i 목록에서 제외**(escon_br_intake, cams_sq_dashboard 만).
- 나머지 69모듈: 버전 동일(변경 없음). escon_mo_barcode 는 매니페스트 표기 '0.9' = 운영 18.0.0.9(Odoo 정규화 동일) → 변경 없음.
- **제외(미러에 넣지 않음)**: uat_safety, uat_bom_purpose_seed, escon_web_trace(설치 금지 정책), test_factory_bridge, test_scm_iqc_bridge, 각 모듈 `.claude/`·`.vscode/`, 미러 `iatf_plugins/` 최상위 잡파일(CLAUDE.MD, DECIMAL_PATCHES_*.md, README.md, __manifest__.py, static/, views/, .vscode/ — 7번 합의로 제거).
- 새 의존: injection_worksite→escon_employee(운영 설치됨 ✓), injection_planning→escon_bom_util(✓), escon_br_intake→mrp_bom_scan_guard(자동).

## 2. 미러 동기화(odoo-uat → odoo_gh) — 개발이 브랜치 준비, 서버 담당이 머지
- 배치 규칙: 기존 모듈은 **현재 폴더 유지**(odoo_plugins/iatf_plugins 매핑표 = 미러 현재 배치), 신규(escon_br_intake, cams_sq_dashboard, mrp_bom_scan_guard 는 이미 iatf_plugins)는 **iatf_plugins**(wilcoco 계열).
- 개발이 `odoo_gh` 에 `release/r145-<odoo-uat sha>` 브랜치를 만들어 PR: 내용 = odoo-uat addons/ 를 매핑표대로 두 폴더에 복사(제외 목록 반영, 잡파일 삭제). 검증: 각 모듈 트리 해시 = odoo-uat 것과 동일(스크립트 첨부 예정), `tools/uat_transplant_check.py` 닫힘 OK.
- 서버 담당이 PR 검토·머지(9번 합의). **머지 전 미러 main 에 다른 커밋이 없어야** 한다(있으면 개발이 3라운드).

## 3. 운영 서버 실행 절차(서버 담당) — 반드시 복제본에서 먼저
```
cd /db/odoo-root
# 3.1 백업
docker exec postgresdb pg_dump -U odoo -Fc odoo18 > /db/backup/odoo18_pre_r145_$(date +%Y%m%d_%H%M).dump
tar czf /db/backup/filestore_pre_r145_$(date +%Y%m%d_%H%M).tgz <filestore 경로>
# 3.2 코드
cd /db/odoo-root/odoo/git/odoo_gh && git fetch && git checkout main && git pull --ff-only && git rev-parse HEAD   # = 릴리스 커밋
# 3.3 업그레이드만 먼저(스키마 변경 모듈 포함) — 설치와 같은 실행에 섞지 않는다(UAT 사고 5)
docker compose stop odoo_green
docker compose run --rm odoo_green odoo -c /etc/odoo/odoo.conf -d odoo18 --stop-after-init \
  -u account_kr_plus_patch,account_kr_reports,cams_ops_dashboard,escon_br,escon_serial,gh_total_mes,gh_vendor_settlement,iatf_approval,iatf_document_control,iatf_incoming_inspection,iatf_mold,iatf_nonconformity,iatf_process_inspection,iatf_spc,iatf_traceability,iatf_work_environment,injection_costing,injection_planning,injection_worksite,supplier_portal_purchase
# 3.4 신규 설치(별도 실행)
docker compose run --rm odoo_green odoo -c /etc/odoo/odoo.conf -d odoo18 --stop-after-init -i escon_br_intake,cams_sq_dashboard
# 3.5 재기동
docker compose up -d odoo_green
```
- 각 단계 로그에서 `CRITICAL`·`Traceback` 0 확인. migration 실행 로그(예: gh_vendor_settlement 18.0.4.x, injection_worksite 8.9.0 은 migration 없음, escon_bom_util 은 변경 없음) 보관.

## 4. 롤백
- 3.3/3.4 에서 오류: 컨테이너 기동하지 말고 `pg_restore -U odoo -d odoo18 --clean --if-exists <dump>` + 파일스토어 복원 + `git checkout <이전 커밋 0b36e7f>` + 재기동. 부분 업그레이드 상태로 두지 않는다.
- 재기동 후 기능 문제: 같은 절차. 운영 데이터가 그 사이 쌓였으면 복원 대신 핫픽스(개발→odoo-uat→미러) 를 원칙으로 하되 판단은 서버 담당.

## 5. 확인(재기동 후, 읽기 전용)
```
docker exec postgresdb psql -U odoo -d odoo18 -Atc "select name,state,latest_version from ir_module_module where name in ('injection_worksite','injection_planning','gh_vendor_settlement','escon_br_intake','mrp_bom_scan_guard','cams_sq_dashboard','escon_web_trace') order by 1"
```
- 기대: injection_worksite 18.0.8.9.0, injection_planning 18.0.1.24.0, gh_vendor_settlement 18.0.4.2.0, escon_br_intake·mrp_bom_scan_guard·cams_sq_dashboard installed, escon_web_trace uninstalled/없음.
- 화면: 사출 계획 열림(BOM 정리 전이면 MO 생성은 BOM 없음 경고가 정상), BR 생산지시표 조회, 작업자 목록(escon_employee), 정산 원장 목록.

## 6. 미결(이 문서 v2 에서 닫을 것)
- 결정 A/B/Q2 반영본, 미이식 격리 모듈 12+21 파동 여부(cams_quality_rework 포함), 복제본 리허설 결과, 릴리스 브랜치 SHA·검증 스크립트.
