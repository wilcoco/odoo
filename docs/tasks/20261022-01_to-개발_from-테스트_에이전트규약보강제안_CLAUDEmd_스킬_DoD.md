# 에이전트 규약 보강 제안 — 초안 v1 (claude-test, 2026-10-22)

사용자 지시: ECC(Everything Claude Code) 온보딩 자료를 읽고 "우리가 빠뜨린 것"을 찾아
**다른 세션과 합의한 뒤 같이 적용**하라. 아래는 합의용 초안이다. 측정값은 2026-10-22 실측.

## 0. 현황 (실측)

| 항목 | 현황 |
|---|---|
| `~/cams-odoo/CLAUDE.md` | 7.1KB — 운영 토폴로지·정본→미러·절대 규칙·서버 차이. **코딩 규약·검증 명령·완료 기준 없음** |
| `~/cams-odoo/AGENTS.md` | CLAUDE.md 의 8월 구버전 부분 복사(드리프트) |
| `~/cams-odoo/.claude/` | 빈 디렉터리(스킬·훅 0) |
| `railway-uat/` (실제 개발 트리, 98모듈) | **CLAUDE.md·AGENTS.md 없음** |
| 모듈 규약 준수(98) | license 98/98(LGPL-3, 1건 manifest 깨짐) · 보안 CSV 82/86 · tests 45/98 · OWL 19 · 문서 29 |
| 린트/pre-commit | 없음 |

ECC 가 말하는 모듈 구조(models/views/security/static, `_description`, access CSV)는 **이미 지켜지고
있다.** 빈 곳은 구조가 아니라 **에이전트가 읽을 규약·검증 절차·완료 기준**이다.

**ECC 채택 여부**: 통째 설치는 보류 제안. 제3자 스킬·훅이 에이전트 설정에 들어오는 것이고,
`OEEL-1` 라이선스 권고처럼 틀린 지침도 섞여 있다(우리 커스텀 모듈은 LGPL-3 이 맞다).
아이디어만 우리 식으로 가져온다.

---

## ① `~/cams-odoo/CLAUDE.md` 에 추가할 절 — 초안

```markdown
## 개발 규약 (커스텀 애드온 — 정본 addons_custom / 미러 iatf_plugins / UAT addons)

### 모듈 골격·manifest
- 디렉터리: `models/ views/ security/ data/ wizards/ tests/ static/src/ README.md`
- `__manifest__.py` 필수: `license: LGPL-3`(Enterprise 확장이어도 OEEL 아님),
  `version: 18.0.x.y.z` — **동작이 바뀌면 반드시 올린다**(`-u` 판단 근거),
  `depends` 는 실제 import/상속 모듈 전부.
- 새 모델 = `security/ir.model.access.csv` 행 필수. 회사 분리 모델은 `_check_company_auto = True`.

### Odoo 18 에서 실제로 부딪힌 규칙 (지키지 않으면 운영에서 막힌다)
- `_` 로 시작하는 메서드는 RPC·버튼에서 못 부른다. 외부에서 써야 하면 `action_*` 또는
  위저드 진입점을 둔다. (예: `br.intake.link_delivery(picking)` 은 레코드셋 인자라
  RPC 불가 → `br.intake.delivery.wizard` 가 공개 경로)
- 게이트/가드는 **진입 지점**에서 거부한다. 검사·기록을 다 만든 뒤 마지막에 실패하면
  MQTT 처럼 예외를 삼키는 호출자에게 "합격" 흔적이 남는다. (조립 위저드 2대 MO 사례)
- 완료 메시지는 **부수 상태**를 드러낸다 — "MO done" 인데 완제품 LOT 이 품질 보류면
  그걸 결과에 쓴다. (BR 조립 보류 사례)
- 증빙 원장이 둘이면(예: `ej.check.model` ↔ `mrp.bom.scan.guard.log`) 쓰는 쪽은 둘 다 쓴다.
- 동시성 가드는 advisory lock 만으로 안 된다. **행 UPDATE** 로 REPEATABLE READ 를 깨운다
  (`UPDATE … SET write_date = write_date` 패턴, `scm_no_po_scope_lock`).
- 승인 흐름: `_approve_user` 는 지정 결재자 본인만. 검사자≠결재자 강제 모델이 있다
  (출하검사·포장라벨). 테스트 fixture 도 두 사용자로 짠다.
- 스냅숏을 동결하는 설계(정산 BOM 스냅숏 등)는 **보류 복구 경로**를 같이 만든다.

### 검증 (로컬·클론 전용 — 운영·공유 Railway 쓰기 금지)
- 러너: `work/overnight/claude-test/tools/week_test_shell_runtime.py`
  (`--db <클론> --modules <m> --test-tags <t> --install/--no-test --serve`)
- 모듈 변경 → 클론 DB 에서 `-u <module>` + 해당 tests 통과 → 결과 로그 경로를 회신에 남긴다.
- 테스트 결과는 `odoo.tests.result: … of N tests` 줄로 센다(`--log-level=warn` 은 이름을 숨긴다).
- 시각은 `date` 실측만 쓴다. 추정 시각·가짜 로그 접미사 금지.

### 완료 기준 (Definition of Done)
1. 코드 + manifest 버전 올림
2. 클론 DB `-u` 성공 + 테스트 통과(로그 경로)
3. 새 모델이면 access CSV, 새 가드면 테스트
4. `scripts/mirror_diff.sh --fetch` 로 미러 드리프트 확인
5. 큐 회신(측정값·막힌 지점·바꾼 데이터 목록). 운영 반영은 서버 담당 몫.

### 비밀·Enterprise
- `.secret`·`.env`·API 키·덤프·Enterprise 소스는 Git·공용 큐·로그에 넣지 않는다.
- pre-commit 가드(아래 ④)로 기계적으로 막는다.
```

