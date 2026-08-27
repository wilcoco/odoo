import re

from odoo import _, fields, models

# 승인번호가 여러 필드로 흩어져 있던 것을 정본 하나로 모은다.
#   정본  : kr_approval_number  (중복차단 제약 · 반입/매칭 위저드 · 체크리스트가 물려 있음)
#   원본번호: kr_origin_number   (수정세금계산서의 당초 승인번호)
#   이관 대상: x_escon_tax_approval_no (스튜디오로 만든 중복 필드), ref(업체 청구서 참조)
#
# ref 는 오두 표준 "공급자 청구서 번호" 필드라 승인번호 전용이 아니다 →
# **국세청 승인번호 형식일 때만** 옮긴다 (거래처 청구서 번호를 잘못 옮기지 않도록).

STUDIO_FIELD = "x_escon_tax_approval_no"
# 국세청 승인번호: 8자리-8자리-8자리 (하이픈 유무·공백 허용)
APPROVAL_RE = re.compile(r"^\s*\d{8}\s*-?\s*[0-9A-Za-z]{8}\s*-?\s*[0-9A-Za-z]{8}\s*$")


class KrApprovalNumberMerge(models.TransientModel):
    """승인번호 필드 통합 — 미리보기 후 적용."""

    _name = "kr.approval.number.merge"
    _description = "세금계산서 승인번호 필드 통합"

    source = fields.Selection(
        [("studio", "세금계산서승인번호 (스튜디오 필드)"),
         ("ref", "업체 청구서 참조 (ref) — 승인번호 형식인 것만"),
         ("both", "둘 다 (스튜디오 우선)")],
        string="가져올 곳", required=True, default="both")
    overwrite = fields.Boolean(
        string="이미 값이 있어도 덮어쓰기", default=False,
        help="끄면 정본(세금계산서 승인번호)이 비어 있는 전표만 채웁니다(권장).")
    apply_now = fields.Boolean(
        string="실제로 적용", default=False,
        help="끄면 **미리보기만** 합니다. 결과를 확인한 뒤 켜고 다시 실행하세요.")
    result = fields.Text(string="결과", readonly=True)

    # ── 도우미 ────────────────────────────────────────────────
    def _has_studio_field(self):
        return STUDIO_FIELD in self.env["account.move"]._fields

    def _candidate_value(self, mv):
        """이 전표에서 가져올 승인번호 (없으면 None)."""
        if self.source in ("studio", "both") and self._has_studio_field():
            v = (mv[STUDIO_FIELD] or "").strip() if mv[STUDIO_FIELD] else ""
            if v:
                return v, STUDIO_FIELD
        if self.source in ("ref", "both"):
            v = (mv.ref or "").strip()
            if v and APPROVAL_RE.match(v):
                return v, "ref"
        return None, None

    # ── 실행 ──────────────────────────────────────────────────
    def action_run(self):
        self.ensure_one()
        Move = self.env["account.move"]
        domain = [("move_type", "in", ("in_invoice", "in_refund", "out_invoice", "out_refund"))]
        moves = Move.search(domain)

        # 이미 쓰이고 있는 승인번호 (충돌 검사용)
        taken = {}
        for mv in moves:
            if mv.kr_approval_number:
                taken.setdefault(mv.kr_approval_number, mv.id)

        to_write, conflicts, skipped_filled, no_source, ref_not_approval = [], [], 0, 0, 0
        for mv in moves:
            val, src = self._candidate_value(mv)
            if not val:
                if self.source in ("ref", "both") and mv.ref and not APPROVAL_RE.match(mv.ref.strip()):
                    ref_not_approval += 1
                else:
                    no_source += 1
                continue
            if mv.kr_approval_number and not self.overwrite:
                if mv.kr_approval_number != val:
                    skipped_filled += 1
                continue
            owner = taken.get(val)
            if owner and owner != mv.id:
                conflicts.append(_("%(name)s: %(val)s 은(는) 다른 전표(id %(o)s)가 이미 사용")
                                 % {"name": mv.name or mv.id, "val": val, "o": owner})
                continue
            to_write.append((mv, val, src))
            taken[val] = mv.id

        lines = [
            _("대상 전표 %d건 검사") % len(moves),
            _("스튜디오 필드 존재: %s") % (_("예") if self._has_studio_field() else _("아니오 — 이 서버엔 없음")),
            "",
            _("옮길 수 있는 건수: %d") % len(to_write),
            _("정본에 이미 값이 있어 건너뜀: %d") % skipped_filled,
            _("승인번호 형식이 아니어서 제외된 ref: %d") % ref_not_approval,
            _("가져올 값이 없음: %d") % no_source,
            _("충돌(중복 승인번호): %d") % len(conflicts),
        ]
        if conflicts:
            lines.append("\n" + _("[충돌 목록 — 수동 확인 필요]"))
            lines += conflicts[:30]
            if len(conflicts) > 30:
                lines.append(_("...외 %d건") % (len(conflicts) - 30))

        if not self.apply_now:
            lines.insert(0, _("※ 미리보기입니다. 실제 반영하려면 '실제로 적용'을 켜고 다시 실행하세요.\n"))
            self.result = "\n".join(lines)
            return self._reopen()

        done = 0
        for mv, val, src in to_write:
            try:
                mv.write({"kr_approval_number": val})
                done += 1
            except Exception as e:  # noqa: BLE001 — 한 건 실패가 전체를 막지 않게
                conflicts.append(_("%s: 반영 실패 — %s") % (mv.name or mv.id, str(e)[:100]))
        lines.append("\n" + _("→ 실제 반영 %d건 완료") % done)
        if self._has_studio_field():
            lines.append(_("※ 이관 후 스튜디오 필드(%s)는 화면에서 숨기거나 삭제하세요 "
                           "— 이 위저드는 다른 개발자가 만든 필드를 지우지 않습니다.") % STUDIO_FIELD)
        self.result = "\n".join(lines)
        return self._reopen()

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name,
                "res_id": self.id, "view_mode": "form",
                "views": [[False, "form"]], "target": "new"}
