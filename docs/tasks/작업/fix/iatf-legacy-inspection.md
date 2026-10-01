# 구형 IATF 공정검사 입력·집계·재검사 호환성 보완

## 요청과 기준

- 요청: 2026-10-01 사용자 직접 지시. 구형 IATF 템플릿과 Odoo 업그레이드 후 검증 규칙의 충돌을 적극 보완한다.
- 담당: 현재 Codex 작업. 직접 승인된 기존 IATF 보완을 이어 수행하며 별도 대화에 작업을 발송하지 않는다.
- 정본: `wilcoco/odoo`, `fix/iatf-legacy-inspection`, 기준 `4a135f22c866` (`update/iatf_passive/after20260930`). 이전 사용자 지정 계보를 이어 사용한다.
- 정본 작업 위치: `odoo_gh/.worktrees/iatf-legacy-inspection`. 원래 odoo 및 odoo_gh 체크아웃은 전환하지 않는다.
- 미러: 별도 `odoo_gh/.worktrees/iatf-legacy-mirror`, 같은 작업 브랜치, 기준 `c6d423ef1`.
- 기존 `go_relay_plc/config.ini` 미커밋 변경 및 병행 바코드 작업 보존. 원격 운영 적용·푸시·PR·기존 문서/검사 결과 DB 수정은 수행하지 않는다.

## 수정 범위와 영향

- 대상 정본 모듈 `addons_custom/iatf_process_inspection`, `18.0.1.0.14` → `18.0.1.0.15`.
- 런 묶음은 검사수량 0으로 생성되지만 `_AUTO_SOURCE_FIELDS` 전체 잠금 때문에 실제 검사값도 입력할 수 없었다. 생산 범위 필드와 검사 입력을 분리하여 초안·검사 중에 실제 수량/측정값/판정 입력을 허용한다.
- 생산 원천/회사/제품/LOT/수량 범위는 일반 사용자 입력으로 변경하지 않는다. 판정·상신·승인·자동 연동된 문서는 입력 및 상태 되돌리기를 막는다. 과거 확정 문서에 스냅샷이 없어도 이를 새 검사 중 문서로 승격하지 않는다.
- 검사 시작 또는 실제 입력 이후 생산 범위를 고정한다. 후속 단위 MO는 새 런 검사서로 집계하고 이전 단위 재호출을 모든 기존 묶음에 대조하여 중복 수량을 방지한다. 완료 실적은 검사 수량으로 자동 인정하지 않는다.
- `새 재검사`는 원검사와 연결된 새 초안을 만든다. 측정값·검사수량·합격 결과·기존 승인/스냅샷은 복제하지 않으며 판정 전에 사유와 실제 검사값을 요구한다. 원검사의 SPC/부적합/보류/승인 이력을 자동 취소하거나 대체하지 않는다.
- 완료 출고에 증빙을 소급 생성하는 기존 차단은 유지한다. 이 경우 원본을 열어 덮어쓰거나 새 승인 근거를 붙일 수 없다.
- 신규 재검사 메타데이터가 없는 과거 문서의 원본 payload 구조는 유지한다. 과거 승인 시각/사용자/JSON을 일괄 다시 기록하지 않는다.
- Odoo 18 폼의 readonly/버튼 표시를 서버 규칙과 맞추고 런 집계·입력 방법을 안내한다. 공통 결재 엔진, 패스 모드, 사출 양품 근거, 재고/금융 로직은 변경하지 않는다.

## 검증

- 별도 DB `codex_iatf_legacy_20261001`, 기존 중립화 시험 DB `codex_iatf_passive_20260930`에서 복제. cron·메일 서버·fetchmail 비활성 및 발송 대기 메일 취소, HTTP 임의 포트/cron worker 0.
- Odoo `18.0+e-20251117` 및 기존 Enterprise/MES 앱 포함. 현재 localhost:8069 서비스 DB는 수정하지 않는다.
- 시험 코드: 이 작업의 코드 커밋. 시험 후에는 기록과 미러 복사만 수행하며 코드 변경 없음. 정본·미러 커밋 대응은 아래에 기록한다.
- 테스트 경로: `/tmp/codex-iatf-legacy-addons` 우선, 이어 `/tmp/codex-iatf-passive-addons,/tmp/codex-iatf-passive-mes,/opt/plugins/odoo_plugins,/opt/odoo/addons`.
- 1차: 38개 중 기존 집계 시험 4개 오류. 승인 관리계획이 없는 시험에서 검사항목이 비어 있던 fixture를 보완했다. 실제 필수 관측값 검증은 완화하지 않았다.
- 2차: 초안·재검사·실제 단위 생산 분리·자동 증빙·패스 회귀 43개 실패 0/오류 0.
- 3차: 확장 95개 중 17 실패/1 오류. 복제 DB의 패스 활성 상태 때문에 정상 차단 시험이 통과한 17건은 시험 기본 모드를 해제하여 교정했다. 과거 출하 판정 재개 시험 1건은 강화된 원본 보호 규칙에 맞춰 상태 재개 차단도 검증하도록 수정했다. 제품 검증을 완화하지 않았다.
- 최종 4차: **95개, 실패 0 / 오류 0 / 건너뜀 없음**, 101.28초. 로그 `/tmp/iatf-legacy-tests-r4.log`. 초안·입력 잠금·재검사 10, 런 집계 9, 자동 근거 4, 출하 52, 패스 모드 20개.
- 시험 기본 회사는 패스 비활성. 패스 시험 클래스는 자체적으로 활성/비활성을 전환하여 검증한다. 실제 단위 MO 3건 완료, 검사 시작 후 묶음 분리, 재호출 중복 집계 방지 및 실제 재고 출하/중복 차단을 포함한다. 실물 설비를 동작시킨 것은 아니다.
- DB 설치 확인: `iatf_process_inspection=18.0.1.0.15`, `iatf_passive_verify_test=18.0.1.0.0`; 신규 열 `run_scope_frozen`, `correction_of_id`, `correction_reason` 확인.
- 정본 작업 파일과 WSL 시험 모듈 26개 파일의 경로+내용 SHA256 일치: `da36e8b703dedbfd173e55f1bd6990cedd9cfd276e7f9355e4a4d9cf10aa498d` (캐시 제외).
- Python AST, XML parse, `git diff --check` 통과.
- 폼은 Odoo 모듈 업그레이드/XML 검증 및 일반 검사자 `get_view()`로 확인한다. 실제 브라우저 클릭·설비·운영 서버 인수시험과 구분한다.

