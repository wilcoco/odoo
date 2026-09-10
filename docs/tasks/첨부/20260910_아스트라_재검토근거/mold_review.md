# 금형·범용 점검 무결성 재검토

검토 기준: `quality/` = `wilcoco/odoo`, `fix/codex-review-iatf`, `7d6dc8b17d2436ccad9dfd315da7615dcbd30a0a`; 비교 기준 `baseline/` = `18.0`, `17e9fac0eeeb7564e72e826caaf1865ba3b466a1`. `quality/addons_custom/CLAUDE.md`를 먼저 확인했다. 소스 변경, 운영 접속, 운영 DB 변경, 배포는 수행하지 않았다.

## 판정 요약

| 항목 | 판정 | 수정된 부분 | 남은 부분 |
|---|---|---|---|
| Q10 완료 후 헤더·라인 잠금 | 부분해결 | 완료 상태 유지 중 헤더 사실 필드 write, 기존 완료 라인 write/unlink 차단 | 완료 부모로 line.create/다른 draft 라인 이동, 완료 헤더 unlink 경로 누락 |
| Q10 미래 점검일 | 해결됨(신규 create 및 날짜 write 경로) | 금형에도 날짜 constraint 추가; 범용 시트는 baseline부터 존재 | 기존 미래일 데이터 정리·기존 행 state-only 완료 경로는 별도 업그레이드 확인 필요 |
| Q10 `write(state='done')` 우회 | 부분해결 | 금형에도 완료 constraint 추가; 단순 state-only 미완료 완료 차단 | `overall_result='ok'`를 같이 쓰는 입력을 제약이 신뢰 |
| Q10 draft 되돌리기 | 기능 구현됨 / 감사추적은 부분해결 | 정상 draft→수정→done 경로 존재, state tracking=True | 추적을 끄는 context 차단 없음; 별도 정정사유·권한 제약 없음. draft 허용 자체는 명시된 설계이므로 결함으로 세지 않음 |
| Q11 온도 기준 스냅샷 | 부분해결 | 신규 기록에서 마스터 상한 단독 개정에 과거 스냅샷/판정 고정, 현행 참고값 분리 | snapshot/result 직접 write 및 동일 mold_id 재입력으로 재스냅샷 실제 재현; 기존 데이터 이관 식별 없음 |
| Q12 측정값 0/미입력 | 부분해결 | `no_value`인데 수동 `ok`/`ng`를 넣는 정확한 지적 경로 차단 | `na`로 미측정 수치 항목을 완료/종합 양호 처리; 유효한 0과 미입력 여전히 구분 불가 |
| H14/18.0.1.3.0 migration | 부분해결 | 현재 마스터를 쓰는 추정 이관임을 주석에 명시, 첫 실행 뒤 marker로 라인 재복사 차단 | 이미 1.3.0인 DB가 1.3.1로 올라갈 때 수정 스크립트 미실행; 과거 기준 추정임을 레코드에서 구분하지 않음 |

## 검증 수준

- 실제 고정 소스 메서드를 AST로 추출한 독립 모의 실행을 완료했다. 실행 파일 `reproduce_mold_guards.py`, 결과 `mold_guard_results.json`. 메서드 본문을 재작성하지 않고, 가짜 recordset/storage 및 명시 constraint dispatch에 연결했다.
- 이 모의 실행은 Odoo ORM, PostgreSQL, ACL, dependency scheduling, chatter 실행 결과가 아니다. `python3` 환경에서 `odoo`, `psycopg2`가 발견되지 않았다. 모의 결과를 Odoo 테스트 통과 건수로 합산하지 않는다.
- Odoo 의미론은 같은 고정 SHA의 core를 `git show 7d6dc8b...:odoo/fields.py`, `odoo/models.py`, `odoo/modules/migration.py`, `addons/mail/models/mail_thread.py`로 추가 확인했다. 현재 다른 checkout의 커스텀 소스를 검토 기준에 섞지 않았다.
- 별도 격리 DB에서 `mold_orm_probe.py`를 실제 Odoo ORM으로 실행한 로그를 확인했다. `isolated_orm_probes.log`의 `MOLD_ORM_PROBE_SUMMARY`에 7개 시나리오 계열, 총 12개 우회 관찰이 모두 기록되어 있다. 각 경우 savepoint에서 fixture를 생성하고 rollback하며 마지막에도 rollback했다. 현재 이 12건은 admin/superuser 환경 결과이고, 일반 담당자/모듈 관리자 권한의 재현은 `mold_role_probe.py`로 별도 시험한다.
- 제출된 “156건 통과”는 이 문서 작성 시점에 독립 재현이 확인되지 않았다. 관련 신규 테스트의 존재/내용과 실제 실행 여부를 구분했다.
- `reproduce_migration_sqlite.py`로 인메모리 SQLite에서 migration SQL의 데이터 변경도 별도 확인했다(`migration_sqlite_results.json`). PostgreSQL과 문법이 다른 UPDATE alias에 AS만 추가하고 now()를 고정했다. Odoo/실제 PostgreSQL 이관 시험으로 간주하지 않는다.

