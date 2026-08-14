from odoo import api, models, _


class ResPartner(models.Model):
    """리포트 #3: 거래처 사업자등록번호(vat) 중복 저장 전 안내."""
    _inherit = "res.partner"

    @api.onchange("vat")
    def _onchange_vat_dup_warning(self):
        if not self.vat:
            return
        dup = self.search([("vat", "=", self.vat), ("id", "!=", self._origin.id or 0)], limit=1)
        if dup:
            return {"warning": {
                "title": _("사업자등록번호 중복"),
                "message": _(
                    "동일한 사업자등록번호의 거래처가 이미 등록되어 있습니다: %(n)s\n"
                    "기존 거래처를 사용할지 확인해주세요. (지점/개인사업 중복 등 정당한 경우에만 계속)"
                ) % {"n": dup.display_name},
            }}

    @api.onchange("name")
    def _onchange_name_similar_warning(self):
        """유사 거래처명 안내 (캠스/주식회사 캠스/CAMS 분산 방지)."""
        if not self.name or len(self.name) < 2:
            return
        key = self.name.replace(" ", "").replace("주식회사", "").replace("(주)", "").lower()
        if len(key) < 2:
            return
        cands = self.search([("name", "ilike", key[:4]), ("id", "!=", self._origin.id or 0)], limit=3)
        cands = cands.filtered(
            lambda p: key in p.name.replace(" ", "").replace("주식회사", "").replace("(주)", "").lower()
            or p.name.replace(" ", "").replace("주식회사", "").replace("(주)", "").lower() in key)
        if cands:
            return {"warning": {
                "title": _("유사 거래처명 존재"),
                "message": _("유사한 거래처가 이미 있습니다: %(n)s\n기존 거래처 사용 여부를 확인해주세요.")
                % {"n": ", ".join(cands.mapped("display_name"))},
            }}
