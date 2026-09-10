# SCM 협력사 포털 DMZ 리버스 프록시 — 검증·정비 결과 (담당자 회신)

담당자 체크리스트 잘 받았습니다. 실제 Odoo 모듈(`supplier_portal_purchase`) 기준으로 **경로·보안을 검증**하고, nginx 설정을 정비했습니다. 적용할 설정은 **`deploy/dmz-portal/portal.goescon.com.conf`** 입니다 (nginx `-t` 문법검증 통과).

---

## A. 담당자 "확인 필요" 5건 답변

| # | 항목 | 답변 |
|---|---|---|
| 1 | 도메인명 | **portal.goescon.com** 로 진행 OK (기존 erp와 동일 IP·DNS·NAT 재사용) |
| 2 | Odoo DB 이름(dbfilter) | **erp.goescon.com 이 쓰는 그 DB와 동일**(같은 Odoo 10.10.21.20). odoo.conf 에 `dbfilter = ^<그DB명>$` 고정. DB명은 Odoo 서버에서 `psql -l` 또는 현재 conf 로 확인. |
| 3 | 8072(웹소켓) 방화벽 | **필수 아님.** 미개방이어도 포털 정상 동작(알림은 새로고침 시 갱신). **실시간 푸시가 필요할 때만** DMZ(10.10.99.100)→Odoo:8072 규칙 추가. → 지금 블로커 아님 |
| 4 | 협력사 고정 IP | 목록 확보되면 **화이트리스트 강력 권장**(config 에 주석으로 준비됨). 없으면 경로 화이트리스트+rate-limit 로 방어 |
| 5 | **SCM 경로** | ✅ **`/supplier/*` 확정.** 모듈 전 라우트가 `/supplier/...` (auth="public" + 토큰). `/my/*`·`/web/portal/*` 아님 |

## B. ⚠️ 담당자 draft에서 **수정한 보안 이슈** (중요)

1. **`/web/login` 허용 → 제거했습니다.**
   - 협력사 포털은 **토큰(auth=public) 방식이라 로그인 자체를 안 합니다**(컨트롤러에 auth=user·로그인 리다이렉트 없음 — 정적분석 확인).
   - `/web/login` 을 열면 **인터넷에서 Odoo 백엔드 로그인창이 노출** → 내부·admin 계정 브루트포스 표적이 됩니다. → **차단(404)**.
2. **`/web/session` 허용 → 제거했습니다.**
   - `/web/session/authenticate` 는 자격증명 로그인 엔드포인트라 노출 금지.
   - 라이브 테스트에서 프론트 JS가 세션정보를 요구하면 **오직 `/web/session/get_session_info`(읽기전용)만** 추가 허용. `authenticate`·`login` 은 절대 열지 말 것.
3. **렌더링 자산 보강**: 템플릿이 `website.layout` 사용 → `/web/assets`,`/web/static` 외 **`/web/image`(로고),`/website/static`** 추가.
4. **그 외 전부 404**: `/odoo`,`/web/database/*`(DB매니저),`/xmlrpc`,`/jsonrpc` 등 백엔드·RPC 전부 차단.

## C. Odoo 쪽 설정 (nginx와 별개, 이미 반영됨 — odoo.conf)
- `proxy_mode = True` (프록시 뒤 X-Forwarded-* 신뢰)
- `list_db = False` (DB매니저 노출 차단)
- `dbfilter = ^<운영DB>$` (⚠️ 운영 DB명으로 고정 — erp가 쓰는 DB)
> ⚠️ 같은 Odoo가 erp(내부)·portal(외부) 둘 다 서빙하므로 이 설정은 erp에도 적용됩니다. erp가 단일 DB면 문제없음.

## D. 적용 절차 (기존 Windows nginx)
1. 가비아 DNS: `portal` A 레코드 → 59.1.56.114
2. win-acme 로 `portal.goescon.com` 인증서 발급 → `C:\nginx-1.28.3\conf\ssl\` (chain/key.pem)
3. **`portal.goescon.com.conf`** 를 `C:\nginx-1.28.3\conf\` 에 두고 `nginx.conf` 의 `http{}` 에서 `include`
   (또는 내용을 nginx.conf http 블록에 붙여넣기)
4. `nginx -t` → `nginx -s reload`
5. 검증:
   - ✅ `https://portal.goescon.com/supplier/portal?token=<유효토큰>` → 포털 표시
   - ⛔ `https://portal.goescon.com/web/login` → **404 여야 정상**
   - ⛔ `https://portal.goescon.com/odoo`, `/web/database/manager` → **404**

## E. 검증 상태 (이번에 확인한 것)
- ✅ 모듈 라우트 경로 `/supplier/*` 정적분석 확인
- ✅ 토큰 방식(로그인 불필요) 확인 → `/web/login` 불필요·위험 판정
- ✅ `website.layout` 자산 의존성 확인 → 자산 화이트리스트 보강
- ✅ nginx `-t` 문법 검증 통과
- ⚠️ **라이브 검증 권고**: 실제 발급 토큰으로 포털 1페이지 렌더링 시 프론트 JS가 `/web/session` 없이 정상인지 스테이징에서 1회 확인(대개 정상, 서버렌더 방식). 이상 시 위 B-2 대로 `get_session_info` 만 추가.

---
※ 이전에 검토했던 Cloudflare Tunnel 방식(`docker-compose.scm-portal.yml`, `gateway/`)은 **DMZ로 결정되어 미사용**입니다. 관련 PR은 닫아도 됩니다.