### 실제 ORM 관찰 결과

다음은 안전 조건을 통과한 테스트가 아니라 **잔여 우회가 실제로 성공한 재현**이다. fixture 생성/시나리오 실행 후 flush 및 invalidate를 거쳐 읽은 값이다. 운영 환경은 사용하지 않았다.

| Probe | 범위/건수 | 실제 관찰 |
|---|---|---|
| `done_line_create` | 금형·범용 2건 | 완료/양호 1개 항목에 미판정 라인 추가 성공; 완료 유지, 전체 pending, 항목2개 |
| `done_line_reparent` | 금형·범용 2건 | draft의 미판정 라인 이동 성공; 대상 완료 유지/pending, 원래 draft 항목0개 |
| `forged_done` | 금형·범용 2건 | 미판정 라인 False 유지한 채 상태 done·전체 ok 저장 성공 |
| `missing_value_na` | 금형·범용 2건 | value=0·judge=no_value·result=na가 전체 ok, action_done 성공 |
| `done_header_unlink` | 금형·범용 2건 | 완료 헤더 및 해당 라인 모두 실제 삭제됨 |
| `temperature_direct_write` | 온도 1건 | 95℃/상한90/ng에서 result만 ok로 변경 성공; 별도 spec_max=100 변경도 성공 |
| `temperature_same_mold_write` | 온도 1건 | 마스터 개정만으로는 과거90/ng 유지; 같은 mold_id write 후 과거100/ok로 변경 |

로그 원문: `work/review_round2/isolated_orm_probes.log`. 실제 권한별 결과가 나오기 전에는 일반 담당자 우회 성공을 이 admin/superuser 로그만으로 확정하지 않는다. 소스 ACL상 일반 담당자에게 관련 write/create 권한이 있는 사실은 별도 확인했다.

## 남은 재현 경로와 코드 근거

### 1. [P1] 완료된 부모에 새 라인을 넣거나 draft 라인을 옮길 수 있음 — Q10

두 라인 모델의 `write`는 **현재** `check_id/record_id.state`만 검사한다. `create` override는 두 모델에 없다. 따라서 다음 입력은 완료 기록을 작성 중으로 돌리지 않고 내용/종합판정을 변경하는 경로다.

```python
# 기존 chk가 완료이고 정상 판정 1개를 가졌다고 가정
env['iatf.mold.check.line'].create({'check_id': chk.id, 'item_name': '추가 미판정 항목'})
# 또는 draft 부모에 있던 line을 완료 부모로 이동
draft_line.write({'check_id': chk.id})
# 범용 시트는 모델 iatf.check.record.line, 필드 record_id로 같은 입력
```

기대 관찰: 완료 부모에 미판정 라인이 들어가 `overall_result='pending'`이 되어도 `state='done'`이 유지된다. `line.create/write`가 부모의 `@api.constrains('state','line_ids')`를 호출하지 않으며, 부모 전체의 완결성을 라인 create/write 후 다시 확인하지 않는다. 과거 증빙의 항목 변경 자체도 이미 잠금 위반이다.

근거:

