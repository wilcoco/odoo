# R145 운영 릴리스 절차서 v2 (서버 담당 실측 초안 채택 + 개발 갱신 2026-09-17)

> odoo-uat `main` → `escon-odoo/odoo_gh` PR → 운영 `odoo18`

- 작성 기준: 2026-09-17
- UAT 기준: `odoo-uat main` **0b6f56b** (321530e + 버전 누락 정정 2건)
- 검증 후보: **bc8be21** → rc ed91279(버전 정정)
- UAT 배포: **f588dec3**, SUCCESS, health 200, CRITICAL 0
- 운영 미러 현재 기준: `escon-odoo/odoo_gh main` **0b36e7f**
- 운영환경 실측: `escon-server`, 2026-09-17
- 실행 주체: 서버 담당
- 상태: **v2 — 릴리스 PR 생성됨(escon-odoo/odoo_gh #9, 브랜치 `release/r145-0b6f56b`, 커밋 27ae9bb259bf41083c39cb169ca01ee86cb3c852). 머지·복제본 리허설·승인 완료 전 운영 실행 금지**
- 원칙: 미러 `main` 직접 커밋 금지. 작업 브랜치 → PR → 머지 후 운영서버는 fast-forward만 수행한다.

## 0. 확정된 사용자 결정

### A. 톤 정산 원천

**(a) 정본 유지**

- 사일로 투입 로그를 정산 원천으로 사용한다.
- 발주 기준 수지는 PO 청구 정책을 유지한다.
- 운영에서 별도로 개발했던 입고 이동/반품 차감 기준 재설계는 채택하지 않는다.
- 원재료 반품은 정상 업무 흐름으로 보지 않는다.
- 사일로 30톤, 잔량 9톤 이하 발주, 20톤 납품 및 열린 발주 중복 방지 정책을 유지한다.

### B. 마감 후 정산 조정

**(b) 승인 뒤 반영**

- 승인 없는 자동 전기는 하지 않는다.
- 원생산일과 원본 원장은 보존한다.
- 조정은 열린 기간 날짜로 기록하고 원본과 연결한다.
- 청구·회계 반영은 승인 이후에 수행한다.

### Q2. 이월 종료 시점

**(b) 청구서 회계 전기 시**

- R134 정본 게이트를 유지한다.
- 위 결정으로 후보 `bc8be21` 및 UAT `321530e`의 코드 변경은 없다.
- A/B/Q2 결정으로 인한 3라운드 재이식은 필요하지 않다.

## 1. 운영 반영 전 필수 게이트

아래 항목이 하나라도 미완료면 운영 배포하지 않는다.

1. 운영 사출품 BOM 18건의 목적 값 정리 완료 — 서버 담당 2026-09-17 '정리 완료' 보고. **확인 쿼리 결과 회신 필요**: `select bom_purpose,is_escon_managed,active,count(*) from mrp_bom b join product_template t on t.id=b.product_tmpl_id where t.is_injection_part group by 1,2,3` (기대: injection/true/true 가 사출품 전부)
2. `release/r145-0b6f56b` 브랜치와 PR 생성 — **완료** (PR #9)
3. PR 검토 및 `escon-odoo/odoo_gh main` 머지 완료
4. 승인된 **40자리 릴리스 커밋 SHA** 확정
5. 모듈별 원본→미러 매핑표 및 트리 해시 검증 완료 — **완료**(91모듈 동일, .vscode 제거 5모듈은 그 파일만 차이; PR 본문·release_mapping.json)
6. `tools/uat_transplant_check.py` 또는 동등 검증 도구 통과
7. 운영 복제본에서 본 문서의 백업·업그레이드·설치·검증·복원 절차 전체 리허설 통과
8. 운영 유지보수 시간 및 명시적 운영 승인 확보
9. 새 Python 패키지 의존성 또는 이미지 재빌드 필요 여부 확인 — **완료: 신규 의존 없음, 재빌드 불필요**(비표준 import openpyxl/xlrd/oracledb/attr 등은 운영 코드에 기존재, freezegun 은 시험 전용)

## 2. 확인된 운영 환경

| 항목 | 실제 운영 값 |
|---|---|
| 호스트 | `escon-server` |
| Compose 파일 | `/db/odoo-root/docker-compose.yml` |
| 실행 Odoo 서비스/컨테이너 | `odoo_green` |
| 대기 Odoo 컨테이너 | `odoo_blue` — 현재 종료 상태 |
| PostgreSQL 컨테이너 | `postgresdb` |
| 공통 Docker 네트워크 | `projectroot_backend` |
| Odoo 이미지 | `odoo-root-odoo_green` |
| Odoo entrypoint/command | `/entrypoint.sh`, `odoo` |
| Odoo 실행 사용자 | `odoo` |
| DB | `odoo18` |
| DB 사용자/호스트/포트 | `odoo` / `postgresdb` / `5432` |
| 배포 저장소 | `/db/odoo-root/odoo/git/odoo_gh` |
| 현재 운영 커밋 | `0b36e7f` |
| Odoo data_dir | `/var/lib/odoo` |
| 호스트 data_dir | `/db/odoo-root/odoo/green/data` |
| 파일스토어 | `/db/odoo-root/odoo/green/data/filestore/odoo18` |
| 파일스토어 크기 | 약 702MB |
| 백업 디렉터리 | `/db/backup` |
| 백업 디스크 여유 | 약 1.3TB |
| addons_path | `/mnt/extra-addons,/mnt/enterprise-addons,/usr/lib/python3/dist-packages/odoo/addons,/mnt/iatf` |
| `odoo_plugins` mount | `/mnt/extra-addons` |
| `iatf_plugins` mount | `/mnt/iatf` |

## 3. 릴리스 범위

### 3.1 업그레이드 22개

- `account_kr_plus_patch` → 18.0.2.5.7
- `account_kr_reports` → 18.0.1.7.0
- `cams_ops_dashboard` → 18.0.3.0.0
- `escon_br` → 18.0.1.8
- `escon_serial` → 18.0.4.1
- `gh_total_mes` → 18.0.1.30
- `gh_vendor_settlement` → 18.0.4.2.0
- `iatf_approval` → 18.0.1.2.1
- `iatf_document_control` → 18.0.1.0.1
- `iatf_incoming_inspection` → 18.0.2.1.2
- `iatf_mold` → 18.0.1.2.7
- `iatf_nonconformity` → 18.0.1.0.1
- `iatf_process_inspection` → 18.0.1.0.13
- `iatf_spc` → 18.0.1.0.10
- `iatf_traceability` → 18.0.1.1.1
- `iatf_work_environment` → 18.0.1.3.7
- `injection_costing` → 18.0.2.0.3
- `injection_planning` → 18.0.1.24.0
- `injection_worksite` → 18.0.8.9.0
- `supplier_portal_purchase` → 18.0.1.4.0
- `gh_provisional_pricing` → 18.0.2.2.0 (버전 누락 정정: 저장 필드 retro_price_id 추가분)
- `production_planning` → 18.0.1.1.0 (버전 누락 정정: R144 정책 ① 수요 잠금)

### 3.2 신규 설치 2개

- `escon_br_intake`
- `cams_sq_dashboard`

의존성:

- `escon_br_intake` 설치 시 기존 미러에 있으나 운영 DB에서 미설치 상태인 `mrp_bom_scan_guard`가 의존성으로 설치되어야 한다.

### 3.3 보류

- `cams_quality_rework`
  - `iatf_quality_precedence` 의존
  - 현재 운영 DB 모듈 목록과 UAT 이식 범위에 없음
  - 격리 모듈 이식 파동이 확정되기 전에는 설치하지 않는다.

### 3.4 제외

- `uat_safety`
- `uat_bom_purpose_seed`
- `escon_web_trace`
- `test_factory_bridge`
- `test_scm_iqc_bridge`
- 각 모듈의 `.claude/`, `.vscode/`
- 미러 최상위 잡파일 및 비모듈 항목

`escon_web_trace`는 운영 DB에서 현재 `uninstalled`이며 그대로 유지한다.

## 4. 미러 배치 원칙

- 기존 모듈은 현재 `odoo_plugins`/`iatf_plugins` 배치를 유지한다.
- 신규 모듈 `escon_br_intake`, `cams_sq_dashboard`는 최신 결정에 따라 `odoo_plugins`에 배치한다.
- 기존 `mrp_bom_scan_guard`는 현재 위치인 `iatf_plugins`를 유지한다.
- 동일한 기술 모듈을 두 addons 디렉터리에 중복 배치하지 않는다.
- `odoo-uat addons/` 원본과 미러 대상 모듈의 트리 해시를 비교한다.
- 개발자는 `release/r145-321530e` 형태의 작업 브랜치를 만들고 PR을 연다.
- 서버 담당은 PR을 검토·머지하며 `main`에 직접 커밋하지 않는다.
- PR 머지 후 정확한 40자리 SHA를 이 문서에 기록한다.

## 5. 배포 당일 사전 점검

아래 `<RELEASE_SHA>`는 확정된 40자리 SHA로 교체한다. 교체 전 실행 금지.

```bash
set -euo pipefail

compose_file=/db/odoo-root/docker-compose.yml
repo_dir=/db/odoo-root/odoo/git/odoo_gh
filestore_root=/db/odoo-root/odoo/green/data/filestore
backup_dir=/db/backup
previous_sha=0b36e7f103149d23251ac3e6bedf2dedc0c2874c
release_sha=<RELEASE_SHA>

test -f "$compose_file"
test -d "$repo_dir/.git"
test -d "$filestore_root/odoo18"
test -d "$backup_dir"
test "${#release_sha}" -eq 40
test -z "$(git -C "$repo_dir" status --porcelain)"
test "$(git -C "$repo_dir" rev-parse HEAD)" = "$previous_sha"

git -C "$repo_dir" fetch origin main
test "$(git -C "$repo_dir" rev-parse origin/main)" = "$release_sha"

docker compose -f "$compose_file" ps
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
df -h "$backup_dir"
```

`origin/main`이 승인된 SHA와 다르면 배포를 중단한다. 승인되지 않은 후속 커밋을 함께 배포하지 않는다.

## 6. 운영 실행

### 6.1 운영 중지

현재 운영 Odoo writer와 cron은 `odoo_green` 하나다. 중지 순간부터 운영 중단이다.

```bash
r145_ts=$(date +%Y%m%d_%H%M%S)
r145_started_at=$(date --iso-8601=seconds)
umask 077

docker compose -f "$compose_file" stop odoo_green
```

### 6.2 DB 및 파일스토어 백업

DB 덤프에는 DB 생성 정보를 포함해 복원 시 원래 DB 속성을 재현할 수 있게 한다.

```bash
db_dump="$backup_dir/odoo18_pre_r145_${r145_ts}.dump"
filestore_dump="$backup_dir/filestore_pre_r145_${r145_ts}.tgz"

docker exec postgresdb \
  pg_dump -U odoo -Fc --create odoo18 \
  > "$db_dump"

tar -C "$filestore_root" \
  -czf "$filestore_dump" \
  odoo18

test -s "$db_dump"
test -s "$filestore_dump"

docker exec -i postgresdb \
  pg_restore --list - \
  < "$db_dump" \
  > /dev/null

tar -tzf "$filestore_dump" > /dev/null
```

백업 또는 무결성 확인이 실패하면 이후 단계로 진행하지 않는다. 코드와 DB를 변경하지 않은 상태라면 기존 `odoo_green`을 다시 기동하고 원인을 확인한다.

### 6.3 승인된 코드로 fast-forward

```bash
git -C "$repo_dir" switch main
git -C "$repo_dir" merge --ff-only "$release_sha"

test "$(git -C "$repo_dir" rev-parse HEAD)" = "$release_sha"
test -z "$(git -C "$repo_dir" status --porcelain)"
```

이 절차는 승인된 PR 커밋으로 로컬 `main`을 fast-forward할 뿐, 운영서버에서 새 커밋을 만들지 않는다.

### 6.4 기존 모듈 22개 업그레이드

설치와 업그레이드를 같은 Odoo 실행에 섞지 않는다.

```bash
upgrade_log="$backup_dir/r145_upgrade_${r145_ts}.log"

docker compose -f "$compose_file" run \
  --rm -T --no-deps \
  odoo_green \
  odoo \
  -c /etc/odoo/odoo.conf \
  -d odoo18 \
  --workers=0 \
  --max-cron-threads=0 \
  --no-http \
  --stop-after-init \
  -u account_kr_plus_patch,account_kr_reports,cams_ops_dashboard,escon_br,escon_serial,gh_total_mes,gh_vendor_settlement,iatf_approval,iatf_document_control,iatf_incoming_inspection,iatf_mold,iatf_nonconformity,iatf_process_inspection,iatf_spc,iatf_traceability,iatf_work_environment,injection_costing,injection_planning,injection_worksite,supplier_portal_purchase,gh_provisional_pricing,production_planning \
  2>&1 | tee "$upgrade_log"
```

`set -o pipefail`이 적용된 상태에서 명령 종료 코드가 0인지 확인한다. `CRITICAL`, `Traceback`, migration 오류가 하나라도 있으면 신규 설치로 넘어가지 않는다.

### 6.5 신규 모듈 2개 설치

```bash
install_log="$backup_dir/r145_install_${r145_ts}.log"

docker compose -f "$compose_file" run \
  --rm -T --no-deps \
  odoo_green \
  odoo \
  -c /etc/odoo/odoo.conf \
  -d odoo18 \
  --workers=0 \
  --max-cron-threads=0 \
  --no-http \
  --stop-after-init \
  -i escon_br_intake,cams_sq_dashboard \
  2>&1 | tee "$install_log"
```

기대 결과:

- `escon_br_intake`: installed
- `cams_sq_dashboard`: installed
- `mrp_bom_scan_guard`: 의존성으로 installed
- `cams_quality_rework`: 설치하지 않음
- `iatf_quality_precedence`: 설치하지 않음
- `escon_web_trace`: uninstalled 유지

### 6.6 운영 재기동

```bash
docker compose -f "$compose_file" up -d odoo_green

docker ps --filter 'name=^/odoo_green$' \
  --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'

docker logs --since "$r145_started_at" odoo_green \
  2>&1 | tee "$backup_dir/r145_runtime_${r145_ts}.log"
```

## 7. 배포 후 확인

### 7.1 전체 대상 모듈 상태

```bash
docker exec postgresdb psql \
  -U odoo \
  -d odoo18 \
  -P pager=off \
  -c "
SELECT name, state, latest_version
FROM ir_module_module
WHERE name IN (
    'account_kr_plus_patch',
    'account_kr_reports',
    'cams_ops_dashboard',
    'escon_br',
    'escon_serial',
    'gh_total_mes',
    'gh_vendor_settlement',
    'iatf_approval',
    'iatf_document_control',
    'iatf_incoming_inspection',
    'iatf_mold',
    'iatf_nonconformity',
    'iatf_process_inspection',
    'iatf_spc',
    'iatf_traceability',
    'iatf_work_environment',
    'injection_costing',
    'injection_planning',
    'injection_worksite',
    'supplier_portal_purchase',
    'gh_provisional_pricing',
    'production_planning',
    'escon_br_intake',
    'cams_sq_dashboard',
    'mrp_bom_scan_guard',
    'cams_quality_rework',
    'iatf_quality_precedence',
    'escon_web_trace'
)
ORDER BY name;"
```

다음을 확인한다.

- 업그레이드 22개가 모두 `installed`이며 승인된 릴리스 매니페스트 버전과 일치
- 신규 2개 및 `mrp_bom_scan_guard`가 `installed`
- `cams_quality_rework`, `iatf_quality_precedence`가 미설치 또는 목록에 없음
- `escon_web_trace`가 `uninstalled` 또는 목록에 없음

### 7.2 로그

다음 문자열이 없는지 확인한다.

- `CRITICAL`
- `Traceback`
- `ERROR` 중 모듈 로드·migration·registry 관련 오류
- `Failed to load registry`
- `ParseError`
- `ModuleNotFoundError`

### 7.3 화면 확인

- 운영 로그인 및 기본 메뉴 진입
- 사출 계획 화면 열림
- BOM 18건 정리 완료 후 대상 BOM 선택 및 MO 생성
- BR 생산지시표 조회
- 작업자 목록 및 `escon_employee` 연동
- 정산 원장 조회
- `escon_br_intake` 화면과 권한
- `cams_sq_dashboard` 화면
- 기존 회계·생산·품질 핵심 화면 회귀 확인

## 8. 롤백

아래 절차는 반드시 운영 복제본에서 사전 리허설하고 로그를 남긴 뒤 운영 절차로 확정한다.

### 8.1 롤백 조건

- 20개 업그레이드 또는 신규 설치가 비정상 종료
- registry 로드 실패
- migration 오류
- 핵심 화면 또는 업무 흐름 중단
- 배포 직후 데이터 정합성 문제
- 승인된 SHA와 실제 배포 코드 불일치

### 8.2 DB 변경 후, 운영 재개 전 실패

```bash
docker compose -f "$compose_file" stop odoo_green

docker exec postgresdb psql \
  -U odoo \
  -d postgres \
  -v ON_ERROR_STOP=1 \
  -c "
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE datname = 'odoo18'
  AND pid <> pg_backend_pid();"

docker exec -i postgresdb \
  pg_restore \
  -U odoo \
  --clean \
  --if-exists \
  --create \
  --exit-on-error \
  -d postgres \
  - \
  < "$db_dump"

failed_filestore="$filestore_root/odoo18_failed_${r145_ts}"

mv "$filestore_root/odoo18" "$failed_filestore"

tar --numeric-owner \
  -C "$filestore_root" \
  -xzf "$filestore_dump"

git -C "$repo_dir" switch --detach "$previous_sha"

docker compose -f "$compose_file" up -d odoo_green
```

롤백 후 다음을 확인한다.

- `odoo_green` 실행
- DB `odoo18` 연결
- 이전 20개 모듈 버전 복원
- 로그인 및 주요 화면 정상
- 파일스토어 첨부파일 조회
- 런타임 로그에 registry 오류 없음

장애 당시 파일스토어는 `odoo18_failed_<시각>`으로 보존한다. 확인 없이 삭제하지 않는다.

### 8.3 운영 재개 후 문제가 발견된 경우

배포 후 신규 운영 데이터가 발생했다면 과거 덤프로 즉시 복원하지 않는다. 그 경우 신규 거래·생산·회계 데이터가 유실될 수 있으므로 다음 중 하나를 승인받아 수행한다.

- 핫픽스
- 추가 migration
- 운영 중단 후 신규 데이터 별도 보존 및 재처리
- 승인된 시점 복원

## 9. 완료 증적

다음을 한 묶음으로 보관한다.

- 릴리스 PR
- 승인된 40자리 SHA
- 원본→미러 모듈 매핑표
- 트리 해시 검증 결과
- 복제본 리허설 결과
- DB dump와 파일스토어 tar 파일명
- 백업 무결성 검사 결과
- `-u` 로그
- `-i` 로그
- 재기동 로그
- 전체 모듈 상태 쿼리 결과
- 화면 확인 결과
- 롤백 리허설 로그
- 실행자, 승인자, 시작·종료 시각

## 10. 현재 남은 항목

- 운영 사출품 BOM 18건 정리 확인 쿼리 회신
- PR #9 검토·머지 → 확정 릴리스 SHA(머지 후 40자리) 기록
- 복제본 백업·업그레이드·복원 리허설
- 운영 유지보수 일정 및 승인