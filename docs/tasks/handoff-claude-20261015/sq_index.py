#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQ 참고자료 색인: 파일 → (SQ 항목, 쓸모) 분류 + 미흡 9항목 후보 추출. 읽기 전용(JSON 만 읽는다)."""
import json
import re
import sys
import collections

BASE = '/Users/jhungsoohong/Documents/Codex/2026-09-10/new-chat/AI-Agent-Queue/attachments/sq-ref-analysis'

# 금강 6영역 폴더 번호는 우리 48항목과 어긋난다(관측). 폴더 → 우리 코드.
GUM_SIX = {'6-1': '6_1', '6-2': '6_2', '6-3': '6_3', '6-4': '6_4', '6-5': '6_5',
           '6-6': '6_7', '6-7': '6_8', '6-8': '6_9', '6-9': '6_10',
           '6-10': '6_12', '6-12': '6_14'}

# 크레아 자체 번호(품질 1-35 / 생산 36-76 / 금형 77-86 / 보전·조립 87-105,122 / 구매·관리 106-121)
# 는 항목 코드가 아니라 **서류 일람 번호**다(관측: 폴더 안 파일명이 "1. ISIR…", "27. 공정검사 PPM" 식).
# 따라서 크레아는 폴더로 매핑하지 않고 파일명·본문 키워드로만 매핑한다.

#: 도장·도금은 우리 사출 48항목 밖(타업종). 별도 통으로 센다.
PAINT = r'도장|도금|도료|막후|막두께|도막|프라이머|클리어|제전|스프레이|피도물'

KW = [
    ('2_3', r'한도견본|한도 견본|마스터견본|마스터 견본|限度'),
    ('6_6', r'교안|품질교육|교육계획|사내교육|사내_ ?교육'),
    ('6_11', r'수평전개|수평 전개|품질현황'),
    ('6_13', r'누락 ?방지|공정누락|풀프루프|포카요케|Fool ?Proof|F/P'),
    ('1_7', r'초물|초기 ?허용|초중종'),
    ('4_3', r'금형 ?등급|시사출|금형관리방안'),
    ('3_2', r'예방보전|예방보존|정기점검|TBM|월 ?설비점검|년간설비'),
    ('2_4', r'신뢰성|정기검사|정기 시험|내구|촉진|열충격|항온항습'),
    ('3_3', r'건조시간|건조조건|건조장치|호퍼|H/?D|핫에어|드라이어|제습건조|건조기'),
    ('3_4', r'배합기|분쇄기|크러셔|믹서|배합 ?비|분쇄'),
    ('1_9', r'분쇄|배합|스크랩|재생재|리그라인드'),
    ('3_5', r'지그|JIG|치구'),
    ('5_4', r'용기|파레트|팔레트|대차|도시락|적재함|포장 ?규격'),
    ('6_3', r'검사협정|도면 ?일치|도면기준|ISIR'),
    ('6_14', r'정성품질|정성 품질'),
    ('2_5', r'검교정|교정|계측기|검사구|게이지'),
    ('6_9', r'조도'),
    ('6_10', r'3정|5행|5S|3정5행'),
    ('6_12', r'REWORK|리워크|재작업'),
    ('6_1', r'안전|위험성평가|유해|보호구|LOTO'),
    ('6_5', r'자격|인증|교육이력|스킬|다기능'),
    ('5_1', r'LOT ?추적|추적성|로트추적'),
    ('4_6', r'예열'),
    ('4_7', r'금형 ?온도|금형온도'),
    ('4_2', r'세척'),
    ('4_3', r'보전|정비'),
    ('1_5', r'수분 ?관리|수분관리'),
    ('1_8', r'수분 ?함유|수분측정|수분 ?검증'),
    ('1_4', r'원단위|중량 ?관리|실중량'),
    ('1_6', r'성형조건|사출조건|조건표'),
    ('1_7', r'초기 ?허용|초기허용불량'),
    ('2_7', r'자주검사|패트롤|순회'),
    ('2_8', r'완제품 ?검사|출하검사'),
    ('2_1', r'수입검사'),
    ('1_1', r'관리계획서|FMEA|작업표준|표준류|Control ?Plan'),
    ('3_1', r'일상점검'),
    ('3_2', r'정기점검|예방보전|TBM'),
    ('4_1', r'금형 ?점검|타발|숏트|SHOT'),
    ('6_2', r'4M|설계변경|설변'),
    ('6_4', r'내부감사|시정조치|경영검토|품질경영'),
    ('6_7', r'부적합|격리|식별'),
    ('6_8', r'품질실적|PPM|불량률'),
    ('6_6', r'교안|품질교육'),
    ('6_13', r'누락 ?방지|공정누락|풀프루프|F/?P|포카요케'),
    ('2_6', r'R&R|게이지알앤알'),
    ('2_2', r'수입검사 ?대장'),
    ('2_9', r'융착'),
    ('5_2', r'보관장|창고'),
    ('5_3', r'식별 ?관리|입고품 ?식별'),
    ('1_2', r'가동중단|재가동'),
    ('1_3', r'외국인|현지어'),
    ('6_11', r'수평전개|품질현황'),
]