- `iatf_mold/models/mold_check.py:266–273`: 라인 write 현재 부모만 검사. `:162–297` 클래스에 create 없음.
- `iatf_work_environment/models/check_sheet.py:706–718`: 같은 검사. `:597–735` 라인 클래스에 create 없음.
- 완료 부모 guard는 `mold_check.py:124–134`, `check_sheet.py:565–576`.
- 고정 core `odoo/models.py:1622–1631`: 현재 모델에 전달된 field_names와 constraint 필드가 겹칠 때만 호출.
- 일반 담당자에게 라인 create/write 권한: 금형 ACL `security/ir.model.access.csv:10`, 범용 ACL `:14`.
- 독립 모의: 두 모델 모두 `draft_line_reparent_to_done='allowed'`, create guard 부재 확인. 실제 ORM `done_line_create:*`, `done_line_reparent:*`에서도 두 모델 모두 성공하여 완료 상태/pending/라인2개가 저장됨.

### 2. [P1] `state`와 저장 계산 결과를 함께 쓰면 완료 백스톱 우회 — Q10

`overall_result`가 `compute, store=True`인 것만으로 서버 쓰기 금지가 되지 않는다. draft 헤더에는 새 write 잠금도 걸리지 않는다. 완료 constraint는 실제 라인 목록/판정을 다시 검사하지 않고 저장된 `overall_result`만 신뢰한다.

```python
# 라인 판정이 False인 draft 기록, 정상 계산 결과 pending
rec.write({'state': 'done', 'overall_result': 'ok'})
```

라인 dependency를 변경하지 않고 종합판정과 상태만 같이 쓰는 경우 미판정 라인이 있는 완료 증빙을 만들 수 있다. 이를 차단하는 constraint/필드 입력 제거/서버 write 금지가 없다.

근거:

- 금형: 계산 필드 `mold_check.py:54–60`, 계산 dependency `:69`, write 가드 `:100–107`, 완료 검사 `:132`.
- 범용: `check_sheet.py:484–489`, dependency `:494`, write `:556–563`, 완료 검사 `:574`.
- 고정 core `odoo/fields.py:155–158`: readonly는 UI에만 영향, stored 또는 inverse가 있는 필드는 코드 대입 가능함을 명시.
- 고정 core `odoo/models.py:4736–4741,4801–4802,4817–4826`: 전달값을 field.write하고 전달 필드 기반으로 constraint 수행.
- 독립 모의: 단순 `state=done`은 두 모델 모두 차단, 위 입력은 둘 다 허용되어 최종 `[done,ok]`. 실제 ORM `forged_done:*`에서도 두 모델 모두 미판정 라인 `[False]`를 가진 `[done,ok]` 상태가 저장됨.

추가 테스트 `test_mold_check.py:277–282`는 state만 쓰는 경우만 확인하며 이 조합을 테스트하지 않는다.

### 3. [P1] 완료 헤더 삭제는 라인 잠금을 건너뛰어 증빙 전체를 없앰 — Q10

두 헤더 모델은 `unlink` override가 없다. 관리자는 헤더 삭제 권한이 있고 라인의 부모 FK는 cascade다. 부모가 삭제될 때 DB cascade는 라인의 Python `unlink()` guard가 아니다. MailThread 기본 unlink는 관련 메시지도 지운다.

```python
done_record.unlink()  # 해당 모듈 관리자 사용자
```

근거:

- `mold_check.py:174–176`, `check_sheet.py:602–603`: 부모 FK `ondelete='cascade'`.
- 금형 ACL `:9`, 범용 ACL `:13`: manager perm_unlink=1.
- 고정 core `addons/mail/models/mail_thread.py:348–363`: 메시지/팔로워 삭제와 super unlink.
- 기존 추가 테스트는 라인 unlink만 테스트: 금형 `test_mold_check.py:302–303`, 범용 `test_check_sheet.py:305–306`.
- AST 구조상 헤더 unlink guard 부재. 실제 ORM `done_header_unlink:*`에서 두 모델 모두 `record_survives=false`, `line_survives=false` 확인. 비슈퍼유저 모듈 관리자 권한 재현은 별도 role probe 대상.

