#!/usr/bin/env python3
"""애드온 XML 에서 **메뉴 전체 경로**를 추출한다.

메뉴가 재구성되면 UAT 문서의 【경로】 표기가 전부 어긋난다.
문서를 손으로 고치면 또 틀리므로, 코드에서 경로를 뽑아 대조한다.

사용:
  python3 menu_paths.py <애드온루트> [<애드온루트> ...]            # 전체 경로 목록
  python3 menu_paths.py <애드온루트> --find 승인번호 사일로 ...     # 이름으로 검색
  python3 menu_paths.py <루트A> --diff <루트B>                     # 두 트리의 경로 변화
"""
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def collect(roots):
    """{xmlid: (name, parent_xmlid, module)} 수집."""
    menus = {}
    for root in roots:
        root = Path(root)
        for xml in root.rglob("*.xml"):
            if any(p in xml.parts for p in ("node_modules", ".git", "static")):
                continue
            module = _module_of(xml, root)
            try:
                tree = ET.parse(xml)
            except ET.ParseError:
                continue
            for el in tree.iter():
                if el.tag == "menuitem":
                    xid, name = el.get("id"), el.get("name")
                    parent = el.get("parent")
                    if not xid:
                        continue
                    menus[_full(xid, module)] = (
                        name or "", _full(parent, module) if parent else None, module)
                elif el.tag == "record" and el.get("model") == "ir.ui.menu":
                    xid = el.get("id")
                    name = parent = None
                    for f in el.findall("field"):
                        if f.get("name") == "name":
                            name = (f.text or "").strip()
                        elif f.get("name") == "parent_id":
                            parent = f.get("ref")
                    if xid:
                        menus[_full(xid, module)] = (
                            name or "", _full(parent, module) if parent else None, module)
    return menus


def _module_of(xml_path, root):
    rel = xml_path.relative_to(root).parts
    return rel[0] if rel else root.name


def _full(xid, module):
    return xid if "." in xid else f"{module}.{xid}"


def paths(menus):
    """{xmlid: '최상위 › 하위 › 메뉴명'}"""
    out = {}

    def walk(xid, seen):
        if xid in out:
            return out[xid]
        if xid not in menus or xid in seen:
            return None
        name, parent, _mod = menus[xid]
        seen = seen | {xid}
        if parent:
            up = walk(parent, seen)
            full = f"{up} › {name}" if up else name
        else:
            full = name
        out[xid] = full
        return full

    for xid in menus:
        walk(xid, frozenset())
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    if "--diff" in args:
        i = args.index("--diff")
        old_roots, new_roots = args[:i], args[i + 1:]
        old, new = paths(collect(old_roots)), paths(collect(new_roots))
        moved = [(x, old[x], new[x]) for x in old if x in new and old[x] != new[x]]
        gone = [(x, old[x]) for x in old if x not in new]
        added = [(x, new[x]) for x in new if x not in old]
        print(f"== 경로가 바뀐 메뉴 {len(moved)}개")
        for x, o, n in sorted(moved, key=lambda t: t[2]):
            print(f"  {o}\n    → {n}   [{x}]")
        print(f"\n== 사라진 메뉴 {len(gone)}개")
        for x, o in sorted(gone, key=lambda t: t[1]):
            print(f"  {o}   [{x}]")
        print(f"\n== 새로 생긴 메뉴 {len(added)}개")
        for x, n in sorted(added, key=lambda t: t[1]):
            print(f"  {n}   [{x}]")
        return 0

    if "--find" in args:
        i = args.index("--find")
        roots, terms = args[:i], args[i + 1:]
        pt = paths(collect(roots))
        for term in terms:
            rx = re.compile(term, re.I)
            hits = sorted(p for p in pt.values() if p and rx.search(p))
            print(f"== '{term}' — {len(hits)}건")
            for h in hits:
                print(f"  {h}")
        return 0

    for p in sorted(v for v in paths(collect(args)).values() if v):
        print(p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
