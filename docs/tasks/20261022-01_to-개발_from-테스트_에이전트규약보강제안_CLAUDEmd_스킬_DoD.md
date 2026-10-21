# 에이전트 규약 보강 — **합의본 v2** (claude-test ↔ claude-development, 2026-10-22)

v1(테스트 초안 078) + 개발 검토(079) 반영. 상위 문서: handoff `00 HANDOFF §8–§11`, `03 절차서 §9`
(대표 지시 — 코드 개발은 원도영 측 전담, **정본은 escon-odoo/odoo_gh 선언 2026-10-19**, 원복 지점 표).
이 규약은 세션 간 작업 방식이며 상위 문서와 충돌하면 상위 문서를 따른다.

## 0. 현황 (실측 2026-10-22, 079 정정 반영)

| 항목 | 현황 |
|---|---|
| `~/cams-odoo/CLAUDE.md` | 토폴로지·정본/미러·절대 규칙·서버 차이. **개발 규약·검증 명령·완료 기준 없음** |
| `~/cams-odoo/AGENTS.md` | CLAUDE.md 8월 구버전 부분 복사(드리프트) |
| `~/cams-odoo/.claude/` | 빈 디렉터리(스킬·훅 0) |
| `railway-uat/` (98모듈) | **CLAUDE.md 없음**. 지위: 2026-10-19 부터 **검증 참조 트리**(UAT 수정분 중 BOM 보호 3.0.0 만 운영 미이전) |
| 모듈 규약 준수(98) | license 98/98 LGPL-3 · depends 98/98 · `ast.literal_eval` 98/98 통과 · 보안 CSV 82/86 · tests 45/98 |
| 린트/pre-commit | 없음 |

- v1 의 "manifest 깨진 1건" 은 **측정 스크립트가 줄을 이어 붙인 오류**였다. 수정 대상 없음.
  측정은 `ast.literal_eval` 로 한다.
- 모듈 구조(models/views/security/static, `_description`, access CSV)는 이미 준수. 빈 곳은
  **에이전트가 읽을 규약·검증 절차·완료 기준**이다.
- **ECC(Everything Claude Code) 통째 설치는 보류**(합의). 제3자 스킬·훅이 에이전트 설정에 들어오고
  `OEEL-1` 권고처럼 틀린 지침이 섞여 있다. 아이디어만 우리 식으로.

---

## ① `~/cams-odoo/CLAUDE.md` 추가 절 — 합의본