### 4. [P1] 온도 스냅샷/판정 서버 쓰기와 재스냅샷 경로 — Q11

신규 온도기록 생성 시 60~90 기준, 95℃이면 `ng`; 마스터 상한을 100으로 바꾸는 **마스터 단독 변경**에 과거 결과가 ng로 유지되는 수정은 적절하다. 하지만 온도 로그에는 write/constraint가 전혀 없고 일반 담당자에게 write 권한이 있다.

```python
log.write({'spec_result': 'ok'})  # 95℃, 상한 90 유지한 채 합부만 위조
log.write({'spec_max': 100.0})    # 판정 근거 자체를 변경
# 다른 재스냅샷 경로
mold.write({'preheat_temp_max': 100.0})
log.write({'mold_id': mold.id})  # 같은 ID 재전달만으로 과거 상한90/ng가 100/ok로 변함
```

마스터나 측정 구분을 정말 변경할 경우 기준을 다시 읽도록 의도되어 있어 `log_type` 왕복도 기존 측정 날짜/측정값을 유지한 채 기준을 바꿀 수 있다. 추가 실제 ORM probe에서 같은 ID 재전달만으로도 과거 기준과 판정이 바뀌는 것을 확인했다.

근거:

- `mold_temp_log.py:58–65`: 저장 계산 필드 정의.
- `:90–95`: mold_id/log_type dependency에 매번 현재 마스터 복사.
- `:99–104`: 변경된 snapshot에서 결과 재계산.
- 전체 클래스 `:9–130`: write/constraint 없음.
- `iatf_mold/security/ir.model.access.csv:12`: 일반 담당자 write=1.
- 독립 모의: 최초 `[60,90,ng]`, master-only `[60,90,ng,current=ok]`, snapshot compute 재호출 시 `[60,100,ok]`. 직접 write 가능성은 고정 core의 stored readonly 의미론으로 확인.
- 신규 테스트 `test_mold_temp_log.py:68–91`는 master-only 변화/개정 뒤 신규 입력만 확인. API snapshot/result 입력, 동일 mold_id 재전달, 업그레이드 전 데이터는 검사하지 않는다.
- 실제 ORM `temperature_direct_write`에서 상한90/측정95를 유지한 채 spec_result=ok 변경을 확인했고, `temperature_same_mold_write`에서 상한90/ng→100/ok 재스냅샷을 확인했다. 두 우회 모두 로그에 flush 후 다시 읽은 결과가 있다.

기존 데이터 주의: 이전 spec_min/spec_max는 비저장이고 수정판은 저장이다. 새 컬럼 초기화 시 현재 마스터를 기준으로 계산하는 것이지 측정 당시 기준 복원이 아니다. 금형 모듈에는 별도 migration/provenance 필드가 없다. 기존 실적에 “측정 당시 스냅샷” 표기가 정확한지 업그레이드 데이터 검증이 필요하다. 증거 수준은 소스 구조이며 이번 단계에서 실제 기존 DB 업그레이드를 실행한 것은 아니다.

추가 유지보수 사실: `mold.py:233–248`에 judge_temp를 추가했지만 `check_temp_in_spec` `:250–267`은 여전히 직접 비교를 복제한다. `CLAUDE.md`의 “단일 판정 구현” 및 코드 주석과 다르다. 현재 두 비교식 결과는 같으므로 당장 별도 판정 오류로 계산하지 않는다.

### 5. [P2 / 제외 정책 확인] `no_value + na`가 종합 양호/완료로 집계됨 — Q12

```python
# 두 모델의 라인에서 같은 입력
{'item_name': '수치항목', 'spec_min': 0.0, 'spec_max': 20.0,
 'value': 0.0, 'result': 'na'}
rec.action_done()
```

`no_value`에서 금지하는 result는 ok/ng뿐이다. na는 남는다. 종합판정은 미판정(False)과 ng만 제외하고 나머지를 전부 ok로 처리한다. “수치 기준이 있는 항목은 측정 없이 판정하지 못함”이라는 보완 취지에 비해 na 우회가 남아 있다. na를 허용할 업무상 근거/승인/제외집계는 구현되어 있지 않다. 범용 시트의 항목별 최근 실시일 역시 result가 truthy면 완료 실적으로 센다(`check_sheet.py:343–350`).

