# 세금계산서 반입 및 인수인계 회신문서 재검토

검토일: 2026-09-10. 고정 소스 읽기 전용 검토, 독립 모의 실행, 신규 격리 DB의 실제 Odoo ORM 검증 결과를 대조했다. 운영 서버·운영 DB·외부 업무 시스템에 접속하지 않았고 제품 소스 수정·push·배포를 수행하지 않았다. 실제 시험은 루트 검토자가 별도 Docker Odoo 18.0-20260609/PostgreSQL 17 환경의 폐기용 `codex_review2` DB에서 실행했으며, 이 하위검토는 작성한 probe와 원본 로그/구조화 결과를 대조했다. 모의 실행과 실제 ORM 실행을 구분한다.

## 1. 기준과 판정

- `tax/`: `wilcoco/odoo fix/tax-invoice-row-rollback @ c9ad89dd7f593a77b7ffa8aa6f17f41c3a7f8047`
- `tax_original/`: `feat/tax-invoice-file-import @ ce025d508f40c143db13ce46bfec35c0aa893fc9`
- `baseline/`: `18.0 @ 17e9fac0eeeb7564e72e826caaf1865ba3b466a1`
- `handover/docs/Codex_인수인계_ERP측_회신자료.md`: `docs/codex-handover-reply @ 6c3acf4e7bad1e2ed095de12888a8e8102434ea4`
- MES 비교: 기존 `work/mes_source` 스냅샷, 로컬 읽기 전용 `odoo_gh HEAD=49002743a7243948bdc098cef77e7f2f8386fef8`, `git status --porcelain` 출력 없음. 이 로컬 확인을 원격 최신성/운영 배포 확인으로 확장하지 않았다.
- 아래 `tax/...`, `baseline/...`, `handover/...` 경로는 `work/review_round2/` 기준이다. `outputs/`와 `work/handoff-queue/`는 대화 작업 디렉터리 기준이다.

| 항목 | 판정 | 근거·한계 |
|---|---|---|
| H11 / ACC-01, `Move.create` 후 예외에 대한 청구서 롤백 | **수정본의 해당 범위 해결 확인** | 실제 Odoo create/flush 후 실패 주입: bad 0건·good 1건, good 공급가 100,000/세액 10,000/합계 110,000 확인 |
| 자동 게시 실패 격리·결과 집계 | **수정본의 해당 범위 해결 확인** | 실제 action_post 후 실패 주입: bad draft + good posted 및 “게시 1건/초안 1건” 집계 확인 |
| 행 전체 원자성 | **부분수정, 잔여 결함** | 숫자 파싱·거래처 검색/생성이 try/savepoint 밖. 신규 거래처 잔존 및 후속행 중단을 실제 ORM 재현 |
| 원본 수정과 cherry-pick 이식 | **관련 수정 동등** | 회귀 테스트 byte 동일, create/flush·게시·요약 AST 동등. 신규 승인번호 키 계약을 유지해 전체 파일/patch-id는 다름 |
| 18.0/운영 배포 반영 | **미반영/추가 확인** | c9ad89d의 직접 부모는 17e9fac0eee. c9ad89d는 기준 18.0의 조상이 아니며 최신 원격 18.0 역시 17e9fac0eee라는 루트 검토 결과. 실제 운영 파일은 본 검토 미접속 |
| H12 / ACC-02 음수 세액 | **미해결, 이번 수정 범위 밖 기존 결함** | 실제 ORM 입력 -1,000,000/-100,000/-1,100,000이 세액 0·합계 -1,000,000 초안으로 생성되고 오류 0건 표시 |
| 회신문서 근거 구분 | **정정 필요** | 제출자 측정 주장과 이번 독립 확인이 혼재. HEAD 이동 주장은 확인값과 충돌; 모듈/파일 항목 수 혼용 |

## 2. 해결 코드의 범위와 동등성

### TAX-01: 청구서 생성 및 자동 게시의 DB 변경 격리

`tax/addons_custom/account_kr_reports/wizard/tax_invoice_import.py:270`에서 try가 시작하고, 274~276행의 `cr.savepoint()` 안에서 `Move.create` 및 `mv.flush_recordset()`을 수행한다. `created.append`와 `seen_in_file.add`는 277~278행에서 savepoint 성공 종료 후 수행한다. 따라서 이 범위 내부의 생성 실패를 정상 생성으로 집계하지 않는다.

