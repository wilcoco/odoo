from odoo import api, fields, models, _

# 전사 단위 기준 마스터 — "기준을 정하는 메뉴를 만들고 그 기준에 따라 모든 영역에서
# 정합" 원칙. 정책은 데이터(이 마스터), 검증은 점검 버튼(위반 드릴다운)으로.
# 배경 실사례: BOM 원단위를 kg 로 입력하면 소수 2자리 정밀도로 0.784→0.78 저장,
# 자재소요 왜곡(마스터배치 0.00) — g 입력 기준을 정하고 위반을 기계로 잡는다.

AREA = [
    ("stock_material", "원재료 재고·구매 단위"),
    ("bom_weight", "BOM 원단위(중량) 입력 단위"),
    ("measure_weight", "실측 중량 기록 단위"),
    ("product_count", "사출품·완제품 수량 단위"),
]


class EsconUomPolicy(models.Model):
    _name = "escon.uom.policy"
    _description = "단위 기준 정책"
    _order = "sequence, id"

    sequence = fields.Integer(default=10)
    area = fields.Selection(AREA, string="영역", required=True)
    category_id = fields.Many2one("uom.category", string="단위 카테고리", required=True)
    standard_uom_id = fields.Many2one(
        "uom.uom", string="기준 단위", required=True,
        domain="[('category_id', '=', category_id)]",
        help="이 영역의 데이터가 따라야 하는 단위")
    note = fields.Char(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [("area_uniq", "unique(area, company_id)", "영역별 기준은 하나입니다.")]

    @api.model
    def _policy(self, area):
        return self.search([("area", "=", area)], limit=1)


class EsconUomAudit(models.TransientModel):
    """정합 점검 — 기준 정책 대비 위반 데이터 검출 + 드릴다운."""
    _name = "escon.uom.audit"
    _description = "단위 정합 점검"

    bom_weight_violations = fields.Integer(string="BOM 중량 라인 단위 위반", readonly=True)
    material_uom_violations = fields.Integer(string="원재료 재고 단위 위반", readonly=True)
    precision_warning = fields.Char(string="소수점 정밀도", readonly=True)
    result_note = fields.Text(readonly=True)

    def _bom_weight_violation_ids(self):
        policy = self.env["escon.uom.policy"]._policy("bom_weight")
        if not policy:
            return []
        return self.env["mrp.bom.line"].search([
            ("product_uom_id.category_id", "=", policy.category_id.id),
            ("product_uom_id", "!=", policy.standard_uom_id.id),
        ]).ids

    def _material_violation_ids(self):
        policy = self.env["escon.uom.policy"]._policy("stock_material")
        if not policy:
            return []
        return self.env["product.product"].search([
            ("uom_id.category_id", "=", policy.category_id.id),
            ("uom_id", "!=", policy.standard_uom_id.id),
        ]).ids

    def action_audit(self):
        self.ensure_one()
        bom_ids = self._bom_weight_violation_ids()
        mat_ids = self._material_violation_ids()
        prec = self.env["decimal.precision"].search(
            [("name", "=", "Product Unit of Measure")], limit=1)
        digits = prec.digits if prec else 2
        self.write({
            "bom_weight_violations": len(bom_ids),
            "material_uom_violations": len(mat_ids),
            "precision_warning": _(
                "Product UoM 소수점 %d자리 — 기준 단위(g 등 정수계)를 지키면 충분. "
                "kg 로 원단위 입력 시 3자리째부터 잘림") % digits,
            "result_note": _(
                "위반 0이 정합 상태입니다. 위반 건은 '보기'로 열어 기준 단위로 "
                "변환·수정하세요. 정책 변경은 '단위 기준 정책' 메뉴에서."),
        })
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "new", "name": _("단위 정합 점검")}

    def action_view_bom_violations(self):
        return {"type": "ir.actions.act_window", "name": _("BOM 중량 라인 단위 위반"),
                "res_model": "mrp.bom.line", "view_mode": "list,form",
                "domain": [("id", "in", self._bom_weight_violation_ids())]}

    def action_view_material_violations(self):
        return {"type": "ir.actions.act_window", "name": _("원재료 재고 단위 위반"),
                "res_model": "product.product", "view_mode": "list,form",
                "domain": [("id", "in", self._material_violation_ids())]}
