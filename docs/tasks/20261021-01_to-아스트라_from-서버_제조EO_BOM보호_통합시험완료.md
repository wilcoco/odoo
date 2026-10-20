수신: 아스트라
발신: 서버
상태: 요청

# 제조 EO · 최신 main · BOM 보호 통합 시험 결과 검토

승인: 사용자 직접 요청(2026-10-21 이 대화) — 현재 EO를 최신 main/BOM 보호에 통합하고 시험 DB에서 검증. 기존 생산지시·BR·이종검사 보존 및 IATF/SQ 중복 방지. 운영 변경 금지. 이 기록은 PR 병합·운영 반영 승인이 아니다.

10-20 제조 EO 공유 건의 후속이다. 현재 품번별 BOM을 유지하며 공통 원본/컬러 BOM 과거 시험은 포함하지 않았다. 사용자가 합의한 동일 작업을 서버 측 Codex가 진행했으며 추가 에이전트 재배정은 하지 않았다.

## 검토할 PR과 원본

- 정본 `wilcoco/odoo`: [초안 PR #41](https://github.com/wilcoco/odoo/pull/41), `codex/eo-change-management`, 제출 `d005cf4ff3d0595086a880e793fa1d00c079ee47` / 코드 `92148cf32a96a5a6a024df5e642d5ffae76e9d0d`.
  [정본 작업 기록](https://github.com/wilcoco/odoo/blob/d005cf4ff3d0595086a880e793fa1d00c079ee47/docs/tasks/작업/codex/eo-change-management.md).
- 미러/MES `escon-odoo/odoo_gh`: [초안 PR #13](https://github.com/escon-odoo/odoo_gh/pull/13), `codex/eo-bom-protection`, 제출 `d0c9974c9f23f73772523f80c2dd32b22ee4d585`.
  [같은 브랜치의 작업 기록·적용 및 원복 기준](https://github.com/escon-odoo/odoo_gh/blob/d0c9974c9f23f73772523f80c2dd32b22ee4d585/docs/tasks/작업/codex/eo-bom-protection.md).
  [검증 보고서·결과·체크섬](https://github.com/escon-odoo/odoo_gh/blob/d0c9974c9f23f73772523f80c2dd32b22ee4d585/docs/testing/eo-bom-protection/REPORT.md).
- 기준 main `043542a34d51d1a489ac83e40ec839eef9bc5593`, 검증 애플리케이션 SHA `5777291df6d7bca476dfa406d480e954e6ba6af1`. 이후 애플리케이션 모듈 변경 없음. 정본 두 변경 파일과 미러 Git blob 동일.

## 결과 요약

- 별도 시험 PG에 새 `odoo18_eo_integration_20261021` 생성. 기존 `odoo18_eo_test`의 백업 복제본이며 운영 또는 기존 8070/8071을 교체하지 않았다. 새 공개 포트는 없다.
- EO/BOM 보호/BR/EJ/생산 게이트/결재 회귀 133건 실패0·오류0. `865A0-5S140CA`의 시험 EO `CR-2026-0217` 등록·반려·재승인·적용·검증 종료, 구·신 BR과 이종검사14건 및 43조건 통과.
- 구 지시는 BOM17776, 새 BR 지시는 BOM18315 사용. 기존9테이블8,119행 전체 기존 컬럼 해시 동일(생산793, BR100, 검사94, CR29 포함). 원본 시험 DB도 같은 해시 유지.
- EO와 IATF 변경요청 증가1건, 별도 결재 증가0건. EO BOM의 중복 상신/승인/적용/새 개정 경로 정리. 별도 SQ EO 원장을 만들지 않았으며 동일 CR 증빙을 참조한다.
- BOM 상태 직접 변경·하위 구성 이동·RPC context 위조를 통한 보호 우회 차단. 신규 BR에서 검증된 EJ 작업장 공정 추가만 허용하며 확정 지시는 재배정하지 않는다.
- 운영 SHA043542a34 및 운영/8070/8071 이미지·시작시각 동일. 운영 DB 쓰기·배포·재시작, main/18.0 병합 없음. 최초·검증완료 시험 DB 및 filestore 백업과 실패/성공 로그를 보존했다.

## 검토 및 인수 요청

1. 정본 #41은 자동 BOM CR 훅 제거이며 **단독 배포하면 안 된다**. 미러 #13의 BOM 보호3.0.1/EO1.1.0/MES1.50.1/IATF변경관리1.1.0 조합으로 검토하고 정본 PR을 먼저 판단한다.
2. 이번 결과는 EO 기설치 시험 DB의 업그레이드/ORM 통합과 Odoo 합성 폼 검증이다. 최신 후보 브라우저·실물 스캐너/PLC 인수, 운영 설치 상태의 EO 신규 설치 리허설은 별도로 남는다.
3. SQ 전체 메뉴 재편이나 SQ 심사 충족 검증을 수행한 것은 아니다. SQ의 EO 증빙 연결은 동일 `iatf.change.request` 참조로 처리하고 중복 원장을 추가하지 않는다.
4. 운영 반영 요청이 필요하면 위 PR/모듈/기존 데이터 보존/동일 시점 코드·DB·filestore 원복 기준을 명시하여 별도 승인 범위로 요청한다. 이번 큐 전달 자체로 운영 작업을 시작하지 않는다.

개발 측/홍정수 측 전달 자료는 위 PR과 작업 문서이며, 이 큐에는 검토 결과 및 회신 링크만 추가한다.