게시도 같은 파일 284~295행에서 각 move별 savepoint로 분리했고, `posted += 1`은 성공 종료 뒤 실행한다. 요약의 게시/초안 수는 297~298행 및 335~346행에서 생성·게시 개수로 산출한다.

기준 Odoo 코어를 Git object로 읽어 대조했다.

- `odoo/sql_db.py:123`: `_FlushingSavepoint`는 진입 전 `cr.flush()`를 호출한다.
- `odoo/sql_db.py:128`: rollback 시 환경을 clear한 뒤 SQL rollback을 수행한다.
- `odoo/sql_db.py:132`: 정상 종료 시 다시 flush하고, 그 flush에서 실패해도 savepoint를 rollback한다.
- `odoo/sql_db.py:175`: 기본 `savepoint(flush=True)`가 이 구현을 사용한다.
- `odoo/models.py:6769`: `flush_recordset`은 ORM의 pending computation/write를 처리한다.

따라서 명시적 `mv.flush_recordset()` 위치는 적절하며, `flush=True`의 종료 flush 역시 관련 지연 ORM 쓰기를 잡는다. 이 설명은 PostgreSQL의 `DEFERRABLE INITIALLY DEFERRED` 제약까지 flush 한 번으로 조기 검증된다는 뜻은 아니다. 문서의 “지연 제약”은 ORM의 지연 재계산·쓰기 의미로 한정해 설명하는 편이 정확하다.

### TAX-02: 원본 수정과 이식본 비교

`tax_patch_equivalence.json`에 결과를 저장했다.

- `tests/test_tax_invoice_import.py`는 원본과 이식본이 byte 단위 동일.
- SHA-256: `cb543dac05126f353fc9c2d416bf4a12e10c41df8b7ad0fa4fb625fa4a2b612f`.
- 생성 try/savepoint 블록은 `seen_in_file`에 넣는 변수 `approval` → `approval_key`만 정규화하면 AST 동일.
- 게시 if 블록 및 `_summary`는 AST 그대로 동일.
- wizard 전체 파일은 다르다. 이식본 9행, 171~175행, 185~195행이 최신 18.0의 승인번호 정규화·전사 중복 키 조회를 유지한다.
- stable patch-id도 원본 `46bf4d7fd216ea1922a2d0263e1d80888a180b8d`, 이식본 `bc1816404ab5ccd7902f40f0a331f7c5a64051f3`로 다르다. 단순 byte 동일한 cherry-pick이라고 기록하면 안 되지만, 요청된 트랜잭션 수정이 유실된 증거는 없다.

## 3. 남은 결함

### TAX-R1 / P2: 실패한 반입 행의 신규 거래처가 남는다 — 기존 잔여, 새 회귀 아님

근거: `tax/addons_custom/account_kr_reports/wizard/tax_invoice_import.py:223`에서 `Partner.create`를 먼저 호출한다. 세금코드 검사 240~246행과 청구서 생성 savepoint 274행보다 앞이며, try도 270행에서야 시작한다.

재현 조건: `create_partner=True`, 미등록 거래처, 이후 `Move.create` 성공 직후 검증 예외 주입. 결과는 해당 청구서를 롤백하지만 신규 거래처는 savepoint보다 먼저 생성되어 남는다. 모의 DB 및 실제 ORM에서 bad 청구서 0건·good 청구서 1건인데 bad 신규 거래처 1건이 남았다. 실제 결과는 `tax_orm_followup_results.json`의 `new_partner_leaks_on_failed_invoice`에 있다.

더 단순한 경로도 있다. 신규 거래처 자동 생성 후 파일의 양수 세액에 맞는 세금코드를 찾지 못하면 246행에서 continue한다. 모의 시험은 두 오류행에서 “생성 0건 / 오류 2건”인데 거래처 2건이 남았다. 실제 ORM은 `_pick_tax`의 빈 반환을 주입한 한 행에서 “생성 0건 / 오류 1건”, 청구서 0·거래처 1건을 확인했다(`new_partner_leaks_on_missing_tax`). 청구서 create의 예외가 없어도 세금코드 부재 조건에서 발생하는 잔여다.

