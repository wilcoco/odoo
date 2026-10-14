# 작업 기록: 취소 세금계산서 환불완료 금액

- 요청: 매출처·매입처 취소 세금계산서 목록의 완료 금액 열을 `환불완료 금액`으로 표시한다.
- 정본: `wilcoco/odoo`, `addons_custom/account_kr_plus_patch`
- 브랜치·기준: `fix/refund-paid-label`, `60a67ba8279c41e130ffa03ff2475e67939b1552`
- 영향: 취소 목록의 열 제목만 변경하며 정상 목록, 폼, 금액·전기·결제 로직은 변경하지 않는다.
- 버전: `18.0.2.5.5` → `18.0.2.5.6`; DB 마이그레이션 없음.
- 검증: XML 파싱, Python 문법 컴파일, 정적 뷰 단언 및 정본-미러 비교 통과.
- 런타임: Odoo DB·브라우저 검증과 운영 배포는 수행하지 않는다.
- 배포: 승인된 환경에서 `account_kr_plus_patch` 모듈 `-u`와 재기동이 필요하다.
- 미러: `odoo_gh/iatf_plugins/account_kr_plus_patch`로 동일 동기화한다.
