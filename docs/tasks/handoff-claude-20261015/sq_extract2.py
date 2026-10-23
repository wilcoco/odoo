#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SQ 참고자료 2차 추출(배정 085). 읽기 전용 — 원본 폴더에 쓰지 않는다.

1차(sq_extract.py) 한계를 닫는다:
  · zip 10건: CP949 파일명 복원 후 작업 폴더에 해제하고 내용 추출(경로 `zip명/내부경로`)
  · xls 50건: xlrd 2.0.2 의 BIFF8 유니코드 strict 디코딩 버그 → `unicode` 를 errors='replace' 로
    교체해 재추출(치환 문자 U+FFFD 가 생길 수 있음 — `lenient` 플래그로 표시)
  · 요약 절단: 1차는 파일당 1.8KB. 여기서는 전체 시트·전체 행을 20KB 까지 읽는다.
  · 구형 ppt/doc/hwp: 변환기(soffice)가 없다 → OLE 텍스트 긁기로 가능한 만큼, 안 되면 사유 기록.
"""
import os
import re
import sys
import json
import glob
import zipfile
import subprocess
import collections

SRC = os.path.expanduser('~/Downloads/OneDrive_2_10-19-2026')
WORK = sys.argv[1] if len(sys.argv) > 1 else '/tmp/sq2'
MAXC = 20000
SKIP_DIRS = ('에스콘 로고 CI',)

# ── xlrd 관대 디코딩 패치 (1차 미해석 50건의 단일 원인)
import xlrd
import xlrd.biffh
import xlrd.book
import xlrd.sheet
import xlrd.compdoc


def _lenient(b, enc=None, *a):
    if enc is None:
        return str(b)
    try:
        return bytes(b).decode(enc, 'replace')
    except Exception:
        return ''


for _m in (xlrd.biffh, xlrd.book, xlrd.sheet, xlrd.compdoc):
    _m.unicode = _lenient


def clean(s):
    return re.sub(r'\s+', ' ', str(s)).strip()


def rows_of(cells):
    vals = [clean(v) for v in cells if v not in (None, '')]
    return ' | '.join(vals)[:400] if vals else ''


def read_xlsx(p):
    import openpyxl
    wb = openpyxl.load_workbook(p, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        rr = []
        for row in ws.iter_rows(values_only=True):
            line = rows_of(row)
            if line:
                rr.append(line)
        out.append({'sheet': ws.title, 'rows': rr})
    wb.close()
    return out


def read_xls(p):
    wb = xlrd.open_workbook(p)
    out = []
    for si in range(wb.nsheets):
        ws = wb.sheet_by_index(si)
        rr = []
        for r in range(ws.nrows):
            line = rows_of([ws.cell_value(r, c) for c in range(ws.ncols)])
            if line:
                rr.append(line)
        out.append({'sheet': ws.name, 'rows': rr})
    return out


def read_pptx(p):
    from pptx import Presentation
    prs = Presentation(p)
    texts = []
    for i, s in enumerate(prs.slides):
        t, imgs = [], 0
        for sh in s.shapes:
            if sh.has_text_frame and clean(sh.text_frame.text):
                t.append(clean(sh.text_frame.text))
            if getattr(sh, 'has_table', False) and sh.has_table:
                for r in sh.table.rows:
                    line = ' | '.join(clean(c.text) for c in r.cells if clean(c.text))
                    if line:
                        t.append(line)
            if sh.shape_type is not None and 'PICTURE' in str(sh.shape_type):
                imgs += 1
        tag = '[slide %d]' % (i + 1) + (' (이미지 %d)' % imgs if imgs else '')
        texts.append(tag + ' ' + ' / '.join(t) if t else tag + ' (텍스트 없음·이미지 %d)' % imgs)
    return texts


def read_pdf(p):
    r = subprocess.run(['pdftotext', '-layout', '-q', p, '-'],
                       capture_output=True, timeout=120)
    txt = r.stdout.decode('utf-8', 'replace')
    lines = [clean(x) for x in txt.splitlines() if clean(x)]
    return lines


def read_ole_text(p):
    """구형 ppt/doc: 변환기가 없다. OLE 스트림에서 UTF-16/CP949 문자열만 긁는다(부분 복원)."""
    data = open(p, 'rb').read()
    out = []
    for m in re.finditer(rb'(?:[\x20-\x7e\xa1-\xfe]\x00){6,}', data):   # UTF-16LE
        s = clean(m.group().decode('utf_16_le', 'replace'))
        if len(s) >= 4:
            out.append(s)
    if not out:
        for m in re.finditer(rb'(?:[\xb0-\xc8][\xa1-\xfe]|[\x20-\x7e]){8,}', data):  # CP949
            s = clean(m.group().decode('cp949', 'replace'))
            if len(s) >= 6:
                out.append(s)
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:400]


def extract(p):
    """반환 (content, note)."""
    ext = p.rsplit('.', 1)[-1].lower()
    try:
        if ext in ('xlsx', 'xlsm'):
            return read_xlsx(p), ''
        if ext == 'xls':
            head = open(p, 'rb').read(4)
            if head == b'PK\x03\x04':
                return read_xlsx(p), '확장자 xls 이나 실제 xlsx'
            return read_xls(p), 'lenient 디코딩(치환 가능)'
        if ext in ('pptx', 'pptm', 'ppsx'):
            return read_pptx(p), ''
        if ext == 'pdf':
            lines = read_pdf(p)
            return lines, ('' if lines else '텍스트 레이어 없음(스캔 추정) → 사람 확인')
        if ext in ('ppt', 'doc'):
            t = read_ole_text(p)
            return t, 'OLE 텍스트 긁기(부분 복원·표 구조 소실)' if t else '구형 OLE·변환기 없음 → 사람 확인'
        if ext == 'hwp':
            t = read_ole_text(p)
            return t, 'HWP OLE 긁기(부분)' if t else 'HWP·변환기 없음 → 사람 확인'
        if ext == 'txt':
            return [clean(x) for x in open(p, encoding='utf-8', errors='replace')][:400], ''
        if ext in ('png', 'jpg', 'jpeg'):
            return [], '이미지 → 사람 확인'
        if ext in ('mp4', 'eml'):
            return [], '%s → 분석 대상 아님' % ext
        return [], '미지원 확장자'
    except Exception as e:
        return [], '추출 오류: %s' % str(e)[:120]


def walk_sources():
    """(논리경로, 실제경로, 출처구분)"""
    for root, dirs, files in os.walk(SRC):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn.startswith('.') or fn == 'Icon\r':
                continue
            full = os.path.join(root, fn)
            yield os.path.relpath(full, SRC), full, '원본'
    uz = os.path.join(WORK, 'unzip')
    for root, dirs, files in os.walk(uz):
        for fn in files:
            if fn.startswith('.') or '__MACOSX' in root:
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, uz)
            parts = rel.split('/', 1)
            yield '%s.zip/%s' % (parts[0], parts[1] if len(parts) > 1 else ''), full, 'zip내부'


def main():
    out, notes = [], collections.Counter()
    for rel, full, kind in walk_sources():
        content, note = extract(full)
        truncated = False
        while len(json.dumps(content, ensure_ascii=False)) > MAXC:
            truncated = True
            if isinstance(content, list) and content:
                last = content[-1]
                if isinstance(last, dict) and last.get('rows'):
                    last['rows'] = last['rows'][:max(0, len(last['rows']) - 5)]
                    if not last['rows']:
                        content.pop()
                else:
                    content.pop()
            else:
                content = []
                break
        out.append({
            'path': rel, 'src_kind': kind, 'ext': rel.rsplit('.', 1)[-1].lower(),
            'size': os.path.getsize(full), 'note': note, 'truncated': truncated,
            'content': content,
        })
        notes[note or 'OK'] += 1
    json.dump(out, open(os.path.join(WORK, 'sq_extract2.json'), 'w'), ensure_ascii=False)
    print('2차 추출 %d 건 → %s/sq_extract2.json' % (len(out), WORK))
    for k, v in notes.most_common():
        print('  %4d %s' % (v, k))


if __name__ == '__main__':
    main()