조치 방향: 행에서 생성되는 DB 부작용을 하나의 savepoint 안에 포함하고, 생성 전 검증을 먼저 수행한다. 세금코드 실패를 continue로 처리한다면 신규 거래처를 만들기 전에 판정하거나 전체 행 rollback을 명시해야 한다. “행 단위 롤백 완료”라고 표현하려면 거래처까지 다룬 시험이 필요하다.

### TAX-R2 / P2: 잘못된 숫자 한 행이 전체 반입을 중단한다 — 기존 잔여, 새 회귀 아님

근거: 같은 파일 `_to_float` 43~49행, 호출 202~204행. `float('1.2.3')`가 발생시킨 `ValueError`를 감쌀 try는 270행 이후에만 존재한다.

재현 조건: 첫 오류행의 공급가액을 `1.2.3`으로 하고 다음에 정상행을 둔다. 원본 action_import AST 실행에서 `ValueError: could not convert string to float: '1.2.3'`가 밖으로 빠져나갔다. 실제 ORM에서도 정상행 → 오류행 → 정상행 입력에서 같은 ValueError가 전파되고 wizard.result=False, 첫 정상행만 생성·마지막 정상행 미처리를 확인했다(`malformed_amount_aborts_later_row`). probe는 관측을 위해 예외를 잡았고 이후 전체 rollback했다. 실제 RPC에서 예외가 요청 밖으로 전파되면 앞선 정상행도 상위 트랜잭션 rollback 대상이다.

`Partner.create` 검증 예외도 같은 try 밖이므로 동일한 전체 중단 경계에 있다. 행 단위 실패 수집을 의도한다면 숫자 파싱/거래처 생성까지 행별 예외 처리 범위에 포함할 필요가 있다.

### TAX-R3 / P1: H12 / ACC-02 음수 수정 세액 누락은 여전히 남아 있다

근거: 같은 파일 230~238행은 `tax_amt > 0`만 과세로 분류하고, `_pick_tax` 318~321행은 `tax_amt <= 0`이면 빈 세금코드를 반환한다. 251~264행은 세금코드가 없으면 단가를 공급가액만 넣고 tax_ids를 비운다.

공급가액 -1,000,000 / 세액 -100,000 / 합계 -1,100,000의 수정 파일은 합계 검사에 통과하지만 실제 ORM 생성 결과는 amount_untaxed=-1,000,000, amount_tax=0, amount_total=-1,000,000, 분개 라인 2개이고 “생성 1건 / 오류 0건”으로 표시됐다(`negative_tax_ACC_02`). 행별 rollback 수정만으로 H12를 완료 처리할 수 없다. 기존 최종 근거 `outputs/04_상세검토근거.md:32`의 H12↔ACC-02~06 대응과 699행 ACC-02에 일치한다.

## 4. 시험 근거의 신뢰성

### 제출 회귀 테스트가 실제로 검증하는 것

`tax/addons_custom/account_kr_reports/tests/test_tax_invoice_import.py:93`의 새 회귀 테스트는 mock으로 결과를 꾸미기만 하는 시험이 아니다. 112~118행에서 실제 ORM `original_create`를 먼저 호출한 후 `ValidationError`를 주입하고, 124~129행에서 실제 검색으로 bad가 없고 good이 있는지 확인한다. 이 시험이 실제 Odoo DB에서 실행됐다면 최초 보고의 orphan draft 문제를 직접 검출하는 가치가 있다.

다만 다음 경계는 확인되지 않는다.

- 예외를 create 직후 주입하므로 명시적 flush 단계 실패 자체를 검증하지 않는다.
- `post_moves=True`를 주지 않는다. 실제 action_post 후 실패·부분 게시·요약 일치는 이 테스트로 입증되지 않는다.
- 기본 `create_partner=False`이고 거래처는 사전 생성되어 신규 거래처 rollback을 시험하지 않는다.
- 숫자 파싱 실패, bad 뒤 동일 승인번호 재시도, 파일 재반입, 다회사 세목, concurrent duplicate는 시험 범위 밖이다.
- 123행 `assertIn('오류', wiz.result)`는 정상 결과 요약에도 “오류 0건”이 포함되어 보조 단언으로 약하다. 다만 bad/good 레코드 단언이 있으므로 이 이유만으로 테스트 전체를 공허한 통과라고 부를 수는 없다.