근거:

- 금형 `mold_check.py:259–264`, 범용 `check_sheet.py:691–696`: ok/ng만 금지.
- 금형 `mold_check.py:69–80`, 범용 `check_sheet.py:494–505`: na도 종합 ok.
- 독립 모의: baseline/quality, 두 모델 모두 value=0+na 허용, overall=ok, action_done 허용.
- 실제 ORM `missing_value_na:*`에서 두 모델 모두 value=0, judged=no_value, result=na, overall=ok, state=done을 확인했다.

유효한 실측 0의 구분 문제도 그대로다. 예를 들어 재생재 배합비율 0%는 상한 20%의 유효 측정일 수 있지만 `not self.value`가 미입력으로 처리한다(`mold_check.py:203–214`, `check_sheet.py:638–649`). 수정판에서 이를 ok로 수동 보정하려 하면 오히려 새 constraint가 막는다. 측정여부 플래그 등 0과 미입력을 분리할 구조가 필요하며, 정량 항목을 정성으로 바꾸라는 주석(`mold_check.py:206–208`)은 수치 증빙을 대체하지 못한다.

### 6. [P2] draft 정정의 chatter 추적은 context로 생략 가능 — Q10

draft 복귀를 허용하는 것 자체는 `CLAUDE.md`의 명시된 정정 절차다. 다만 “상태 변경은 chatter에 남는다”는 근거는 모든 API 경로에서 보장되지 않는다.

```python
r = rec.with_context(tracking_disable=True)
r.action_draft()
r.line_ids[0].write({'value': 12.0})
r.action_done()
```

모듈에서 tracking_disable/mail_notrack context를 무시하거나 별도 정정이력을 강제하지 않는다. 금형 `mold_check.py:155–156`, 범용 `check_sheet.py:590–591`은 단순 state write다. 고정 core `addons/mail/models/mail_thread.py:333–344`는 tracking_disable이면 추적 기능 없이 super write하고 mail_notrack이면 _track_prepare를 건너뛴다. 일반 담당자도 헤더/라인 write를 할 수 있다. 현재 테스트는 state round-trip만 검사하고 실제 chatter 생성 여부를 assertion하지 않는다(금형 `test_mold_check.py:304–310`, 범용 `test_check_sheet.py:307–311`). 실제 ORM chatter 재현은 아직 실행하지 않았으므로 source-confirmed 경로로 구분한다.

또한 헤더 write 가드는 done을 유지할 때만 금지하므로 `{'state':'cancelled','check_date':과거일}`도 함께 허용한다. 취소 실적은 완료 집계에서 빠지므로 이를 별도 허위 완료 우회로 과장하지 않지만, “먼저 작성 중으로”라는 오류문구와 허용 경로는 일치하지 않는다.

### 7. [P2] migration marker 수정의 버전 위치 및 과거 기준 추정 표시 — H14

baseline 모듈 버전은 18.0.1.3.0, quality는 18.0.1.3.1이다. 수정한 migration 파일 위치는 여전히 `migrations/18.0.1.3.0/post-migration.py`다. Odoo는 `installed_version < script_version <= current_version`일 때 실행하므로 이미 1.3.0이 설치된 DB는 이번 1.3.1 업그레이드에서 수정된 script를 실행하지 않는다.

근거:

- 양쪽 `iatf_work_environment/__manifest__.py:3`.
- 고정 core `odoo/modules/migration.py:199–220`, 특히 `:216` strict inequality.
- 버전 부등식 모의: `(18,0,1,3,0) < (18,0,1,3,0) <= (18,0,1,3,1)`은 False.

이번 marker는 새 수정판 script가 한 번 실제로 실행된 뒤 재호출되는 경우에만 라인 backfill을 건너뛴다. Cursor mock으로 실제 migration 함수를 실행해 첫 실행은 라인 UPDATE/marker INSERT를 호출하고, marker 존재 상태의 재실행은 앞의 1~4 작업과 marker SELECT만 수행하는 것을 확인했다. SQL 자체를 DB에 실행한 검증은 아니다.