## 실행 재현

중립화된 **별도 시험 DB 전용**으로 다음 명령을 실행했다. 실제 서비스 DB를 넣어 실행하지 않는다.

```bash
runuser -u odoo -- /opt/odoo/venv/bin/python /opt/odoo/odoo-bin \
  -c /etc/odoo/odoo.conf -d codex_iatf_legacy_20261001 \
  --addons-path=/tmp/codex-iatf-legacy-addons,/tmp/codex-iatf-passive-addons,/tmp/codex-iatf-passive-mes,/opt/plugins/odoo_plugins,/opt/odoo/addons \
  --data-dir=/tmp/codex-iatf-passive-data -u iatf_process_inspection \
  --test-enable --test-tags='/iatf_process_inspection:TestLegacyInspection,/iatf_process_inspection:TestPqcAggregation,/iatf_process_inspection:TestProcessAutoEvidence,/iatf_process_inspection:TestOutgoingGate,/iatf_passive_verify_test' \
  --workers=0 --max-cron-threads=0 --http-interface=127.0.0.1 --http-port=0 \
  --stop-after-init --logfile=/tmp/iatf-legacy-tests-r4.log
```

## 사용자 동작

1. 미확정 런 검사서에서 `검사 시작`을 누르고 실제 검사수량·측정값·판정을 입력한다. 시작 전 값을 입력해도 생산 범위는 즉시 확정된다.
2. 검사 시작 후 추가 생산된 단위 실적은 새 검사서에 모인다. 기존 검사서의 검사수량이 생산량만큼 자동 증가하지 않는다.
3. 판정/승인된 과거 검사서는 `새 재검사`로 새 초안을 만든다. 원검사 링크와 생산 범위는 보존하고 새 사유·실제 측정값을 입력하여 다시 판정/결재한다.
4. 새 재검사 합격은 원래 불합격·부적합·LOT 보류·승인을 자동 취소하지 않는다. 실제 처분/해제는 기존 승인 절차를 따른다. 완료 출고는 새 검사 근거를 소급 추가할 수 없다.

## 배포와 남은 경계

- 정본 변경 파일만 미러의 `iatf_plugins/iatf_process_inspection`에 동기화한다. 미러 native MES 코드는 변경하지 않는다.
- 배포 시 실제 DB에서 `-u iatf_process_inspection` 및 재시작이 필요하다. 신규 필드는 모듈 업그레이드로 추가하며 기존 검사서/승인 데이터를 되쓰는 마이그레이션은 없다.
- 이 변경은 확인된 공정검사 문제에 대한 보완이다. 모든 IATF 모듈의 과거 실데이터가 정상이라는 결론은 아니다. 기존 협력사 응답 중복·정산 근거·HKMC 설정 문제는 별도 범위이다.
- 양품 근거가 없는 기존 사출 시리얼은 계속 차단한다. 테스트에는 기존 수동 시험품 생성/합격 근거 확정 경로를 이용하며, 과거 실물의 근거 누락은 실제 증빙 대조 후 별도 이관으로 처리한다.

- 롤백: 배포 전 코드·DB 백업을 확보한다. 새 재검사/분리 집계가 생성된 뒤에는 이전 코드를 덮어쓰면 보호 규칙과 화면이 달라지므로 신규 입력을 중단하고 영향 기록을 대조한다. 필요하면 승인된 배포 전 코드·DB 백업으로 함께 복구하며 새 검사 이력을 임의 삭제하지 않는다.
- 이번 변경은 별도 정본/미러 작업 브랜치에만 보관한다. 원래 `checkpoint/20260930`, localhost:8069 서비스, 운영 서버는 이번 보완으로 갱신하지 않았다. 브라우저 클릭·실제 설비 인수시험은 미실행이다.

## 커밋 및 동기화 대응

- 정본 코드와 이 기록을 같은 커밋에 포함한다. 미러 동기화 커밋은 해당 정본 코드 SHA를 기록한다.
- 미러 반영 범위: `iatf_plugins/iatf_process_inspection`과 같은 상대 경로의 작업 기록. 기준 시점의 타 모듈·MES·PLC 설정은 보존한다.