### silent skip 방지는 여전히 보장되지 않는다

같은 테스트 파일 17~22행은 10% 세금의 전역 존재 여부만 보고 KR 차트를 로드하려 하고, 예외를 catch 후 pass한다. 25~27행의 `tax10` 검색도 현재 회사 필터가 없다. 101~102행에는 여전히 `skipTest('세금 코드 없는 환경')`가 남아 있다. 다른 회사/매출 10% 세금만 있거나 KR 템플릿 로드에 실패하면 회귀가 skip될 수 있다. 이번 최초 실제 설치 시험에서도 같은 위험이 확인됐다. `isolated_install_tests.log:1505`는 180 tests, 0 failed/0 error를 보고하지만, 1381~1385행에서 한국 세목 시험 3건, 1390~1395행에서 반입 시험 3건(새 orphan 회귀 포함)이 skip됐다. 이는 fixture가 없는 첫 실행의 범위 한계이며 제품 동작 결함 6건으로 계산하지 않는다. 이후 l10n_kr 설치·KR 차트 fixture를 확보하고 `TestKrTaxType` 3개와 `TestTaxInvoiceImport` 5개를 재실행해 **8건 통과, 실패0·오류0·skip0**을 확인했다(`isolated_tax_regression.log:66`, `:85`, `:93`). 최초 누락됐던 세금 관련 6건은 이 재실행으로 실제 검증됐다. 코드의 조건부 skip 경로가 제거됐다는 뜻은 아니다.

커밋 메시지의 “13/13 그린”, `work/handoff-queue/docs/머지배포_요청_20260910.md:12`의 “32/32”, 회신 84~86행의 “savepoint 제거 시 실패”는 **제출자의 실행 주장**이다. 원래 제출자가 수행한 해당 실행의 정확한 명령·전체 로그·총수/skip 수와 동일한 커밋/실행 환경은 이번에 독립 확인하지 않았다. 대신 현재 수정본의 관련 두 클래스 8건을 격리 환경에서 별도로 실행해 실패0·오류0·skip0으로 확인했다. 제출 숫자 자체를 허위라고 단정하지도 않는다.

### 이번 독립 실행

`tax_transaction_probe.py` / `tax_transaction_probe_results.json`:

- 수정본 action_import 및 helper를 AST로 추출해 그대로 실행.
- 기준 Odoo의 `Savepoint`, `_FlushingSavepoint` 클래스도 Git object에서 그대로 추출.
- DB는 SQLite, 모델·recordset·flush는 단순 모형. 실제 Odoo ORM/PostgreSQL·회계 엔진·권한·recompute/훅 통합은 실행하지 않음.
- 8개 관측 검사 완료: create 후 실패, record flush 실패, cursor 종료 flush 실패, savepoint 제거 변이, 게시 후 실패, 신규 거래처+create 실패, 신규 거래처+세금 없음, 잘못된 숫자.
- 원본 savepoint를 모형에서 제거하면 실패한 청구서가 잔존한다. 모형의 rollback 동작을 확인하는 변이 검증이며 제출자가 보고한 Odoo 사보타주 로그를 대신하지 않는다.

### 신규 격리 DB의 실제 ORM 실행 — 7개 결과 확인

`tax_orm_probe.py`를 루트 검토자가 별도 Odoo 18.0-20260609/PostgreSQL 17의 폐기용 `codex_review2`에서 실행했다. 새 KR 회사(id 7), 실제 kr 차트, 현재 회사 10% 매입 세목(id 26), 구매저널(id 19), account_kr_reports 18.0.1.5.1을 사용했다. 각 case와 setup은 rollback했으며 probe는 commit하지 않는다. 원본: `isolated_orm_followup.log`, 구조화 결과: `tax_orm_followup_results.json`.