FORM = r'기준서|표준서|절차서|점검표|체크|대장|양식|서식|LIST|리스트|관리표|일보|일지|계획서|규정|매뉴얼|지침'
CRIT = r'기준서|조건표|규격|스펙|SPEC|한도|관리기준|조건'
REC = r'성적서|실적|이력|결과|현황|측정|기록|점검결과|교정성적'
JUNK = r'\.(png|jpg|jpeg|mp4|zip)$|로고|CI$|사진'


def item_of(path, declared):
    """폴더 번호 우선, 없으면 키워드. 반환 (코드, 근거)."""
    p = path
    if p.startswith('에스콘 SQ 자료/'):
        m = re.search(r'/(\d)[-_](\d{1,2})\s', p)
        if m:
            return '%s_%d' % (m.group(1), int(m.group(2))), '에스콘 폴더번호'
    if p.startswith('G금강 SQ 참고/'):
        # 6영역 폴더 안에서는 6-x 매핑만 쓴다(금강은 그 안에 '5-5 사내 교육계획서' 처럼
        # 다른 번호를 섞어 둔다 — 영역 밖 번호를 그대로 쓰면 오분류).
        in_six = '/6. 품질경영체계/' in p
        m = re.search(r'/(6-\d{1,2})\.?\s', p)
        if m:
            return GUM_SIX.get(m.group(1), ''), '금강 폴더번호(6-x 보정)'
        if not in_six:
            m = re.search(r'/([1-5])-(\d{1,2})\.?\s', p)
            if m:
                return '%s_%d' % (m.group(1), int(m.group(2))), '금강 폴더번호'
    for code, pat in KW:
        if re.search(pat, p, re.I):
            return code, '키워드'
    if re.search(PAINT, p, re.I):
        return '(도장·도금)', '타업종'
    if declared and re.match(r'^INJ\.\d+_\d+$', declared) and declared != 'INJ.1_35':
        return declared.replace('INJ.', ''), '추출기 추정'
    return '', '미분류'


def use_of(path, content):
    name = path.split('/')[-1]
    if re.search(JUNK, name, re.I):
        return '무관'
    hits = []
    if re.search(FORM, name, re.I):
        hits.append('양식')
    if re.search(CRIT, name, re.I):
        hits.append('기준값')
    if re.search(REC, name, re.I):
        hits.append('실적예시')
    if not hits:
        body = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        if re.search(FORM, body[:1200], re.I):
            hits.append('양식(본문)')
        elif re.search(REC, body[:1200], re.I):
            hits.append('실적예시(본문)')
    return '+'.join(hits) if hits else '미판정'


def main():
    allf = json.load(open(BASE + '/sq_extract_all.json'))
    rows = []
    for f in allf:
        code, how = item_of(f['path'], f.get('item', ''))
        content = f.get('content_trunc') or f.get('content') or ''
        rows.append({
            'item': code, 'how': how, 'use': use_of(f['path'], content),
            'top': f['top'], 'ext': f['ext'], 'size': f['size'], 'path': f['path'],
        })
    out = BASE + '/18_SQ참고자료_파일색인.tsv'
    with open(out, 'w') as fh:
        fh.write('item\t근거\t쓸모\t출처\t확장자\t크기\t경로\n')
        for r in sorted(rows, key=lambda r: (r['item'] or 'zz', r['path'])):
            fh.write('%s\t%s\t%s\t%s\t%s\t%d\t%s\n' % (
                r['item'] or '(미분류)', r['how'], r['use'], r['top'],
                r['ext'], r['size'], r['path']))
    print('색인 작성:', out, len(rows), '행')
    print('항목별 건수:', dict(collections.Counter(r['item'] or '(미분류)' for r in rows).most_common()))
    print('쓸모별 건수:', dict(collections.Counter(r['use'] for r in rows).most_common()))
    print('근거별 건수:', dict(collections.Counter(r['how'] for r in rows).most_common()))
    json.dump(rows, open(BASE + '/sq_index_rows.json', 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
