# flushing/20260918 정본 흡수 완료 (2026-09-21, 저자: Claude 개발)

수신: 서버 담당(원도영) · 참조: 홍정수

## 1. 결과
- odoo_gh `flushing/20260918`(10커밋: 사출 MO 실시간 증분 갱신·작업장별 변경 알림, 조립 MO 목록 전용 뷰, 바코드 기준정보 revision API, HKMC 완제품 LOT 규칙, escon_lot_trace 2.0)을 정본 wilcoco/odoo-uat main 에 3-way(base=운영 0b36e7f)로 흡수했습니다. 정본 커밋 044c09e.
- 충돌 9곳 해결: 매니페스트는 양쪽보다 높게(gh_total_mes 18.0.1.33, injection_worksite 18.0.8.11.0, escon_lot_trace 18.0.2.0.0), 사출 MO 모델은 원도영 님 추가분 그대로, `quality_check.do_pass` 는 원도영 님 쪽(출하검사일 때만 시리얼 발행), 현장 시험 파일 4개는 정본 쪽(확정 BOM 보호 픽스처).
- 시험: 격리 실행기 업그레이드 + 7모듈 741/741 통과(원도영 님 시험 test_mo_realtime·test_hkmc_finished_lot·test_assembly_mo_list 포함). 이식 닫힘 OK. UAT 배포 완료.
- 릴리스 범위: **다음 묶음**(이번 PR #9/#10 아님). 새 필드 19개 → 복제본 리허설 대상.

## 2. 부탁
1. **flushing/20260918 을 미러 main 에 머지하지 말아 주세요.** 정본에서 검증된 묶음이 다음 릴리스 PR 로 미러에 갑니다. 지금 머지하면 정본과 운영이 다시 양쪽으로 갈라집니다.
2. 계속 개발하시는 것은 그대로 그 브랜치(또는 새 브랜치)에 커밋하시고, 쌓이면 큐에 한 줄("flushing 에 N커밋 추가, 내용 …") 남겨 주시면 제가 가져갑니다. 정본과 겹치는 파일(injection_worksite controllers/models, gh_total_mes mo_model/quality_check)은 충돌이 나므로 가능하면 작게·자주가 좋습니다.
3. 급한 운영 수정은 근거를 큐에 올려 주시면 정본에서 먼저 처리해 별도 릴리스로 보냅니다.
4. 정본 반영본을 확인하시려면 UAT(https://odoo-production-beb1.up.railway.app) 또는 odoo-uat main 을 보시면 됩니다. 다른 결과가 나오면 알려 주세요.

## 3. 참고
흡수하면서 본 것: `quality_check.do_pass` 의 두 판(정본: MO 있으면 시리얼 발행 후 출하검사만 lot 기록 / 원도영: 출하검사일 때만 발행)은 원도영 님 쪽을 택했습니다. 의도가 다르면 알려 주세요.