| 실제 ORM case | 관측 | 판정 |
|---|---|---|
| 실제 Move.create 후 ValidationError | bad 0, good 1; good 세액 10,000·합계 110,000 | 수정 효과 확인 |
| 실제 flush_recordset 후 ValidationError | bad 0, good 1; good 라인 3개 | 수정 효과 확인 |
| 실제 action_post 후 ValidationError | bad draft / good posted, 게시1·초안1 | 수정 효과 확인 |
| 신규 거래처 + 청구서 생성 실패 | bad 청구서0, 신규 거래처1 잔존 | TAX-R1 재현 |
| 신규 거래처 + 세금코드 빈 반환 | 생성0·오류1, 신규 거래처1 잔존 | TAX-R1 추가 경로 재현 |
| 정상→잘못된 숫자→정상 | ValueError 전파, 첫 정상행만 존재, 요약False | TAX-R2 재현 |
| 음수 수정 세액 | 파일 세액 -100,000 → 전표 세액0, 합계 -1,000,000, 오류0 | TAX-R3 / ACC-02 재현 |

세 가지 수정 효과 검사의 check_passed=True, 네 가지 잔여 조건의 defect_reproduced=True를 확인했다. create/flush/post 실패는 실제 메서드 수행 후 의도적으로 예외를 주입한 트랜잭션 시험이다. 운영에서 발생했던 원래 오류를 동일한 업무 자료로 재현했다는 뜻은 아니다. PostgreSQL DB rollback, ORM 재조회 및 실제 회계 금액/상태는 모형이 아닌 실제 실행 결과다.

첫 probe 실행은 기존 회사의 차트/세목/저널 fixture가 충분하지 않아 setup_error로 종료했다(`isolated_orm_probes.log:297`). 이를 제품 결함으로 세지 않았고, 새 KR 회사를 명시 구성해 위 7건을 모두 재실행했다. 원래 모듈 회귀의 최초 skip과 이 setup_error도 성공 실행 이력으로 덮어쓰지 않고 보존했다.

## 5. 인수인계 회신문서 대조

### DOC-01 / P2: “18.0이 이후 이동했다”는 확인값과 충돌한다

- 회신문서 `handover/docs/Codex_인수인계_ERP측_회신자료.md:12`
- 복사본 `outputs/07_ERP측_회신자료_실측.md:12`
- 반영된 요청서 `outputs/06_통합개발_인수인계_요청서.md:15`

모두 17e9fac0eee 이후 HEAD가 이동했다고 기술한다. 그러나 이번 루트 검토가 갱신한 원격 18.0은 여전히 `17e9fac0eeeb7564e72e826caaf1865ba3b466a1`이다. `work/handoff-queue/docs/머지배포_요청_20260910.md:20`도 이 커밋을 현재 18.0으로 명시한다. 역사적으로 잠깐 다른 HEAD였다가 돌아왔는지는 증거가 없으므로 단정하지 말고, 현재 검증된 SHA와 조회 시각을 기록해야 한다.

새 회신문서와 outputs/07은 byte 단위 동일하다. 새 파일을 받았다는 이유만으로 outputs의 기존 진술에 독립 증거가 추가된 것은 아니다.

### DOC-02 / P2: 모듈 수와 파일/폴더 항목 수를 구분해야 한다

회신 16~17행은 odoo_plugins 31개/iatf_plugins 66개 항목, 38행은 정본 55개 모듈, 42행은 “55개 중 3개 드리프트”로 표현한다. 요청서 19~20행에도 전파됐다.

독립 집계 정의: addons 경로의 **직접 하위 디렉터리 안에 `__manifest__.py`가 있는 것**을 모듈로 센다. 부모 addons 경로 자신의 manifest와 static/views/에디터설정·문서는 모듈 수에 넣지 않았다.

| 고정 스냅샷 | 직접 하위 모듈 수 | 전체 직접 항목 수 | 구분 |
|---|---:|---:|---|
| ERP 17e9fac0eee addons_custom | 53 | 58 | 모듈 외 static/views 및 파일 3개 |
| MES 49002743 iatf_plugins | 60 | 67 | 모듈 외 static/views 및 파일 5개 |
| MES 49002743 odoo_plugins | 28 | 31 | 모듈 외 .vscode와 파일 2개 |

55는 ERP의 모듈 53개에 static/views 폴더를 더한 개수와 일치한다. 31은 MES 모듈 수가 아니라 파일·설정 폴더를 포함한 항목 수다. iatf 66개 항목이라는 수는 이 스냅샷의 67과 다르다. 집계 정의 없이 “모듈”로 전달하면 설치/동기화 범위를 잘못 산정할 수 있다.

다음 핵심 관계는 **독립 대조로 확인됐다** (`tax_handover_inventory.json`).