추가 인메모리 SQL 재현: 구판 migration 1회 실행 → 현재 기준 item의 is_key_item을 False에서 True로 변경 → 수정판 script 최초 재호출 시 과거 정성 실적 라인의 is_key_item이 False에서 True로 다시 복사되었다(구판은 marker를 만들지 않음). 그 뒤 master를 False로 바꾸고 수정판을 두 번째 호출하면 marker가 있어 True가 보존된다. 즉 수정판끼리 반복 호출은 막지만 **이미 구판으로 이관된 실적의 첫 수정판 재호출**을 보호하지 않는다. 이는 명시적 script 재호출 입력에 대한 결과이며, 위의 version gate 때문에 1.3.0→1.3.1 정규 업그레이드에서 자동 발생한다고 주장하지 않는다.

당시 기준 복원이 아니라 현재 기준을 추정 복사하는 점은 `post-migration.py:46–51` 주석에 명시되었다. 그러나 실제 SQL은 여전히 현재 item에서 `spec_mode/entry_type/target_value/tolerance/is_key_item`을 기존 실적에 넣으며(`:61–79`), 기록별 “이관 추정” 표시나 이관시각·원본값 보존은 없다. `:36–37`은 “3번에서 전부 1로 맞춰 정확”하다고 하지만 3번은 revision=0/NULL인 시트만 1로 바꾸므로 기존 양수 revision은 1이 아닐 수 있다. 이 주석 정정과 사용자에게 보이는 provenance 확인이 필요하다.

## 테스트 대조 결론

추가 테스트가 실제로 주장하는 범위는 작동 변경과 일치한다: 금형 미래일 생성 거절, state-only 완료 거절, no_value+ok 거절, 완료 후 날짜/value/라인 삭제 거절, 정상 draft round-trip, 온도 master-only 스냅샷 유지 및 신규 기준 반영. 따라서 변경이 전혀 효과 없다고 볼 수는 없다.

하지만 위 1~7 경로는 해당 추가 테스트로 커버되지 않는다. “156건 통과”가 확인되더라도 완전 해결의 충분조건은 아니며, 신규·기존 데이터 및 API 우회 입력에 대한 독립 검증이 필요하다. 현재 판정은 Q10/Q11/Q12/H14 모두 부분해결이고, 단일 신규 미래일 차단만 별도로 해결됨으로 분류한다.


## 일반 담당자·모듈 관리자 권한 후속 확인 (아스트라 통합 검토)

`mold_role_orm_followup_results.json` / `isolated_orm_followup.log`의 7개 관찰을 확인했다. 앞선 12개 관찰 중 주요 경로를 권한별로 다시 확인한 것이며 별개 결함 7개로 더하지 않는다. 모든 실제 대상 조작은 `su=False`, 시스템 설정 관리자 아님인 사용자로 실행했다.

- 금형·범용 **일반 담당자**: 완료 부모에 라인 추가 각 1건, 미판정 기록의 state/overall_result 동시 입력 각 1건이 허용됐다.
- 금형 **일반 담당자**: 온도 95/상한90의 ng를 결과 직접 입력으로 ok로 바꾸고 기준 상한도100으로 바꿀 수 있었다.
- 금형·범용 **모듈 관리자**: 완료 헤더 삭제 각1건에서 헤더·라인 모두 사라졌다.

따라서 이 7개 관찰은 superuser 권한 때문에만 발생한 결과가 아니다. ORM 호출을 이용한 서버 검증이며 화면 클릭·HTTP 인증 경로의 재현으로 표현하지 않는다. 측정값0+na·동일금형 재입력·라인 이동의 권한별 재실행은 별도 수행하지 않았고 초기 ORM 및 ACL 소스 근거로 구분한다.


통합 검토 판단 보완: `na` 자체는 정당한 해당없음 처리일 수 있으므로 이 입력을 항상 결함이라고 단정하지 않는다. R04는 미측정과 업무상 제외의 구분·증빙 정책 확인으로 P2에 분류한다. 실제 측정0과 미입력의 구분 문제는 별도로 남는다.