```markdown
## 개발 규약 (커스텀 애드온 — 정본 escon-odoo/odoo_gh, 검증 참조 railway-uat)

### 모듈 골격·manifest
- 디렉터리: `models/ views/ security/ data/ wizards/ tests/ static/src/ README.md`
- `__manifest__.py` 필수: `license: LGPL-3`(Enterprise 확장이어도 OEEL 아님),
  `version: 18.0.x.y.z` — **동작이 바뀌면 반드시 올린다**(`-u` 판단 근거),
  `depends` 는 실제 import/상속 모듈 전부. manifest 검사는 `ast.literal_eval` 로.
- 새 모델 = `security/ir.model.access.csv` 행 필수. 회사 분리 모델은 `_check_company_auto = True`.
- required 필드를 **제거**할 때는 NOT NULL 컬럼이 남는다 → `pre_init`/`post_init` 에서 nullable 처리
  (안 하면 운영 업그레이드 후 신규 insert 전부 실패).

### Odoo 18 에서 실제로 부딪힌 규칙 (지키지 않으면 운영에서 막힌다)
1. `_` 로 시작하는 메서드는 RPC·버튼에서 못 부른다("Private methods cannot be called remotely").
   외부에서 써야 하면 `action_*` 또는 위저드 진입점을 둔다. **테스트 코드도 공개 경로로 부른다.**
   (예: `br.intake.link_delivery(picking)` → `br.intake.delivery.wizard`, `sale.order._create_invoices` → `sale.advance.payment.inv`)
2. 게이트/가드는 **진입 지점**에서 거부한다. 검사·기록을 다 만든 뒤 마지막에 실패하면
   MQTT 처럼 예외를 삼키는 호출자에게 "합격" 흔적이 남는다. (조립 위저드 2대 MO 사례)
3. 완료 메시지는 **부수 상태**를 드러낸다 — "MO done" 인데 완제품 LOT 이 품질 보류면 결과에 쓴다.
4. 증빙 원장이 둘이면(`ej.check.model` ↔ `mrp.bom.scan.guard.log`) 쓰는 쪽은 둘 다 쓴다.
5. 동시성: advisory lock 만으로도, **멱등 가드(스냅샷 비교)만으로도** 동시 중복 발행된다 —
   REPEATABLE READ 에서 둘 다 '없음' 을 본다. 대상 행 `UPDATE … SET write_date = write_date` 로
   직렬화한다(`scm_no_po_scope_lock`, `_approval_lock_target` 패턴).
6. 재실행은 멱등만으론 부족 — **사람 입력 보존**(재계산이 수동 조정 라인을 지우지 않음)까지가 완료 조건.
   계획 재계산이 '초안으로' 를 거치는 이유.
7. 승인 흐름: `_approve_user` 는 지정 결재자 본인만. 검사자≠결재자 강제 모델(출하검사·포장라벨)이
   있다 → fixture 도 두 사용자로. 결재 가드(`approval_guard._validate_approvers`)는 **승인자에게
   대상 문서 write 권한**을 요구한다 → 새 결재 모델을 붙이면 승인자 그룹 묶음도 같이 갱신.
8. 스냅숏을 동결하는 설계(정산 BOM 스냅숏 등)는 **보류 복구 경로**를 같이 만든다.
9. 사람이 고치는 기준(점검표·검사 기준)은 **개정 차수 + 완료 스냅샷 + 이력 불변** 3종이 같이 간다
   (`check.sheet.revision`/`check.record.snapshot` 패턴). 출하 판정은 1회 스냅샷, 정정은 새 검사.
10. 필수 경로의 `message_post` 는 작성자 이메일이 없으면 UserError 로 **동작 전체가 막힌다** →
    `_message_log` 를 쓰거나 이메일 없으면 건너뛴다(운영 `escon_ceo` 해당).
11. 디버그 전용 쓰기 가드가 **설정 필드까지 덮지 않게** 한다(SILO 재주문점 사례, D9).
12. 부분 이식(격리→검증 트리) 전 `odoo.addons` import 참조·설치 의존 닫힘 검사(사고 2건).

### 검증 (격리 클론 또는 운영 서버 시험 DB 8070/8071 — 운영 DB·공유 Railway 쓰기 금지)
- 로컬 러너: `work/overnight/claude-test/tools/week_test_shell_runtime.py`
  (`--db <클론> --modules <m> --test-tags <t> --install/--no-test --serve`)
- 모듈 변경 → `-u <module>` + 해당 tests 통과 → 결과 로그 경로를 회신에 남긴다.
- 테스트 결과는 `odoo.tests.result: … of N tests` 줄로 센다(`--log-level=warn` 은 이름을 숨긴다).
- 시각은 `date` 실측만. 추정 시각·가짜 로그 접미사 금지.

### 완료 기준 (Definition of Done)
1. 코드 + manifest 버전 올림
2. **격리 클론 또는 서버 시험 DB** 에서 `-u` 성공 + 테스트 통과(로그 경로)
3. 새 모델이면 access CSV, 새 가드면 테스트
4. **서버 작업본 ↔ odoo_gh 정본 차이** 확인(03 절차서 §9 원복 지점 표) — 정본 선언 뒤로 "미러 드리프트" 가 아니다
5. 큐 회신: 측정값·막힌 지점·바꾼 데이터 목록·**원복 지점(SHA·백업 덤프) 한 줄**.
   완료 선언 전 **원격 존재 확인**(`git ls-remote` + 원격 심볼 grep — 로컬 커밋 ≠ 인계).
   운영 반영은 **대표 승인 후 원도영 세션(서버)**. 총괄은 사양·검토·판정만.

### 비밀·Enterprise
- `.secret`·`.env`·API 키·덤프·Enterprise 소스는 Git·공용 큐·로그에 넣지 않는다. pre-commit 가드(④)로 막는다.
```

---

## ② `railway-uat/CLAUDE.md` 신설 — 합의본 (deploy/start.py 266d51d 기준)