- ERP 53개 모듈이 iatf 미러에 모두 존재.
- 공통 53개 중 50개 byte 동일, 3개 차이: `escon_mainmenu`, `pumui_approval`, `supplier_portal_purchase`.
- 각각 버전 1.0.0→1.1.0, 1.0.0→2.4.0, 1.3.0→1.3.1로 회신 표 46~48행과 일치.
- 미러 전용 7개 목록도 회신 39행과 정확히 일치.

즉 “공통 모듈 전체를 포함하는 미러이고 일부 드리프트가 있다”는 결론은 유효하다. 정본만으로 운영 실행 코드를 확정할 수 없다는 50~55행의 경계도 적절하다.

### DOC-03: 제출자의 측정 주장과 독립 확인을 분리해 표시해야 한다

회신 4행은 문서 전체를 “저장소·컨테이너·운영 서버에서 직접 측정”으로 소개한다. 그러나 항목마다 근거 수준이 다르다.

| 내용 | 이번 확인 수준 | 필요한 표기/추가 증거 |
|---|---|---|
| 로컬 MES HEAD 49002743/clean | 이번 로컬 read-only Git로 직접 확인 | 로컬 확인이라고 표시 |
| MES 원격 main도 49002743, 저장소 이전(13행) | 제출 주장. 본 하위검토는 원격을 직접 조회하지 않음 | 원격 ref 조회 응답/시각을 확보한 담당이 확인했다는 범위를 표시 |
| 운영 Odoo/DB/설정, 개발 PG/차트/평가방식(23~30행) | 제출 문서 진술. 운영 접근 없음 | 명령·응답·시각·대상 환경·실행자와 원본 로그 링크 필요 |
| 운영 CoA 한국(29행) | 문서 스스로 “사용자 확인”으로 기재 | 서버 실측과 구분 유지 |
| 운영 addons_path/평가방식/PG 미확인(27·30·110~112행) | 미확인으로 남긴 것은 적절 | 이미 제출된 서버회신 자료와 정리하되 현시점 실행본 독립 확인과 구분 |
| SQ 적용표·CSR·실사례·채점비율(59~64행), UAT/양산상태(68~75행) | 제출 주장 및 업무 담당 확인사항 | 해당 평가표 버전/원본과 회사 적용 결정·현장 확인 기록 필요 |
| 세금 수정 머지 대기(97행) | 방향은 현재 고정 18.0과 일치, 브랜치 표기는 구 버전 | 실제 인수 대상은 c9ad89d fix 브랜치임을 함께 명시 |

추가로 이미 받은 `work/handoff-queue/docs/서버확인_회신_20260909.md:73` 및 101~114행에는 운영 addons_path와 마운트 순서가, 197~216행에는 서버/개발 PC 미러 HEAD가 제시되어 있다. 이를 인수 체크리스트에서 “자료 미수신”으로만 남기기보다 **서버 담당 회신 수신, 독립 재검증 미실시**로 구분할 수 있다. 그 문서 역시 서버 담당이 작성한 제출 증거이며 이번 하위검토가 서버에서 명령을 실행한 것은 아니다.

## 6. 인수 결론

1. H11은 **청구서 create/flush/게시 실패 격리 확인**, **행 전체 격리 잔여(TAX-R1/R2)**로 세분화한다. H12의 ACC-02 음수 세액 누락은 실제 ORM으로 재현되어 미해결로 유지한다. 제품 소스 수정은 이번 재검토에서 수행하지 않았다.
2. 기존 세금 회귀 두 클래스 8건은 실패0·오류0·skip0으로 통과했다. 최초 설치 시험의 세금 관련 skip 6건도 이 재실행으로 해소됐다. 전체 ERP 회귀는 중복을 제거하면 180개 중 **179개 실행 통과·1개 skip**이며, 남은 1개는 MES injection_worksite가 필요한 PQC 단위 MO 경로다(`independent_regression_summary.json`). 원본 제출 회귀가 검증하지 않는 경계는 이번 실제 ORM probe 결과로 보완했다.
3. 회신문서와 요청서의 현재 ERP SHA, 모듈 집계 정의, 제출자 측정/독립 확인/운영 미확인 구분을 정정해야 한다. 이번 고정 소스와 격리 DB 결과를 운영 배포 완료 또는 인증 적합으로 확장하지 않는다.
