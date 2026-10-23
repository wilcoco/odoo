#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQ 서류 일람 467건 → 시스템 출력물 매핑(배정 089). 읽기 전용(8070 쓰기 0).

입력: 8070 `sq.doc.requirement` 467 + `sq.item` 84(t3.sq 로 읽음) · 18 색인 · sq-union CSV
출력: sq-union/doc_outputs.csv
"""
import os
import re
import csv
import json
import collections
import unicodedata as U

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = BASE + '/sq-union'
W = '/private/tmp/claude-501/-Users-jhungsoohong-cams-odoo/e09056bf-6214-4b5d-bf3d-6ec964b77580/scratchpad/sq2'
nfc = lambda s: U.normalize('NFC', s or '')

# 8070 에 **실제로 존재·읽기 확인된** 모델 (fields_get/search_count 로 확인)
EXISTS = {
    'iatf.control.plan', 'iatf.fmea', 'iatf.nonconformity', 'iatf.document',
    'iatf.incoming.inspection', 'iatf.process.inspection', 'iatf.shipping.inspection',
    'iatf.packaging.spec', 'iatf.calibration.record', 'iatf.equipment',
    'iatf.change.request', 'iatf.corrective.action', 'iatf.audit',
    'iatf.check.sheet', 'iatf.check.record', 'escon.lot.trace', 'escon.line.snapshot',
    'mrp.production', 'mrp.workorder', 'stock.lot', 'stock.picking', 'stock.quant',
    'product.supplierinfo', 'vendor.part.price', 'br.intake', 'supplier.asn',
    'iatf.approval.request', 'iatf.control.plan.line', 'iatf.process.inspection.line',
    # 089 회신(091) 정정 — t3.sq `search_count` 로 재확인한 기존 모델
    'iatf.mold.check', 'iatf.mold.maintenance', 'iatf.mold.temp.log', 'iatf.mold.tryout',
    'iatf.training.record', 'iatf.competence.matrix', 'iatf.daily.check', 'iatf.blend.log',
    'iatf.environment.check',   # 권한만 없고 모델은 존재
}
# 기존 QWeb 리포트 3개
REPORTS = {'iatf.nonconformity': '8D Report', 'iatf.control.plan': 'Control Plan',
           'iatf.fmea': 'FMEA Worksheet'}

#: (정규식, output_type, source_model, report_kind, period, owner_role)
#  output_type: 보고서 / 조회·내보내기 / 업로드 / 외부·수동
R = [
    (r'관리계획서|Control ?Plan', '보고서', 'iatf.control.plan', 'QWeb PDF', '발생시', '품질'),
    (r'FMEA', '보고서', 'iatf.fmea', 'QWeb PDF', '발생시', '품질'),
    (r'8D|부적합 ?보고|시정조치|NCR', '보고서', 'iatf.nonconformity', 'QWeb PDF', '발생시', '품질'),
    (r'수입검사.*(성적서|일지|대장|기록)|수입검사표', '보고서', 'iatf.incoming.inspection', 'QWeb PDF', '발생시', '품질'),
    (r'수입검사', '보고서', 'iatf.incoming.inspection', 'QWeb PDF', '발생시', '품질'),
    (r'출하검사|완제품 ?검사|완성품 ?검사', '보고서', 'iatf.shipping.inspection', 'QWeb PDF', '일', '품질'),
    (r'자주검사|공정검사|패트롤|순회|초중종|초물|중물|종물', '보고서', 'iatf.process.inspection', 'QWeb PDF', '일', '품질'),
    (r'검교정|교정 ?성적|계측기|검사구|게이지', '보고서', 'iatf.calibration.record', 'QWeb PDF', '월', '품질'),
    (r'포장 ?(사양|규격)', '조회·내보내기', 'iatf.packaging.spec', 'xlsx', '발생시', '품질'),
    (r'4M|설계변경|설변|변경 ?통보', '보고서', 'iatf.change.request', 'QWeb PDF', '발생시', '품질'),
    (r'내부심사|경영검토|감사', '보고서', 'iatf.audit', 'QWeb PDF', '월', '품질'),
    (r'LOT ?추적|추적성|로트 ?이력', '조회·내보내기', 'escon.lot.trace', 'xlsx', '발생시', '품질'),
    (r'작업일보|생산일보|조업일보|융착작업일보', '보고서', 'mrp.production', 'QWeb PDF', '일', '생산'),
    (r'작업지시|공정 ?실적', '조회·내보내기', 'mrp.workorder', 'xlsx', '일', '생산'),
    (r'입고|출하 ?전표|납품서|거래명세', '조회·내보내기', 'stock.picking', 'xlsx', '발생시', '자재'),
    (r'재고 ?(현황|조사)|보관장 ?현황', '조회·내보내기', 'stock.quant', 'xlsx', '월', '자재'),
    (r'공급사 ?(현황|목록)|협력사 ?(현황|목록)|supplierinfo', '조회·내보내기', 'product.supplierinfo', 'xlsx', '발생시', '구매'),
    (r'단가|계약 ?단가', '조회·내보내기', 'vendor.part.price', 'xlsx', '발생시', '구매'),
    (r'BR|수신 ?이력', '조회·내보내기', 'br.intake', 'xlsx', '발생시', '생산'),
    (r'ASN|입고 ?예정', '조회·내보내기', 'supplier.asn', 'xlsx', '발생시', '구매'),
    # ── 점검표·일지 계열: iatf.check.sheet/record 가 이미 있다
    (r'일상점검', '보고서', 'iatf.daily.check', 'QWeb PDF', '일', '생산'),
    (r'점검표|점검 ?시트|체크 ?시트|점검일지|점검 ?기록|정기점검|점검 ?대장',
     '보고서', 'iatf.check.sheet / iatf.check.record', 'QWeb PDF', '일', '생산'),
    (r'일지|일보', '보고서', 'iatf.check.record', 'QWeb PDF', '일', '생산'),
    # ── 신규 모델 필요(19 §1 P1)
    (r'한도견본|마스터 ?견본|한도품', '보고서', 'sq.limit.sample(신규)', 'QWeb PDF', '월', '품질'),
    (r'정기검사|신뢰성', '보고서', 'sq.periodic.test.plan(신규)', 'xlsx', '월', '품질'),
    (r'건조|호퍼|드라이', '보고서', 'sq.dryer.check(신규)', 'QWeb PDF', '일', '생산'),
    (r'배합|혼합', '보고서', 'iatf.blend.log', 'QWeb PDF', '일', '생산'),
    (r'분쇄', '보고서', 'sq.grind.sample(신규)', 'QWeb PDF', '일', '생산'),
    (r'지그|JIG|치구|컨베어', '보고서', 'jig.inspect.record(신규)', 'QWeb PDF', '월', '보전'),
    (r'용기|파레트|팔레트|대차|단프라', '보고서', 'sq.container.standard / .clean(신규)', 'xlsx', '월', '자재'),
    (r'검사협정|도면 ?일치|도면', '보고서', 'sq.drawing.agreement(신규)', 'QWeb PDF', '월', '품질'),
    (r'정성품질', '보고서', 'sq.quality.spirit.check(신규)', 'QWeb PDF', '월', '품질'),
    (r'금형.*(온도|표면온도)', '보고서', 'iatf.mold.temp.log', 'QWeb PDF', '일', '보전'),
    (r'금형.*(시사출|T/?O|트라이)', '보고서', 'iatf.mold.tryout', 'QWeb PDF', '발생시', '생산기술'),
    (r'금형.*(보전|세척|수리|정비|SPARE)', '보고서', 'iatf.mold.maintenance', 'QWeb PDF', '발생시', '보전'),
    (r'금형', '보고서', 'iatf.mold.check', 'QWeb PDF', '일', '보전'),
    (r'조도|정전기|이물 ?방지|온습도', '보고서', 'iatf.environment.check', 'QWeb PDF', '월', '생산기술'),
    (r'3정|5행|5S', '보고서', 'sq.5s.check(신규)', 'QWeb PDF', '월', '생산'),
    (r'REWORK|리워크|재작업', '보고서', 'iatf.nonconformity(재작업 분기)', 'QWeb PDF', '발생시', '품질'),
    (r'자격|인증서|숙련도|직무능력|다기능', '보고서', 'iatf.competence.matrix', 'xlsx', '월', '인사'),
    (r'교육|교안', '보고서', 'iatf.training.record', 'QWeb PDF', '월', '인사'),
    (r'위험성 ?평가|안전|보호구|피난|소화', '보고서', 'sq.safety.risk(신규)', 'QWeb PDF', '월', '생산기술'),
    (r'SPC|관리도|X-?R', '보고서', 'sq.spc(신규)', 'xlsx', '월', '품질'),
    (r'품질실적|PPM|불량률', '조회·내보내기', 'iatf.nonconformity 집계', 'xlsx', '월', '품질'),
    # ── 업로드 문서
    (r'기준서|표준서|절차서|규정|매뉴얼|지침|프로세스|조직도|업무분장|LAY ?-?OUT|레이아웃',
     '업로드', 'iatf.document', '-', '발생시', '품질'),
    (r'협정서|승인서|성적서\(외부\)|밀시트|M/?S|TDS|시험성적서', '업로드', 'iatf.document', '-', '발생시', '품질'),
    # ── 외부·수동
    (r'사진|실물|현장 ?게시|라벨|표지판|식별표', '외부·수동', '-', '-', '발생시', '생산'),
]


def classify(name):
    for pat, ot, sm, rk, pe, ow in R:
        if re.search(pat, name, re.I):
            return ot, sm, rk, pe, ow
    return '업로드', 'iatf.document', '-', '발생시', '품질'


def main():
    D = json.load(open(W + '/sq_docs_8070.json'))
    docs, item_by_id = D['docs'], {int(k): v for k, v in D['item_by_id'].items()}
    idx = json.load(open(W + '/sq_index2_rows.json'))
    # 외부 지적이 걸린 union_code (P0 판정용)
    # P0 = **에스콘 자체 지도점검**(우리 지적)에 걸린 항목. 타사 지적은 P1 로 둔다
    # (199건이 거의 모든 항목을 덮어 P0 가 무의미해지는 것을 피한다).
    own, other = set(), set()
    for r in csv.DictReader(open(OUT + '/external_findings.csv')):
        if not r['union_code']:
            continue
        (own if r['source'] == '에스콘지도점검' else other).add(r['union_code'])
    # 항목 배점
    pts = {}
    for r in csv.DictReader(open(OUT + '/union_items.csv')):
        try:
            pts[r['union_code']] = float(r['points_union'].split()[0] or 0)
        except Exception:
            pts[r['union_code']] = 0.0
    # 18 색인에서 참조 양식 찾기 (양식/기준값 쓸모만)
    forms = [r for r in idx if '양식' in r['use'] or '기준값' in r['use']]

    def ref_form(name):
        toks = [t for t in re.split(r'[\s/·,()]+', name) if len(t) >= 2][:3]
        hits = []
        for r in forms:
            p = nfc(r['path'])
            if all(t in p for t in toks[:1]) and any(t in p for t in toks):
                hits.append(p)
            if len(hits) >= 2:
                break
        return ' ; '.join(h[-72:] for h in hits)

    rows = []
    for d in docs:
        name = nfc(d['name'])
        codes = [item_by_id.get(i, '') for i in d['item_ids']]
        ucodes = sorted({c.replace('INJ.', '').replace('ASM.', '') for c in codes if c})
        ot, sm, rk, pe, ow = classify(name)
        base_model = sm.split('(')[0].split(' / ')[0].strip()
        exists = base_model in EXISTS
        rep = REPORTS.get(base_model, '')
        new_needed = 'Y' if (ot == '보고서' and not rep) else 'N'
        if ot in ('업로드', '외부·수동'):
            new_needed = 'N'
            rk = '-'
        p0 = any(c in own for c in ucodes)
        hi = any(c in other for c in ucodes) or any(pts.get(c, 0) >= 30 for c in ucodes)
        rows.append({
            'doc_id': d['id'], 'name': name,
            'item_codes': ' '.join(sorted(set(codes))),
            'output_type': ot,
            'source_model': sm + ('' if exists or '신규' in sm or sm == '-' else ' [8070 미확인]'),
            'existing_report': ('Y:' + rep) if rep else 'N',
            'reference_form': ref_form(name),
            'new_report_needed': new_needed,
            'report_kind': rk, 'period': pe, 'owner_role': ow,
            'priority': 'P0' if p0 else ('P1' if hi else 'P2'),
            'note': ('구매 준비' if d['kind'] == 'purchase' else '')
                    + ('' if exists or '신규' in sm or sm in ('-', 'iatf.document') else ' 모델 없음→신규'),
        })
    hdr = ['doc_id', 'name', 'item_codes', 'output_type', 'source_model', 'existing_report',
           'reference_form', 'new_report_needed', 'report_kind', 'period', 'owner_role',
           'priority', 'note']
    with open(OUT + '/doc_outputs.csv', 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=hdr)
        w.writeheader()
        w.writerows(rows)
    print('doc_outputs.csv %d행' % len(rows))
    print('output_type:', dict(collections.Counter(r['output_type'] for r in rows)))
    print('신규 리포트 필요:', sum(1 for r in rows if r['new_report_needed'] == 'Y'))
    print('기존 리포트 활용:', sum(1 for r in rows if r['existing_report'].startswith('Y')))
    print('우선순위:', dict(collections.Counter(r['priority'] for r in rows)))
    print('모델 없음→신규:', sum(1 for r in rows if '신규' in r['source_model']))
    print('참조 양식 붙은 행:', sum(1 for r in rows if r['reference_form']))
    mods = collections.Counter(r['source_model'] for r in rows if r['new_report_needed'] == 'Y')
    print('\n신규 리포트 모델별 상위:')
    for m, c in mods.most_common(14):
        print('   %-44s %d' % (m, c))


if __name__ == '__main__':
    main()
