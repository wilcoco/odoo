#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQ 합집합 마스터·별칭·외부지적·기준값 CSV 생성(배정 087). 읽기 전용.

출력: union_items.csv / item_alias.csv / external_findings.csv / standard_values.csv
규칙: 원문 보존, 담당자 **이름 → 직책** 치환, 개인정보(명단·서명·연락처) 제외.
"""
import os
import re
import csv
import sys
import json
import openpyxl

SRC = os.path.expanduser('~/Downloads/OneDrive_2_10-19-2026')
OUT = os.path.dirname(os.path.abspath(__file__)) + '/sq-union'
os.makedirs(OUT, exist_ok=True)

# 이름 → 직책 (지적·준비 원문에 등장하는 사람). 직책만 남긴다.
NAME2ROLE = [
    (r'박래선\s*책임매니저\s*\(Senior\)', '캠스 생산기술팀 책임매니저'),
    (r'박래선\s*책임매니저', '캠스 생산기술팀 책임매니저'),
    (r'박래선', '캠스 생산기술팀 책임매니저'),
    (r'박순형\s*이사', '지금강 이사'), (r'박순형', '지금강 이사'),
    (r'김덕중\s*책임', 'HKMC 평가 책임'), (r'김덕중', 'HKMC 평가 책임'),
    (r'한승근\s*책임', '조립 책임'), (r'김준호\s*과장', '조립 과장'),
    (r'이준혁\s*매니저', '조립 매니저'), (r'백윤혁', '작성자'), (r'박성현', '검토자'),
    (r'전충극', '승인자'), (r'홍용표\s*과장', '관리책임자(정)'), (r'박형우\s*사원', '관리책임자(부)'),
    (r'김현재', '담당'), (r'송덕환', '담당'), (r'정상천', '담당'), (r'김상무님', '임원'),
    (r'박정훈', '작성자'), (r'박순형', '승인자'),
]


def anon(s):
    s = re.sub(r'\s+', ' ', s or '').strip()
    for pat, role in NAME2ROLE:
        s = re.sub(pat, role, s)
    return s


def cells(path, sheet):
    wb = openpyxl.load_workbook(os.path.join(SRC, path), read_only=True, data_only=True)
    ws = wb[sheet]
    rows = [[('' if v is None else str(v).strip()) for v in r] + [''] * 16
            for r in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


# ── 1. Ver5.1 (지금강 평가서) 47항목
AREA = {'1': '생산조건관리', '2': '검사시험', '3': '설비관리', '4': '금형관리',
        '5': '자재관리', '6': '품질경영체제'}
ver51 = []
for r in cells('에스콘 SQ 자료/2026-09-08 지금강(PL사출_캠스).xlsx', '평가결과'):
    if re.fullmatch(r'\d_\d+', r[0]):
        ver51.append({'code': r[0], 'req': anon(r[2]), 'points': r[3], 'state': r[4],
                      'score': r[5], 'obs': anon(r[6]), 'extra': anon(r[7])})

# ── 2. 우리 48항목 (MASTER = cams_sq 적재본)
ours = json.load(open(os.path.dirname(os.path.abspath(__file__)) + '/sq_items_inj.json'))
ours = [{'code': x['code'].replace('INJ.', ''), 'name': x['name'],
         'points': x['points'], 'req': anon(x['requirement'])} for x in ours]
ours_by = {x['code']: x for x in ours}

# Ver5.1 → 우리 코드
V2O = {'1_1': '1_1', '1_2': '1_2', '1_3': '1_3', '1_4': '', '1_5': '1_4', '1_6': '1_5',
       '1_7': '1_6', '1_8': '1_7', '1_9': '1_8', '1_10': '1_9',
       '6_1': '6_1', '6_2': '6_2', '6_3': '6_3', '6_4': '6_4', '6_5': '6_5',
       '6_6': '6_7', '6_7': '6_8', '6_8': '6_9', '6_9': '6_10',
       '6_10': '6_12', '6_11': '6_13', '6_12': '6_14'}
for a in '2345':
    for i in range(1, 12):
        c = '%s_%d' % (a, i)
        if c in [x['code'] for x in ver51]:
            V2O[c] = c
O2V = {v: k for k, v in V2O.items() if v}

# 우리에만 있는 항목
ours_only = [x for x in ours if x['code'] not in O2V]

# ── union_items.csv
rows = []
for x in ver51:
    o = V2O.get(x['code'], '')
    nm = re.sub(r'^▣\s*', '', x['req']).split(' - ')[0][:80]
    po = ours_by.get(o, {}).get('points', '') if o else ''
    pu = max(float(x['points'] or 0), float(po or 0))
    rows.append({
        'union_code': x['code'], 'industry': 'INJ', 'area_no': x['code'][0],
        'area_name': AREA[x['code'][0]], 'name': nm, 'requirement': x['req'],
        'points_ver51': x['points'], 'points_ours': po,
        'points_union': ('%g' % pu) + ('' if str(po) == x['points'] or not po else ' (max)'),
        'in_ver4': 'Y', 'in_ver51': 'Y', 'in_ours': 'Y' if o else 'N', 'in_prep_list': '',
        'note': ('' if o else 'Ver4·Ver5.1 공통 — 우리 마스터에만 없음'),
    })
for i, x in enumerate(ours_only, 1):
    code = '6_X%d' % i
    rows.append({
        'union_code': code, 'industry': 'INJ', 'area_no': '6', 'area_name': AREA['6'],
        'name': x['name'][:80], 'requirement': x['req'],
        'points_ver51': '', 'points_ours': x['points'], 'points_union': '%g' % x['points'],
        'in_ver4': 'N', 'in_ver51': 'N', 'in_ours': 'Y', 'in_prep_list': '',
        'note': '사내 추가(우리 %s) — Ver4·Ver5.1 모두 없음' % x['code'],
    })

# ── 3. 조립: SW 조립장 준비 LIST 34항목
AREA_A = {'1': '생산조건관리', '2': '검사시험', '3': '설비관리', '4': '자재관리', '5': '품질경영체제'}
asm = []
for r in cells('SQ평가서 참고본/SW 조립장 SQ 준비 LIST_250912(샘플).xlsx', '종합'):
    if re.fullmatch(r'\d_\d+', r[0]):
        asm.append({'code': r[0], 'req': anon(r[1]), 'finding1': anon(r[2]),
                    'pre': anon(r[3]), 'prep': anon(r[4])})
for x in asm:
    nm = re.sub(r'^▣\s*', '', x['req']).split(' - ')[0][:80]
    rows.append({
        'union_code': x['code'], 'industry': 'ASM', 'area_no': x['code'][0],
        'area_name': AREA_A.get(x['code'][0], ''), 'name': nm, 'requirement': x['req'],
        'points_ver51': '', 'points_ours': '', 'points_union': '',
        'in_ver4': '', 'in_ver51': '', 'in_ours': '미확인', 'in_prep_list': 'Y',
        'note': '배점 미기재(준비 LIST 에 없음). 우리 36항목과의 대응은 8070 sq.item 접근 거부로 미확인',
    })

hdr = ['union_code', 'industry', 'area_no', 'area_name', 'name', 'requirement',
       'points_ver51', 'points_ours', 'points_union', 'in_ver4', 'in_ver51', 'in_ours',
       'in_prep_list', 'note']
with open(OUT + '/union_items.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr)
    w.writeheader()
    w.writerows(rows)
print('union_items.csv %d행 (INJ %d + ASM %d)' % (
    len(rows), sum(1 for r in rows if r['industry'] == 'INJ'), len(asm)))
json.dump({'ver51': ver51, 'ours': ours, 'asm': asm, 'V2O': V2O},
          open(OUT + '/_build_cache.json', 'w'), ensure_ascii=False)

# ───────────────────────── item_alias.csv
alias = []
A = lambda u, s, ec, en, b: alias.append(
    {'union_code': u, 'source': s, 'external_code': ec, 'external_name': en, 'basis': b})
for x in ver51:
    nm = re.sub(r'^▣\s*', '', x['req']).split(' - ')[0][:70]
    A(x['code'], 'HKMC-Ver5.1', x['code'], nm, '동일문구')
for x in ours:
    u = O2V.get(x['code'])
    if u:
        A(u, 'OURS-48', x['code'], x['name'][:70], '동일문구' if u == x['code'] else '동일문구(번호 밀림)')
for i, x in enumerate(ours_only, 1):
    A('6_X%d' % i, 'OURS-48', x['code'], x['name'][:70], '동일문구')
for x in asm:
    nm = re.sub(r'^▣\s*', '', x['req']).split(' - ')[0][:70]
    A(x['code'], 'SW-PREP-250912', x['code'], nm, '동일문구')
# 금강 폴더 번호(= Ver5.1 체계) — 관측된 폴더만
GUM = [('1_1', '1. 생산조건관리'), ('2_1', '2. 검사시험'), ('3_2', '3-2. 설비 정기점검 업무절차 수립 및 준수여부'),
       ('3_3', '3-3. 원소재 건조장치 관리기준 설정 및 준수상태'), ('3_4', '3-4. 배합기, 분쇄기 관리기준'),
       ('6_1', '6-1. 안전사고 발생 예방 프로세스 준수현황'), ('6_2', '6-2. 설계변경,4M 변경'),
       ('6_3', '6-3. 도면기준 검사협정 체결 및 관리(도면 일치성)'), ('6_4', '6-4. 품질경영체제'),
       ('6_5', '6-5. 자격인증'), ('6_6', '6-6. 수입,공정,출하 부적합 관리'),
       ('6_7', '6-7. 품질 실적 점검 및 개선활동'), ('6_8', '6-8. 검사유효성확보를 위한 조도관리'),
       ('6_9', '6-9. 3정 5행'), ('6_10', '6-10. REWORK시 관리기준 수립 및 이행'),
       ('6_11', '6-11. (폴더 없음)'), ('6_12', '6-12 정성품질,개선현황')]
for code, folder in GUM:
    if '폴더 없음' in folder:
        continue
    A(code, 'GUMGANG-FOLDER', code, folder, '동일문구(폴더명)')
# 크레아 서류 일람(항목이 아니라 서류 묶음) — 범위를 union_code 로 보지 않고 구간만 기록
for rng, note in (('1-35', '품질'), ('36-76', '생산'), ('77-86', '금형'),
                  ('87-105,122', '보전·조립'), ('106-121', '구매·관리')):
    A('', 'CREA-DOCLIST', rng, '%s 서류 일람(항목 코드 아님)' % note, '추정(폴더 구간)')
# 크레아 리뷰 종합 시트 번호(= Ver5.1 체계로 관측)
for r in cells('크레아 GS SQ 참고/SQ참고/SQ리뷰개선요청건.xls'.replace('.xls', '.xls'), '종합') if False else []:
    pass
hdr2 = ['union_code', 'source', 'external_code', 'external_name', 'basis']
with open(OUT + '/item_alias.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr2)
    w.writeheader()
    w.writerows(alias)
print('item_alias.csv %d행' % len(alias))

# ───────────────────────── 2차 추출 JSON(구형 xls·pptx 포함)에서 읽는다
import unicodedata as U
W2 = '/private/tmp/claude-501/-Users-jhungsoohong-cams-odoo/e09056bf-6214-4b5d-bf3d-6ec964b77580/scratchpad/sq2'
EX = json.load(open(W2 + '/sq_extract2.json'))
nfc = lambda s: U.normalize('NFC', s)


def grab(key):
    for f in EX:
        if nfc(key) in nfc(f['path']):
            return f
    return None


# 크레아 리뷰 종합 시트 번호 → 별칭 (Ver5.1 체계로 관측: 1-4 = 취약시간대)
rev = grab('SQ리뷰개선요청건')
seen = set()
for sh in (rev['content'] if rev else []):
    for r in sh.get('rows', []):
        m = re.match(r'^(\d+-\d+)\s*\|\s*([^|]*)\|?\s*([^|]*)', r)
        if m:
            ec = m.group(1)
            if ec in seen:
                continue
            seen.add(ec)
            uc = ec.replace('-', '_')
            A(uc, 'CREA-REVIEW', ec, anon((m.group(3) or m.group(2)).strip())[:70], '추정(번호·문구)')
with open(OUT + '/item_alias.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr2)
    w.writeheader()
    w.writerows(alias)
print('item_alias.csv %d행 (크레아리뷰 %d 추가)' % (len(alias), len(seen)))

# ───────────────────────── external_findings.csv
fx = []
fid = [0]


def F(src, party, date, uc, ec, rating, text, improve, ev):
    fid[0] += 1
    fx.append({'finding_id': 'F%03d' % fid[0], 'source': src, 'evaluated_party': party,
               'date': date, 'union_code': uc, 'external_code': ec,
               'rating_or_score': rating, 'text': anon(text)[:1500],
               'improvement': anon(improve)[:900], 'status': '미조치', 'evidence_file': ev})


EV1 = '에스콘 SQ 자료/2026-09-08 지금강(PL사출_캠스).xlsx'
for x in ver51:
    F('지금강평가-Ver5.1', '지금강', '2026-09-08', x['code'], x['code'],
      '%s %s/%s' % (x['state'], x['score'], x['points']), x['obs'], x['extra'], EV1)

EV2 = '에스콘 SQ 자료/2026-09-08 지금강(PL사출_캠스)_지적사항.xlsx'
f = grab('지금강(PL사출_캠스)_지적사항')
for sh in f['content']:
    for r in sh.get('rows', []):
        m = re.match(r'^(\d+)\s*\|\s*(\d_\d+)\s*\|\s*(.+)$', r)
        if m:
            F('지금강지적', '지금강', '2026-09-08', m.group(2), m.group(2), '',
              m.group(3), '', EV2)

EV3 = '에스콘 SQ 자료/2026-2-3 4 ㈜크리아(PL사출,도장)_지적사항 _ 김덕중책임.xlsx'
# 이 파일은 **두 구간**이다: 순 1~21 = 도장 평가서 번호, 순 22~31 = 사출(Ver5.1) 번호.
# 1차 분석이 1.8KB 요약만 보고 "10건" 으로 적은 것은 도장 구간의 앞 10행이었다.
f = grab('크리아(PL사출,도장)_지적사항')
COMMON = {'1_1', '1_2', '1_3', '1_4'}      # 사출·도장 평가서가 공유하는 앞 항목(추정)
for sh in f['content']:
    for r in sh.get('rows', []):
        m = re.match(r'^(\d+)\s*\|\s*(\d_\d+)\s*\|\s*(.+)$', r)
        if not m:
            continue
        no, code, text = int(m.group(1)), m.group(2), m.group(3)
        if no >= 22:
            F('크레아지적-사출', '크레아', '2026-02-03', code, code, '', text, '', EV3)
        else:
            uc = code if code in COMMON else ''
            F('크레아지적-도장', '크레아', '2026-02-03', uc, code, '',
              text + ('' if uc else ' [도장 평가서 항목 — 사출 대응 없음]'), '', EV3)

# 에스콘 지도점검 18건 — 항목 다중 매핑
EV4 = '에스콘 SQ 자료/에스콘 SQ 지도 점검 _ 20261014.pptx'
GUIDE = [
    (1, ['6_3'], '검사협정서 체결 안됌 (캠스 ↔ 현대차, 캠스 ↔ 에스콘)', '검사협정서 체결 필요'),
    (2, ['6_3', '2_4'], '검사협정서 시료수 및 주기 재설정 필요 EX) ① 융착력 1회/1개월 / N=3 → 시업전 일상관리 ② 체결토크 ▶ 갑지 : 1회/년 N=3 → 첨부 참조 (자동차 요구 표준) ③ 부착성 1회/6개월 → 일상관리 (협력사 / 에스콘 주기 설정등)', '검사협정서 내용 개정 필요'),
    (3, ['2_5'], '검사협정서 기준 검사항목에 맞는 계측기 구비 필요 (광택계, 색차계,크로스커팅)', '계측기 구입 여부 협의 필요'),
    (4, ['4_3'], '금형, 설비 SPARE PART 관리기준 및 관리대장', '관리대장 샘플 작성 후 에스콘 공유 : 관리대장 작성 (캠스 생산기술팀 책임매니저 작성 후 공급)'),
    (5, ['4_2', '4_1'], '금형관리 (세척기준, 일상점검등 : 전산시스템 기준 활용시 이슈)', '금형세척 표준서 작성 (캠스 생산기술팀 책임매니저 작성 후 공급) / 금형세척기, 세척제등 구입 / 세척 이력관리 (작업자 확보 및 교육 필요)'),
    (6, ['4_7'], '금형온도 측정 기준서 및 측정관리', '금형 열화상 카메라 시스템 확인 (휴먼텍)'),
    (7, ['6_11'], '관리계획서 중 조립 F/PROOF 대상 너무 많음', 'F/proof 관리 마스터 및 점검 체크시트 작성 필요'),
    (8, ['1_9', '3_3'], '사출 원재료 수분측정 기준서 재설정 (물 분무시 1100PPM → 건조 1,2,3HR )', '실제 수분측정 데이터 및 근거 확보 필요 3시간 건조조건 관리기준 만족시 조업 3시간전 호퍼드라이 가동 및 이력관리 필요'),
    (9, ['4_6'], '금형 예열관리 기준서 및 예열 체크시트', '기준서 및 체크시트 작성 보완'),
    (10, ['1_5'], '사출 중량 관리기준 설정', '설계중량 대비 사출후 실중량 관리 기준 수립 필요 : 관련근거 확보'),
    (11, ['5_2', '4_4'], '원재료 보관장 / 금형보관장 LAY–OUT 설정 및 가시관리', '원재료 / 금형 보관장 LAY-OUT 설정 / 선입선출관리 / 금형 운영유무 양산 & A/S 금형등 식별관리 / 금형 이물유입 방지대책 필요'),
    (12, ['2_3', '2_1', '6_5'], '수입검사장 점검 (작격인증 / 한도견본 / 검사기준서등)', '업데이트 필요 (원재료 한도견본 샘플 / 신재, 기타 외주 협력사 부품)'),
    (13, ['1_1', '1_7'], '사출조건표 관리 (관리계획서, 사출조건표, 사출기 설정값 일치 확인)', '각 아이템별 일치성 확인 필요 ± 허용공차까지 일치화 시켜 관리 필요'),
    (14, ['6_2'], '4M 이력관리', ''),
    (15, ['6_5'], '자격인증 관리 및 적격성 평가', '평가서 미리 작성 후 작업자 선정시 대응 필요'),
    (16, ['2_5', '3_1'], '설비 관리 (게이지 상하한 식별 누락 : 전체 게이지)', '식별표 부착'),
    (17, ['6_9'], '원재료, 배관류 흐름방향 표시', ''),
    (18, ['6_1'], '소화기 식별표 부착위치 개선 필요', ''),
]
for no, codes, text, improve in GUIDE:
    for c in codes:
        F('에스콘지도점검', '에스콘', '2026-10-15', c, 'NO.%d' % no, '', text, improve, EV4)

# SW 조립 1차 평가 지적 17건
EV5 = 'SQ평가서 참고본/SW 조립장 SQ 준비 LIST_250912(샘플).xlsx'
for x in asm:
    if x['finding1']:
        F('SW조립1차평가', 'SW조립장', '', x['code'], x['code'], '', x['finding1'],
          x['prep'], EV5)

# 크레아 리뷰 — 종합 시트: 번호가 붙은 행만(그 아래 세부행은 같은 번호에 합친다)
EV6 = '크레아 GS SQ 참고/SQ참고/SQ리뷰개선요청건.xls'
cur, buf = '', []
def flush():
    if cur and buf:
        F('크레아리뷰', '크레아', '', cur if re.fullmatch(r'\d_\d+', cur) else '',
          cur.replace('_', '-'), '', ' / '.join(buf), '', EV6)
for sh in (rev['content'] if rev else []):
    if sh.get('sheet') != '종합':
        continue
    for r in sh.get('rows', []):
        m = re.match(r'^(\d+-\d+)\s*\|\s*(.+)$', r)
        if m:
            flush()
            cur, buf = m.group(1).replace('-', '_'), [m.group(2)]
        elif cur and r and not r.startswith('NO '):
            buf.append(r)
    flush()
    cur, buf = '', []

# 평가원 관점 — 항목별 분해
EV7 = '에스콘 SQ 자료/2026.10.11_SQ 신규평가시 평가원 평가 내용 _ 사출 & 도장 (크레아 기준).pptx'
VIEW = [
    ('5_2', '원재료 창고 / 적정재고 관리기준 · 현 보유재고 확인', '원재료 창고 레이아웃외 재고현황 마스터 관리'),
    ('2_1', '수입검사 / 원재료 LOT별 성적서 관리', '1) 원재료 LOT 관리 / 성적서등 매칭성 확인 / 검사기준서 대비 검사결과 / 합격도장 날인등 관리여부'),
    ('3_3', '원재료 관리 / 호퍼드라이 점검 · 수분측정용 샘플 시료 체취 · 수분 관리기준 · 원재료 한도견본(신재/분쇄재) · 건조일보 · 건조기준서', '1) 샘플 시료 체취 방법 및 작업자 작업방법 확인 - 샘플 시료 체취 위치등 확인 점검 2) PFMEA & 관리계획서, 수분측정 성적서등 기준 일치성 점검 3) 원재료 한도견보 / H/D 건조 일보 / 건조 기준서 / 사출 F/P'),
    ('4_3', '금형관리/설비관리 / 금형·설비 SPARE PART 관리기준 대비 실 보유현황', '1) 금형 SPARE PART 보관장 3정 5S 및 적정재고 유지관리 상태 확인 / 가시관리등'),
    ('3_1', '설비관리 / 생산일보 기준 설비 일상점검표 정합성·매칭성 점검', '1) 설비 가동/비가동일 기준 설비 점검일 점검 (26년 일보 기준 설비 점검표 확인)'),
    ('1_8', '금형교환 / 금형교환·원재료 변경 이력관리', '1) 금형교환 및 원재료 변경관련 조업일보 /초중종물 체크시트 등 일치성 확인'),
    ('4_2', '금형관리 / 금형 타발수 · 금형점검 기준서 · 세척관리', '1) 금형 등급별 세척주기 관리기준 대비 실적 점검'),
    ('6_8', '품질관리 / 조도관리 기준서 및 측정', '조도관리 기준서 수립 및 측정주기, 측정결과 대비 이력관리 조도 측정위치 레이아웃 설정하여 도식화 관리여부'),
    ('2_8', '품질관리 / 출하검사 성적서', '1) 검사기준서 대비 성적서 일치서 확인 / 생산LOT, 출하일, 성적서등. (LOT성적서등)'),
    ('5_1', '원재료 관리 / LOT 관리', '원재료 투입대비 사출 LOT 기록관리 여부 확인 - 원재료 LOT가 사출품에서 관리가 되는지등 확인'),
    ('6_2', '품질관리 / 4M · 설변 이력관리', '1) 4M변경 설계변경통보서 외 유효성 평가 결과등 점검'),
    ('6_10', '품질관리 / 부적합품 처리', '1) 부적합품 처리 (리워크 프로세스) /낙하품 처리 관리 프로세스 및 이력 확인'),
]
for c, req, how in VIEW:
    F('평가원관점', '(일반)', '2026-10-11', c, '', '', req, how, EV7)

hdr3 = ['finding_id', 'source', 'evaluated_party', 'date', 'union_code', 'external_code',
        'rating_or_score', 'text', 'improvement', 'status', 'evidence_file']
with open(OUT + '/external_findings.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr3)
    w.writeheader()
    w.writerows(fx)
import collections
print('external_findings.csv %d행' % len(fx), dict(collections.Counter(x['source'] for x in fx)))

# ───────────────────────── standard_values.csv (18 §3-3 + 20 §1·§4 + 2차 지적 신규값)
SV = [
    # union_code, parameter, escon_value, escon_source, ref_value, ref_source, unit, decision
    ('1_6', '원재료 수분 — 입고 시', '0.15 이하', '에스콘 3-3.호퍼드라이 건조능력관리 및 수분측정기준.pptx', 'PC/ABS 0.07 이하(크레아 실관리)', '크레아지적-사출 25', '%', 'N'),
    ('1_6', '원재료 수분 — 성형 전', '0.11 이하', '에스콘 3-3.호퍼드라이…pptx', '0.06 초과 시 추가건조(금강)', '금강 건조기 하한선 설정 표준 양식_26년.xlsx', '%', 'N'),
    ('1_6', '수분 측정 조건', '120℃ 5min, 설비별 주·야 각 1회', '에스콘 3-3.호퍼드라이…pptx', '최소 건조시간 1시간 준수 후 측정', '크레아지적-사출 25', '-', 'N'),
    ('1_9', '수분 시료 채취 위치', '(미정)', '-', '호퍼 상단 → 하단으로 변경 요구', '크레아지적-사출 25', '-', 'Y'),
    ('1_9', '수분 재설정 기준', '물 분무 시 1100PPM → 건조 1·2·3HR 측정', '에스콘 지도점검 8', '-', '-', 'PPM', 'N'),
    ('3_3', '조업 전 호퍼드라이 가동', '3시간 전(3시간 건조조건 만족 시)', '에스콘 지도점검 8', '-', '-', 'h', 'N'),
    ('3_3', '건조 온도·시간(재질별)', '(미정)', '-', 'PP 90±10℃ 1h / ABS·PC·PC+PBT 100±10℃ 2h (크레아) ↔ PP 70~80℃ 1~2h / ABS·ASA 80~90℃ 2~3h / PC ABS 90~100℃ 2~4h / PC+PBT·PC 100~110℃ 2~4h (금강 현장 게시)', '크레아 [사출]호퍼드라이어 건조온도기준.xlsx / 금강 원소재 건조시간 표준표.jpg(20 §1)', '℃·h', 'Y'),
    ('3_3', '건조기 하한선', '(미정)', '-', '용량 100/150/250kg → 50/75/150kg, 최소 건조시간 × 시간당 사용량', '금강 건조기 하한선 설정 표준 양식_26년.xlsx', 'kg', 'Y'),
    ('3_3', '호퍼 필터 청소·교환', '(미정)', '-', '청소 주 1회·교환 년 1회(크레아) ↔ 청소 주 2회(월·목)·교환 년 3회(4·8·12월)(금강)', '크레아 48. 설비관리_건조기(필터) 관리 기준서 / 금강 호퍼 드라이 체크시트(20 §1)', '-', 'Y'),
    ('3_3', '호퍼 설정온도 vs 실측 편차', '(미정)', '-', '±10℃ 이탈 시 2점·가동중지', '금강 호퍼 드라이 일상점검표(20 §1)', '℃', 'Y'),
    ('3_4', '분쇄재 입자 등급', '≤30mm 사용가능 / 30~40mm 사용가능+커팅날 점검 / ≥40mm 사용불가(추가 분쇄)', '에스콘 3-4-1.분쇄재 관리기준 표준서.pptx', '-', '-', 'mm', 'N'),
    ('3_4', '분쇄재 샘플링', '월 1회(첫째주 월) 500mL 샘플통, 최대 입자 기준', '에스콘 3-4-1…pptx', '-', '-', 'mL', 'N'),
    ('3_4', '분쇄기 점검 장부(4종)', '분쇄일지 / 분쇄기 설비 점검일지 / 혼합일지 / 혼합비율 점검시트', '에스콘 3-4 분쇄.혼합 관리항목.ppt(20 §2)', '-', '-', '-', 'N'),
    ('3_4', '분쇄기 칼날 틈새', '(미정)', '-', '1.5mm 이하', '금강 분쇄기 작업관리기준표.xls', 'mm', 'Y'),
    ('3_4', '분쇄기 칼날 교체', '(미정)', '-', '12,000kg 분쇄 후', '금강 분쇄기 작업관리기준표.xls', 'kg', 'Y'),
    ('3_4', '분쇄기 칼날 점검·기어오일', '(미정)', '-', '칼날 1회/주 육안 · 기어오일 1회/월 · 청소 일과 전·후 · 시험가동 5분', '금강 분쇄기 작업관리기준표.xls', '-', 'Y'),
    ('3_5', '지그 정기점검 항목', '5항목(청결·안착·형상·자국·볼트 풀림), 육안, 기준 "없을 것", 1회/월', '에스콘 3-5.조립라인 컨베어 지그 관리 기준서.ppt 1쪽(20 §2)', '-', '-', '-', 'N'),
    ('3_5', '지그 변형 한계', '(미정 — U지그분 ppt 2쪽 이후 미해석)', '-', '모서리 들뜸량 ≤10.0mm(4개소), 초과 시 사용금지·재검증 승인', '금강 도장지그 변형 검증 기준서_2026년.pptx', 'mm', 'Y'),
    ('6_8', '조도 기준값', '150~1,500Lux↑(공정별 상이, 검사공정 준용)', '에스콘 6-9.에스콘 공장동 조도 관리 기준서.pptx', '사출 검사 작업대 1000Lux 이상(KSA 초정밀 750/1000/1500)', '금강 사출 조도 체크시트·측정 관리 기준서(20 §1)', 'Lux', 'Y'),
    ('6_8', '조도 측정 주기', '매월 15일(휴무 시 익일), 일몰 후', '에스콘 6-9…pptx', '1회/월, 전구 5분·방전등 30분 점등 후, 측정자 30cm 이상, 작업면 수평조도, KS A 3011:1998', '금강 5-8. 조도측정 기준서.xlsx', '-', 'N'),
    ('6_8', '조도 측정 시간대', '(개정 필요 — 일몰 기준 기재)', '지금강지적 19(동절기 18:00 이후 / 하절기 20:00 이후로 개정 요구)', '하절기(4~9월) 18시 이후 / 동절기(10~3월) 16시 이후', '금강 5-8. 조도측정 기준서.xlsx', '-', 'Y'),
    ('6_8', '조도 측정 높이·위치', '(미정)', '-', '40cm 위 높이에서 측정, 측정위치 번호 = 조도 Lay-Out 번호', '크레아 28.1 조도 표시(예).ppt(20 §1)', 'cm', 'Y'),
    ('2_3', '한도견본 점검 주기', '1회/12개월(특이사항 시 개정)', '에스콘 2-3.한도견본관리기준서.xls', '유효기간 6개월(금강 대장) · 정기점검 2회/년(크레아 이력카드) · 원재료 시료 만기 = 채취 +12개월(금강 LIST)', '금강·크레아 양식, 20 §1', '-', 'N'),
    ('2_4', '정기검사 주기', '(미정)', '-', '1회/6개월(금강 계획대비실적)', '금강 2026년 캠스 정기검사 계획대비 실적_260610.xls', '-', 'Y'),
    ('2_4', '검사협정 시료수·주기', '융착력 1회/1개월 N=3 → 시업전 일상관리 / 체결토크 갑지 1회/년 N=3 / 부착성 1회/6개월 → 일상관리', '에스콘 지도점검 2', '-', '-', '-', 'Y'),
    ('6_3', '도면 일치성 점검 주기', '(미정)', '-', '1회/3개월', '금강 6-3. 도면일치성 점검 계획&실적시트.xls', '-', 'Y'),
    ('5_4', '용기 청정활동', '연 4회(발청·캐스터휠·용기훼손·오염)', '에스콘 5-4-1 납입용기 청정활동 기준서.pptx', '-', '-', '회/년', 'N'),
    ('5_4', '자동화 용기 승인 의뢰', 'T1 30일 전', '에스콘 5-4-2 납입용기 선정 기준서.xlsx', '-', '-', 'd', 'N'),
    ('6_12', '정성품질 교육·점검', '각 최소 1회/년, 대표이사 승인', '에스콘 5_12 정성품질프로세스.pptx', '전달교육 결과 양식(대표이사 확인 서명·교육 개요·내용·사진 2)', '금강 첨부3(20 §2)', '회/년', 'N'),
    ('1_8', '초중종물 검사항목', '(미정 — 에스콘 동등 문서 미확인)', '-', '9종 고정(미성형·가스자국·흑점/흑줄·취출불량·백화·수축·기스·웰드라인·기타 이물), 초물 3EA 연속 불량 시 작업 중지', '금강 초물관리표준서(VER.2020.001).xls', '-', 'Y'),
    ('1_7', '성형조건 권장 공차', '(미정)', '-', '노즐(수지)온도 ±5℃ · 작동유 온도 ±5℃ · 냉각수 입/출수 온도차 3℃ 이내 · 기타 조건 ±5%', 'Ver5.1 1_7 요구사항 원문', '-', 'Y'),
    ('1_7', '작동유 온도', '(미정)', '-', '동절기 30±5℃ / 하절기 40±5℃(관리계획서) ↔ 35~45℃(일상점검표) — 불일치가 지적됨 / 작동유 IN 15±5℃', '지금강지적 1·3 · 크레아지적-사출 27', '℃', 'Y'),
    ('1_2', '재가동 초품검증', '(미정)', '-', '계획/비계획 60분 이상 시', '크레아 SQ리뷰개선요청건.xls', 'min', 'Y'),
    ('4_2', '금형 세척 주기', '(미정)', '-', 'B등급 30,000 SHOT / 6개월', '지금강지적 11', 'SHOT·개월', 'Y'),
    ('4_6', '금형 예열 온도', '(미정)', '-', '관리온도 250℃(재질별 상이 미반영이 지적됨)', '지금강지적 15', '℃', 'Y'),
    ('6_5', '자격인증 합격선', '(미정)', '-', '75점 이상 자격 부여(경력 30 + 교육 20 + 학력 20 = 70, 숙련도 20: 우수 20/양호 15/미흡 10)', '크레아지적-도장 19', '점', 'Y'),
]
hdr4 = ['union_code', 'parameter', 'escon_value', 'escon_source', 'ref_value', 'ref_source',
        'unit', 'decision_needed']
with open(OUT + '/standard_values.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(hdr4)
    w.writerows(SV)
print('standard_values.csv %d행 (확정 필요 %d)' % (len(SV), sum(1 for x in SV if x[7] == 'Y')))

# ───────────────────────── 도장(PNT) 판 — 크레아 지적 도장 구간에서 관측된 항목만
# 도장 평가서 **전체 항목표는 자료에 없다**. 지적을 받은 번호만 확인된다.
PNT_OBS = [
    ('1_1', 'FMEA·관리계획서 공정번호/순서 일치'), ('1_2', '가동중단 시간별·상황별 조치'),
    ('1_4', '주말/휴일 특근 관리기준'), ('1_8', '제전 후 정전압 측정'),
    ('1_10', '도료 배합 중량 기록·사용 유효시간'), ('1_11', '배합 잔량 도료 폐기기준'),
    ('2_1', '도료 입고 시 유효기간(잔여) 기준'), ('2_2', '수입검사 대장 LOT ↔ 밀시트 LOT'),
    ('2_7', '도막두께 X-R 관리도 관리한계'), ('2_8', '완제품 도장검사 시점·층별 두께'),
    ('3_1', '제전공정 에어압력 일상점검'), ('3_2', '도장부스 온습도 F/P 모니터링'),
    ('3_4', '건조로 온도 기록·타점기록계 이력'), ('3_5', '건조오븐 온도프로파일 C/V 속도'),
    ('3_6', '지그 누적사용량별 등급·점검주기'), ('3_7', '컨베어 속도 관리'),
    ('4_2', '도료 보관창고 레이아웃'), ('4_3', '도료 유효기간(제조일 기준) 관리'),
    ('5_5', '자격인증(검사원) 평가기준'), ('5_7', '품질현황 ↔ 출하검사 기록 정합'),
    ('5_12', '정성품질 프로세스·포상·전파교육 이력'),
]
pnt_rows = []
for code, nm in PNT_OBS:
    pnt_rows.append({
        'union_code': code, 'industry': 'PNT', 'area_no': code[0], 'area_name': '(도장 평가서 영역)',
        'name': nm, 'requirement': '(도장 평가서 원문 미확보 — 지적 원문은 external_findings 참조)',
        'points_ver51': '', 'points_ours': '', 'points_union': '',
        'in_ver4': '', 'in_ver51': '', 'in_ours': 'N', 'in_prep_list': '',
        'note': '도장 업종 판 — 크레아 지적(2026-02-03)에서만 관측. 전체 항목표 미확보. 사출/조립과 번호 체계가 다르다',
    })
with open(OUT + '/union_items.csv', 'a', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr)
    w.writerows(pnt_rows)
for code, nm in PNT_OBS:
    A(code, 'CREA-PAINT-2026', code, nm, '추정(지적 번호)')
with open(OUT + '/item_alias.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr2)
    w.writeheader()
    w.writerows(alias)
print('도장(PNT) 관측 항목 %d행 추가 | item_alias %d행' % (len(pnt_rows), len(alias)))

# ───────────────────────── HKMC Ver4(2025판) 별칭 — handoff 12 로 확인: Ver5.1 과 번호·명칭 동일
for x in ver51:
    nm = re.sub(r'^▣\s*', '', x['req']).split(' - ')[0][:70]
    A(x['code'], 'HKMC-Ver4', x['code'], nm, '동일문구')
with open(OUT + '/item_alias.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, fieldnames=hdr2)
    w.writeheader()
    w.writerows(alias)
print('Ver4 별칭 47행 추가 → item_alias %d행' % len(alias))
