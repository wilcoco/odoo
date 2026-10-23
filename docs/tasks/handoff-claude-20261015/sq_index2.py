#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQ 참고자료 색인 v2(배정 085). 2차 추출(sq_extract2.json, 전체 시트·zip 내부 포함)으로 재분류.

1차 대비 바뀐 점
  · 입력이 전체 본문(20KB)이라 **본문 키워드 매핑**이 실제로 동작한다(1차는 1.8KB 요약).
  · zip 내부 187건 포함.
  · **판(version) 구분**: 협력사 자료의 항목 번호는 HKMC 평가서 **Ver5.1(47항목)** 기준이고,
    우리 마스터(`SQ평가서_PL사출_MASTER.xls`)는 **48항목 구판**이다. 폴더 번호는 Ver5.1 로 읽고
    `V51_TO_MASTER` 로 우리 코드로 변환한다.
"""
import os
import re
import sys
import json
import collections
import unicodedata as U

BASE = os.path.dirname(os.path.abspath(__file__))

# Ver5.1(협력사·실제 평가서) → 우리 MASTER 48항목 코드
V51_TO_MASTER = {
    '1_1': '1_1', '1_2': '1_2', '1_3': '1_3',
    '1_4': '(없음:취약시간대)',            # Ver5.1 에만 있다
    '1_5': '1_4', '1_6': '1_5', '1_7': '1_6', '1_8': '1_7', '1_9': '1_8', '1_10': '1_9',
    '6_1': '6_1', '6_2': '6_2', '6_3': '6_3', '6_4': '6_4', '6_5': '6_5',
    '6_6': '6_7', '6_7': '6_8', '6_8': '6_9', '6_9': '6_10',
    '6_10': '6_12', '6_11': '6_13', '6_12': '6_14',
}
# 영역 2~5 는 두 판이 동일하다.

PAINT = r'도장|도금|도료|막후|막두께|도막|프라이머|클리어|제전|스프레이|피도물'

KW = [
    ('2_3', r'한도견본|한도 ?견본|마스터견본|한도품|한도 ?설정'),
    ('2_4', r'신뢰성|정기검사|정기 ?시험|내구|촉진|열충격|항온항습|중금속|재질 ?시험'),
    ('3_3', r'건조시간|건조조건|건조온도|건조장치|건조기|호퍼|핫에어|드라이어|제습'),
    ('3_4', r'배합기|분쇄기|크러셔|칼날|분쇄품|분쇄재'),
    ('1_9', r'분쇄|배합|스크랩|재생재|리그라인드'),
    ('3_5', r'지그|JIG|치구|컨베어|스키드'),
    ('5_4', r'용기|파레트|팔레트|대차|도시락|적재함|단프라|납입용기'),
    ('6_3', r'검사협정|도면 ?일치|도면기준|ISIR'),
    ('6_14', r'정성품질|정성 ?품질'),
    ('6_6', r'교안|품질교육|교육계획|사내교육|품질 ?의식'),
    ('6_11', r'수평전개|수평 ?전개'),
    ('6_13', r'누락 ?방지|공정누락|풀프루프|포카요케|Fool ?Proof|F/P'),
    ('1_7', r'초물|초중종|초기 ?허용'),
    ('2_5', r'검교정|교정|계측기|검사구|게이지'),
    ('6_9', r'조도'),
    ('6_10', r'3정|5행|5S'),
    ('6_12', r'REWORK|리워크|재작업'),
    ('6_1', r'안전|위험성평가|유해|보호구|LOTO|소방|피난'),
    ('6_5', r'자격|인증서|숙련도|직무능력|다기능'),
    ('5_1', r'LOT ?추적|추적성|로트추적|바코드'),
    ('4_6', r'예열'),
    ('4_7', r'금형 ?온도|금형온도'),
    ('4_2', r'금형 ?세척|세척'),
    ('4_1', r'금형 ?점검|타발|숏트|SHOT|금형 ?일상'),
    ('4_3', r'금형 ?보전|금형 ?등급|시사출|금형관리방안|정비'),
    ('4_4', r'금형 ?보관'),
    ('4_5', r'금형 ?이관'),
    ('1_5', r'수분 ?관리|수분관리|함수율'),
    ('1_8', r'수분 ?함유|수분측정|수분 ?검증'),
    ('1_4', r'원단위|중량 ?관리|실중량|중량 ?마스터'),
    ('1_6', r'성형조건|사출조건|조건표|작동유|냉각수'),
    ('2_7', r'자주검사|패트롤|순회'),
    ('2_8', r'완제품 ?검사|출하검사'),
    ('2_9', r'융착'),
    ('2_1', r'수입검사|밀시트|M/?S'),
    ('2_2', r'수입검사 ?대장'),
    ('2_6', r'R&R'),
    ('1_1', r'관리계획서|FMEA|작업표준|표준류|Control ?Plan|CONTROL ?PLAN'),
    ('3_1', r'일상점검'),
    ('3_2', r'정기점검|예방보전|예방보존|TBM|년간설비'),
    ('6_2', r'4M|설계변경|설변'),
    ('6_4', r'내부감사|시정조치|경영검토|품질경영|조직도|업무분장'),
    ('6_7', r'부적합|격리|식별'),
    ('6_8', r'품질실적|PPM|불량률'),
    ('5_2', r'보관장|창고'),
    ('5_3', r'입고품 ?식별|식별 ?관리'),
    ('1_2', r'가동중단|재가동'),
    ('1_3', r'외국인|현지어'),
]

FORM = r'기준서|표준서|절차서|점검표|체크|대장|양식|서식|LIST|리스트|관리표|일보|일지|계획서|규정|매뉴얼|지침|프로세스|FLOW'
CRIT = r'기준서|조건표|규격|스펙|SPEC|한도|관리기준|기준표|조건|설정서'
REC = r'성적서|실적|이력|결과|현황|측정|기록|점검결과|교정성적|보고서'
JUNK = r'\.(png|jpg|jpeg|mp4|zip|eml)$|로고|CI$|사진|~\$'

n = lambda s: U.normalize('NFC', s)


def folder_item(p):
    """폴더 번호(=Ver5.1 체계) → 우리 코드. 반환 (코드, 근거, 외부코드)."""
    if p.startswith('에스콘 SQ 자료/'):
        m = re.search(r'/(\d)[-_](\d{1,2})\s', p)
        if m:
            ext = '%s_%d' % (m.group(1), int(m.group(2)))
            return V51_TO_MASTER.get(ext, ext), '에스콘 폴더(Ver5.1→MASTER)', ext
    if p.startswith('G금강 SQ 참고/'):
        in_six = '/6. 품질경영체계/' in p
        m = re.search(r'/(6-\d{1,2})\.?\s', p)
        if m:
            ext = m.group(1).replace('-', '_')
            return V51_TO_MASTER.get(ext, ''), '금강 폴더(Ver5.1→MASTER)', ext
        if not in_six:
            m = re.search(r'/([1-5])-(\d{1,2})\.?\s', p)
            if m:
                ext = '%s_%d' % (m.group(1), int(m.group(2)))
                return V51_TO_MASTER.get(ext, ext), '금강 폴더(Ver5.1→MASTER)', ext
    return '', '', ''


def item_of(path, content):
    p = n(path)
    # 로고/CI 자산은 분석 대상이 아니다(1차 추출기의 SKIP_DIRS 가 macOS NFD 경로라 걸러지지 않았다).
    if p.startswith('에스콘 로고 CI'):
        return '(로고·CI)', '분석 대상 아님', ''
    code, how, ext = folder_item(p)
    if code:
        return code, how, ext
    body = p + ' ' + json.dumps(content, ensure_ascii=False)[:6000]
    for c, pat in KW:
        if re.search(pat, body, re.I):
            return c, ('파일명' if re.search(pat, p, re.I) else '본문'), ''
    if re.search(PAINT, body, re.I):
        return '(도장·도금)', '타업종', ''
    return '', '미판정', ''


def use_of(path, content, note):
    name = n(path).split('/')[-1]
    if n(path).startswith('에스콘 로고 CI'):
        return '무관(로고·CI)'
    if re.search(JUNK, name, re.I):
        return '무관'
    if note.startswith('추출 오류') or '사람 확인' in note:
        return '미해석'
    hits = []
    body = json.dumps(content, ensure_ascii=False)[:8000]
    for pat, tag in ((FORM, '양식'), (CRIT, '기준값'), (REC, '실적예시')):
        if re.search(pat, name, re.I) or re.search(pat, body, re.I):
            hits.append(tag)
    return '+'.join(hits) if hits else '미판정'


def main():
    work = sys.argv[1]
    data = json.load(open(os.path.join(work, 'sq_extract2.json')))
    rows = []
    for f in data:
        code, how, ext = item_of(f['path'], f['content'])
        rows.append({
            'item': code, 'how': how, 'ext_code': ext,
            'use': use_of(f['path'], f['content'], f['note']),
            'src': f['src_kind'], 'ftype': f['ext'], 'size': f['size'],
            'note': f['note'], 'trunc': f['truncated'], 'path': n(f['path']),
        })
    out = os.path.join(BASE, '18_SQ참고자료_파일색인.tsv')
    with open(out, 'w') as fh:
        fh.write('item\t근거\t외부코드(Ver5.1)\t쓸모\t출처\t확장자\t크기\t추출비고\t절단\t경로\n')
        for r in sorted(rows, key=lambda r: (r['item'] or 'zz', r['path'])):
            fh.write('%s\t%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s\t%s\n' % (
                r['item'] or '(미판정)', r['how'], r['ext_code'], r['use'], r['src'],
                r['ftype'], r['size'], r['note'] or 'OK', 'Y' if r['trunc'] else '', r['path']))
    print('색인 v2:', out, len(rows), '행')
    print('항목별:', dict(collections.Counter(r['item'] or '(미판정)' for r in rows).most_common()))
    print('쓸모별:', dict(collections.Counter(r['use'] for r in rows).most_common()))
    print('근거별:', dict(collections.Counter(r['how'] for r in rows).most_common()))
    json.dump(rows, open(os.path.join(work, 'sq_index2_rows.json'), 'w'), ensure_ascii=False)


if __name__ == '__main__':
    main()
