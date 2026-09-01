# 에스콘 휴가 체계 가이드 (escon_eapproval)

휴가 유형·연차 발생·신청 화면은 전부 **코드가 정본**이다 (회계 kr_plus 설정
전역 단일화와 같은 패턴). Odoo 설정 화면에서 구조 설정을 바꾸면 차단되고,
우회되더라도 모듈 업그레이드 때 표준값으로 되돌아온다.

## 1. 휴가 유형 (6종)

정본: [models/setup.py](models/setup.py) 의 `LEAVE_TYPE_SPECS`

| 순서 | 유형 | 레코드(xml id) | 배정 필요 | 승인 | 단위 | 증빙 |
|---|---|---|---|---|---|---|
| 1 | 연차 | `escon_eapproval.leave_type_annual` | 필요 (자동 배정) | 휴가 승인자(1차) | 반차 가능 | - |
| 2 | 병가 | `hr_holidays.holiday_status_sl` | 불요 | 인사 담당 | 일 | - |
| 3 | 공가 | `escon_eapproval.leave_type_official` | 불요 | 인사 담당 | 일 | **첨부 필수** |
| 4 | 무급 휴가 | `hr_holidays.holiday_status_unpaid` | 불요 | 인사 담당 | 일 | - |
| 5 | 경조사 | `escon_eapproval.leave_type_family_event` | 불요 | 휴가 승인자(1차) | 일 | - |
| 6 | 대체휴무 | `escon_eapproval.leave_type_comp_off` | 필요 (인사 배정) | 휴가 승인자(1차) | 반차 가능 | - |

- 병가/무급 휴가는 Odoo 기본 레코드를 표준 스펙 관리 대상으로 편입했다
  (레코드 재사용, 값은 코드가 관장).
- Odoo 기본 유형 중 미사용분은 자동 보관(비활성) 처리된다:
  유급 휴가(`holiday_status_cl`), 포상 휴가(`holiday_status_comp`),
  추가 시간(`hr_holidays_attendance.holiday_status_extra_hours`)
  — 목록: `setup.py` 의 `DEFAULT_LEAVE_TYPE_XMLIDS`.

## 2. 연차 자동 발생 (에스콘 규정)

엔진: [models/annual_leave.py](models/annual_leave.py) (`escon.annual.leave`, 일일 크론)

- 입사 첫해: 입사일 응당일마다 1일 발생, 최대 11일
- 입사 1년 후: 기념일에 15일 / 입사 3년 이상: 16일
- 미사용 연차는 이월되지 않음 (배정 유효기간 만료로 자동 소멸)
- 입사일: 직원의 "입사일" 필드(미입력 시 첫 계약 시작일).
  설정 > 직원 부서/직급 에서 관리. 즉시 반영은 설정 > "연차 배정 지금 갱신".

## 3. 신청 화면 (커스텀, Odoo 기본 화면 미사용)

정의: [views/leave_views.xml](views/leave_views.xml) +
[static/src/dashboard/escon_leave.js](static/src/dashboard/escon_leave.js)

- **휴가 신청** 메뉴(및 품의서 작성 화면의 근태(휴가) 카드) →
  "내 휴가" 목록이 열리고 그 위에 신청 폼이 **팝업**으로 뜬다
  (`action_escon_leave_open` + 커스텀 리스트 뷰 `js_class="escon_leave_list"`
  가 컨텍스트 플래그를 보고 마운트 직후 팝업을 1회 오픈).
- **내 휴가** 목록의 "휴가 신청" 버튼도 같은 팝업을 연다 (신규 버튼 없음,
  페이지 이동 없음).
- 폼: 유형 / 시작·종료일 / 반차(연차·대체휴무) / 오전·오후 / 사유 / 증빙 첨부.
- 승인 흐름은 Odoo 표준(hr_holidays) 그대로: 유형별 승인자(위 표) 승인.
  관리자용 승인 화면은 휴가 > 휴가 승인.

## 4. 수정이 필요할 때 (변경 절차)

**모든 구조 변경은 코드 → 업그레이드.** UI 에서 직접 수정은 차단된다.

1. **유형 속성 변경** (승인 방식·단위·증빙 등):
   `models/setup.py` 의 `LEAVE_TYPE_SPECS` 에서 값 수정
   → `-u escon_eapproval` 업그레이드 (모든 서버가 같은 값으로 정합).
2. **유형 추가**: `data/leave_type_data.xml` 에 레코드 추가(최초 생성)
   + `LEAVE_TYPE_SPECS` 에 같은 값 등록(정합·보호) → 업그레이드.
3. **유형 제거/보관**: `DEFAULT_LEAVE_TYPE_XMLIDS` 에 xml id 추가(기본 유형)
   또는 스펙에서 `"active": False` (자사 유형) → 업그레이드.
4. **연차 발생 규정 변경**: `models/annual_leave.py` 상수
   (`FIRST_YEAR_MAX`/`BASE_DAYS`/`SENIOR_DAYS`/`SENIOR_YEARS`) 수정 → 업그레이드.
5. 배포 없이 재적용만 필요하면: 설정 > "Odoo 전자결재 기본 셋팅 재적용".

보호(수정 차단) 필드: 유형명·활성·배정/승인 방식·단위·증빙 필수
(`PROTECTED_LEAVE_TYPE_FIELDS`). 색상·정렬 등 재량 항목은 UI 수정 허용.
휴가 배정(hr.leave.allocation)과 개별 신청은 운영 데이터라 제한 없음.