---

## ② `railway-uat/CLAUDE.md` 신설 — 초안

```markdown
# CAMS Odoo UAT (Railway) — CLAUDE.md

## 무엇인가
- Railway 프로젝트 `odoo-uat` / 서비스 `odoo` / DB `railway_master`
- URL https://odoo-production-beb1.up.railway.app — 로그인 `uat`(비밀번호는 `work/uat-password.secret`, 절대 출력 금지)
- 팀 계정: plan/prod.lead/injection/assembly/material/quality/quality.lead/account/approver/bom_* (.uat)
- **공유 환경이다.** 쓰기 전 큐로 선통지, 진행 중 트랜잭션 확인 후 배포.

## 배포 기전 (틀리면 재시작 루프)
- push → Railway 빌드 → `deploy/start.py` 가 `UAT_INSTALL_MODULES`(`-i`, 1회 가드 `uat.install_applied`)
  / `UAT_UPDATE_MODULES`(`-u`, 가드 `uat.update_applied`) 를 실행한다.
- `subprocess.run(check=True)` 라 **`-i` 실패 = 컨테이너 재시작 루프.** 설치 전 의존성 사전검사
  (읽기 전용 XML-RPC 로 depends 설치 여부·BLOCKERS 확인) 필수.
- 배포 중단 약 50초(health 502). 확인: `railway deployment list` + `/web/health` 200 복귀 시각 기록.
- `max_cron_threads = 0`, **크론 57개 전부 비활성** — 스냅숏(협력사 예측 등)은 손으로 호출해야 갱신된다.

## 작업 규칙
- 운영 DB 아님. 그러나 **공용 마스터데이터**(거래처 계정·결재 템플릿·supplierinfo·잠금일)를 바꾸면
  큐 회신에 "전/후 목록" 을 남겨 되돌릴 수 있게 한다.
- 시험값(검사 측정값·공급사 주장 수량)은 레코드에 "시험값" 을 명시한다.
- 품질 보류·결재·동결 스냅숏은 증빙 없이 풀지 않는다. 막히면 그 지점 그대로 보고.
- 회계 마스터 기본값이 틀려 있다(거래처 지급계정 `610005`, 분류 재고입고 `211002`) — 운영 `odoo18` 과 별개.

## 알려진 함정
- 완제품 serial 추적 MO 는 수동 완료 **1대 단위**만(본체 `_auto_production_checks`).
- BR 조립은 `is_jr` 을 초안에서 세워야 위저드 대상(1.0.1 이후 자동).
- `qty_available` 은 IQC 격리 위치를 포함한다 — 가용 재고는 `WH/재고` quant 로 본다.
```

---

## ③ `.claude/skills` 후보 (우리 반복 작업)

| 스킬 | 하는 일 |
|---|---|
| `uat-precheck` | `-i`/`-u` 전 depends·BLOCKERS 읽기 전용 검사 → 결과표 |
| `clone-verify` | 러너 래퍼: 클론 복원 → `-u` → tests → 로그 경로 회신 양식 |
| `queue-reply` | 큐 회신 양식 + **번호 발급 규칙**(아래) |

**번호 충돌 방지 규칙(합의 필요)**: 이번에 063·069 두 번 겹쳤다. 제안 — 역할 접두사
(`D-###` 개발 / `T-###` 테스트) 또는 짝수/홀수 분리.

## ④ pre-commit 가드 (AgentShield 대신)
- 차단 패턴: `enterprise/` 경로, `*.secret`, `.env`, `*.dump`/`*.sql`, `sk-`/`Bearer ` 류 토큰.
- 도구는 `pre-commit` + 자체 셸 훅이면 충분. 제3자 스캐너 불필요.

## ⑤ 정리
- `AGENTS.md` → "CLAUDE.md 를 본다" 한 줄로 축소.
- manifest 깨진 1건(`license: LGPL-3depends:[web]…`) 수정 — 어느 모듈인지는 개발이 확인.

---

## 분업 제안
- **claude-test**: ①②③ 초안 유지·수정 반영, `~/cams-odoo/CLAUDE.md`·`AGENTS.md` 로컬 적용(사용자 저장소).
- **claude-development(총괄)**: ② 의 배포 기전 사실 검토, ④⑤ 적용, `railway-uat/CLAUDE.md` 커밋·푸시
  (push 는 재배포를 유발하므로 선통지 절차 그대로).
- 합의본은 이 파일 v2 로 갱신하고 양쪽 status 에 링크.
