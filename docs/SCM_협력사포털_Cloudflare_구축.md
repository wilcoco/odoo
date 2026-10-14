# SCM 협력사 포털 외부공개 — Cloudflare Tunnel 구축 가이드

협력사 10곳이 **포털만** 안전하게 접속. **MES 본체는 방화벽 안 그대로**, 인바운드 포트 0개, 공개 IP 불필요.

```
협력사(브라우저) → Cloudflare HTTPS(portal.<도메인>) → cloudflared(아웃바운드 터널)
   → gateway(nginx: /supplier/* 만 통과, 관리·DB매니저 차단) → odoo:8069
```

추가되는 것: 컨테이너 **2개**(gateway, cloudflared)뿐. 새 서버·장비 없음.

---

## 0. 사전 준비 (사람이 해야 하는 부분)
1. **도메인** 1개를 Cloudflare 에 연결(네임서버를 Cloudflare 로). 무료 플랜 가능.
2. Cloudflare **Zero Trust** 대시보드 접속 (one.dash.cloudflare.com).

## 1. 터널 생성 + 토큰 발급 (Cloudflare 대시보드)
1. Zero Trust → **Networks → Tunnels → Create a tunnel** → "Cloudflared" 선택.
2. 이름 예: `cams-scm-portal` → 저장.
3. 화면에 나오는 **토큰**(`eyJ...` 긴 문자열)을 복사. ← 이게 `CF_TUNNEL_TOKEN`.
   - (도커 설치 명령 중 `--token eyJ...` 의 그 토큰 값만 쓰면 됩니다.)
4. **Public Hostname** 탭 → **Add a public hostname**:
   - Subdomain: `portal` / Domain: `<회사도메인>` (→ portal.회사도메인)
   - Type: `HTTP` / **URL: `gateway:80`**  ← ⚠️ odoo 가 아니라 **gateway**
   - 저장. (DNS CNAME 은 Cloudflare 가 자동 생성)

## 2. 서버 설정 (.env 에 토큰 주입)
운영 서버 `~/cams-odoo/.env` 에 한 줄 추가 (비밀 → git 제외):
```
CF_TUNNEL_TOKEN=eyJ...복사한_토큰...
```

## 3. 기동
```bash
cd ~/cams-odoo
docker compose -f docker-compose.yml -f docker-compose.scm-portal.yml up -d gateway cloudflared
# odoo.conf 변경(proxy_mode/list_db) 반영 위해 odoo 도 재기동
docker compose restart odoo
```

## 4. odoo.conf 확인 (이미 반영됨)
- `proxy_mode = True` — 터널/프록시 뒤 필수
- `list_db = False` — DB 매니저 노출 차단
- ⚠️ **`dbfilter` 를 운영 DB 로 고정**: odoo.conf 의 `; dbfilter = ^cams$` 주석을 풀고
  실제 운영 DB 이름으로 바꾼 뒤 `docker compose restart odoo`.
  (list_db=False 라 DB 가 하나로 특정돼야 포털이 정상 동작)

## 5. 검증
1. 브라우저에서 `https://portal.<도메인>/supplier/portal?token=<유효토큰>` → 포털 떠야 함.
2. **차단 확인(중요)**: 아래는 전부 **404/접근불가** 여야 정상 —
   - `https://portal.<도메인>/web/login`
   - `https://portal.<도메인>/web/database/manager`
   - `https://portal.<도메인>/odoo`
3. 내부망에서 직원 백엔드(`http://내부IP:8069/odoo`)는 평소처럼 접속.

## 6. 운영 메모
- **협력사 접속링크 = 토큰 URL.** 토큰은 길고 추측불가해야 하며(모듈이 발급), 안전한 채널로 전달.
- 더 잠그려면 Cloudflare **Access** 정책(이메일 OTP 등)을 `portal.<도메인>` 에 추가 → 토큰 + 신원 이중.
- 협력사 IP 가 고정이면 Cloudflare **WAF**에서 출발지 IP 화이트리스트 추가 가능.
- 포털을 잠시 내리려면: `docker compose ... stop gateway cloudflared` (MES 는 계속 가동).

## 차단/허용 요약 (gateway/portal.conf)
| 경로 | 처리 |
|---|---|
| `/supplier/*` | ✅ 포털 (통과) |
| `/web/static`,`/web/assets`,`/web/image`,`/website/static`,`/websocket` | ✅ 렌더링/실시간용 |
| `/` | → `/supplier/portal` 리디렉트 |
| **그 외 전부**(`/web/login`,`/odoo`,DB매니저,RPC…) | ⛔ 404 |
