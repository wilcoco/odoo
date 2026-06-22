from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfShippingInspection(models.Model):
    _name = "iatf.shipping.inspection"
    _description = "출하검사 (IATF 16949 §8.6) — 포장·라벨 검사"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    shipping_date = fields.Date(string="출하일", default=fields.Date.today, required=True)

    # ── 제품 / 출하 정보 ──
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    quantity = fields.Float(string="출하 수량")
    destination = fields.Char(string="도착지", help="납품처 / 배송 목적지 (회사양식 destination)")
    partner_id = fields.Many2one("res.partner", string="고객", domain="[('customer_rank','>',0)]", tracking=True)
    picking_id = fields.Many2one("stock.picking", string="출하 전표", tracking=True)

    # ── 항목별 판정 (회사양식: 외관/치수/포장/라벨) ──
    visual_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="외관 판정", tracking=True,
    )
    dimension_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="치수 판정", tracking=True,
    )
    packaging_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="포장 검사", tracking=True, help="회사양식 packagingCheck",
    )
    label_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="라벨 검사", tracking=True, help="회사양식 labelCheck",
    )

    # ── 종합 판정 ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("conditional", "조건부 합격"),
            ("fail", "불합격"),
        ],
        string="판정 결과", tracking=True,
    )

    # ── 담당자 ──
    inspector_id = fields.Many2one("res.users", string="검사원",
                                    default=lambda self: self.env.user, tracking=True)
    approved_by = fields.Many2one("res.users", string="승인자")

    # ── 연결 ──
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="연결된 부적합")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("inspecting", "검사 중"),
            ("decided", "판정 완료"),
            ("closed", "종료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.shipping.inspection") or _("New")
        return super().create(vals_list)

    def action_start_inspection(self):
        self.write({"state": "inspecting"})

    def action_decide(self):
        for rec in self:
            if not rec.result:
                raise UserError(_("판정 결과를 입력해 주세요."))
            rec.write({"state": "decided"})
            if rec.result == "fail":
                rec._auto_create_nc()

    def _auto_create_nc(self):
        """불합격 시 부적합 자동 생성"""
        if self.nonconformity_id:
            return
        nc = self.env["iatf.nonconformity"].create({
            "title": _("출하검사 불합격: %s - %s") % (self.name, self.product_id.name),
            "nc_type": "internal",
            "severity": "major",
            "problem_description": "<p>출하검사 %s 불합격 자동 생성<br/>제품: %s<br/>도착지: %s<br/>수량: %s</p>" % (
                self.name, self.product_id.name, self.destination or "-", self.quantity),
            "product_id": self.product_id.id,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "quantity_affected": self.quantity,
        })
        self.nonconformity_id = nc.id
        self.message_post(body=_("부적합 %s 자동 생성됨") % nc.name)

    def action_create_nc(self):
        self.ensure_one()
        self._auto_create_nc()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": self.nonconformity_id.id,
            "view_mode": "form",
            "target": "current",
        }

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})