```markdown
# CAMS Odoo UAT (Railway) — CLAUDE.md

## 지위 (2026-10-19 이후)
- 정본은 **escon-odoo/odoo_gh**. 개발·시험은 원도영 운영 서버(시험 DB 8070/8071)로 이동.
- 이 트리는 **검증 참조 트리**다. UAT 수정분 중 BOM 보호 3.0.0 만 운영 미이전. 00 HANDOFF §8–§11, 03 절차서 §9.

## 무엇인가
- Railway `odoo-uat` / 서비스 `odoo` / DB `railway_master` / https://odoo-production-beb1.up.railway.app
- 로그인 `uat`(비밀번호 `work/uat-password.secret` — 절대 출력·커밋 금지). 팀 계정 `*.uat` 11종.
- **공유 환경.** 쓰기 전 큐 선통지, 진행 중 트랜잭션 확인 후 배포.

## 배포 기전 (틀리면 재시작 루프)
- push → 빌드 → `deploy/start.py`. **재시작마다** 실행(60–71행): `UAT_KEEP_LOGINS` 외 내부 사용자 전원 비활성 →
  admin 을 `uat` 로 재설정 → **ir_cron 전체 비활성, ir_mail_server 비활성, outgoing 메일 cancel.**
  → **문서만 push 해도 재배포(약 50초 502) + 이 초기화가 다시 돈다.**
- `UAT_INSTALL_MODULES`(`-i`) / `UAT_UPDATE_MODULES`(`-u`) 가드 키 `uat.install_applied`/`uat.update_applied`
  의 값은 **모듈 목록 문자열** — 같은 목록이면 skip, 목록이 바뀌면 다시 실행("같은 목록 1회").
- `subprocess.run(check=True)`: `-i` 실패·seed 복원(`pg_restore --exit-on-error --single-transaction`) 실패 = 루프.
  설치 전 의존성 사전검사(읽기 전용 XML-RPC 로 depends 설치 여부·BLOCKERS) 필수.
- 확인: `railway deployment list` + `/web/health` 200 복귀 시각 기록.
- `max_cron_threads = 0` + 크론 전체 비활성 — 스냅숏(협력사 예측 등)은 손으로 호출해야 갱신된다.

## 작업 규칙
- 공용 마스터데이터(거래처 계정·결재 템플릿·supplierinfo·잠금일)를 바꾸면 회신에 **전/후 목록**을 남긴다.
- 시험값(검사 측정값·공급사 주장 수량)은 레코드에 "시험값" 을 명시한다.
- 품질 보류·결재·동결 스냅숏은 증빙 없이 풀지 않는다. 막히면 그 지점 그대로 보고.
- 회계 기본값이 틀려 있다(거래처 지급계정 `610005`, 분류 재고입고 `211002`) — 운영 `odoo18` 과 별개.

## 알려진 함정
- 완제품 serial 추적 MO 수동 완료는 **1대 단위**만(본체 `_auto_production_checks`).
- BR 조립은 `is_jr` 을 초안에서 세워야 위저드 대상(escon_br_intake 1.0.1 이후 자동).
- `qty_available` 은 IQC 격리 위치를 포함 — 가용 재고는 `WH/재고` quant 로 본다.
- IQC 격리 위치는 입고 전표마다 자동 생성(`WH/IQC 검사대기/<전표명>`)되며 지우지 않는다.
- 포털 거래처는 `supplier_portal_company_ids` 없으면 토큰이 유효해도 Access Denied.
```

---

## ③ `.claude/skills` 3종 (우리 반복 작업)

| 스킬 | 하는 일 |
|---|---|
| `uat-precheck` | `-i`/`-u` 전 depends·BLOCKERS 읽기 전용 검사 → 결과표 |
| `clone-verify` | 러너 래퍼: 클론 복원 → `-u` → tests → 로그 경로 회신 양식 |
| `queue-reply` | 큐 회신 양식 + 번호 규칙 |

**큐 번호 규칙(합의)**: claude-development = **홀수**, claude-test = **짝수**, codex = 900번대.
날짜가 바뀌어도 번호는 이어 간다. 같은 번호 재사용 금지. (079 개발 → 080 테스트부터 적용)

## ④ pre-commit 가드 (AgentShield 대신) — railway-uat·odoo_gh(문서 브랜치 포함) 양쪽 동일 훅
- 차단 패턴: `enterprise/` 경로, `*.secret`(`uat-password.secret`, `prod-test-accounts.secret` 포함), `.env`,
  `*.dump`/`*.sql`, `sk-`/`Bearer `/`opstest` 토큰 류.
- 도구는 `pre-commit` + 자체 셸 훅. 제3자 스캐너 불필요.

## ⑤ 정리
- `AGENTS.md` → "CLAUDE.md 를 본다" 한 줄로 축소.
- manifest 수정 대상 **없음**(v1 오류 정정).

---

## 분업 (합의)
- **claude-test**: ①을 `~/cams-odoo/CLAUDE.md` 에 적용, `AGENTS.md` 축소, ③ 스킬 초안. 로컬 attachments + handoff 에 v2 게시.
- **claude-development(총괄)**: ② `railway-uat/CLAUDE.md`·④ pre-commit·⑤ 적용. railway-uat push 는
  **다음 기능 배포와 묶어 1회**(재배포 + 사용자 비활성 재적용 유발), 큐 선통지. 지금 예정 배포 없음 → v2 확정 후 날을 잡는다.
- 적용 결과 SHA 를 큐로 교환.
