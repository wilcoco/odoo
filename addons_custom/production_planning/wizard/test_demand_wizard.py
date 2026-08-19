from odoo import api, fields, models, _
from odoo.exceptions import UserError


class TestDemandWizard(models.TransientModel):
    """양산 전 테스트용 수요 수기 입력 — 완제품(BOM 보유) 품번을 날짜별로 입력해
    수요 원장(production.demand, source='test')에 기록한다.
    새 수요 경로를 만들지 않고 원장에 기록 (addons_custom/CLAUDE.md 원장 규칙)."""
    _name = "production.test.demand.wizard"
    _description = "테스트 수요 입력"

    line_ids = fields.One2many("production.test.demand.wizard.line", "wizard_id", string="수요 라인")
    note = fields.Char(string="메모", default=lambda self: _("양산 전 테스트 수요"))

    def action_create(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("수요 라인을 입력하세요."))
        Demand = self.env["production.demand"]
        created = Demand
        for line in self.line_ids:
            created |= Demand.create({
                "demand_date": line.demand_date,
                "product_id": line.product_id.id,
                "quantity": line.quantity,
                "demand_type": "daily",
                "source": "test",
                "notes": self.note,
            })
        return {
            "type": "ir.actions.act_window",
            "name": _("테스트 수요"),
            "res_model": "production.demand",
            "view_mode": "list,form",
            "domain": [("id", "in", created.ids)],
        }


class TestDemandWizardLine(models.TransientModel):
    _name = "production.test.demand.wizard.line"
    _description = "테스트 수요 라인"

    wizard_id = fields.Many2one("production.test.demand.wizard", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "product.product", string="완제품", required=True,
        domain=[("product_tmpl_id.bom_ids", "!=", False)],
        help="BOM 이 등록된 완제품만 선택 가능 (BOM 전개로 사출 부품 수요가 계산됨)")
    demand_date = fields.Date(string="수요일", required=True,
                              default=fields.Date.context_today)
    quantity = fields.Float(string="수량", required=True, default=100.0)
