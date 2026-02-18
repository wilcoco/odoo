from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfProcessInspection(models.Model):
    _name = "iatf.process.inspection"
    _description = "공정검사 / 최종검사 (IATF 16949 §8.6)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    inspection_stage = fields.Selection(
        [
            ("ipqc", "공정검사 (IPQC)"),
            ("final", "최종검사 (FQC)"),
            ("oqc", "출하검사 (OQC)"),
        ],
        string="검사 단계", required=True, default="ipqc", tracking=True,
    )
    inspection_date = fields.Datetime(string="검사 일시", default=fields.Datetime.now, required=True)

    # ── 제조 참조 ──
    production_id = fields.Many2one("mrp.production", string="제조 오더", tracking=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")

    # ── 수량 ──
    quantity_produced = fields.Float(string="생산 수량")
    quantity_inspected = fields.Float(string="검사 수량", required=True)
    quantity_accepted = fields.Float(string="합격 수량")
    quantity_rejected = fields.Float(string="불합격 수량")
    defect_rate = fields.Float(string="불량률 (%)", compute="_compute_defect_rate", store=True)

    # ── 검사 항목 ──
    line_ids = fields.One2many("iatf.process.inspection.line", "inspection_id", string="검사 항목")

    # ── 판정 ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("conditional", "조건부 합격"),
            ("fail", "불합격"),
            ("hold", "보류"),
        ],
        string="판정 결과", tracking=True,
    )
    disposition = fields.Selection(
        [
            ("ship", "출하 승인"),
            ("rework", "재작업"),
            ("scrap", "폐기"),
            ("sort", "전수 선별"),
            ("hold", "보류"),
            ("concession", "특채"),
        ],
        string="처리 방법", tracking=True,
    )

    # ── 담당자 ──
    inspector_id = fields.Many2one("res.users", string="검사원",
                                    default=lambda self: self.env.user, tracking=True)
    approved_by = fields.Many2one("res.users", string="승인자")

    # ── 연결 ──
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="연결된 부적합")
    control_plan_id = fields.Many2one("iatf.control.plan", string="관리계획서 참조")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
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

    @api.depends("quantity_inspected", "quantity_rejected")
    def _compute_defect_rate(self):
        for rec in self:
            if rec.quantity_inspected:
                rec.defect_rate = (rec.quantity_rejected / rec.quantity_inspected) * 100.0
            else:
                rec.defect_rate = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.process.inspection") or _("New")
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
                rec._auto_quarantine_lot()

    def _auto_create_nc(self):
        """불합격 시 부적합 자동 생성"""
        if self.nonconformity_id:
            return
        nc = self.env["iatf.nonconformity"].create({
            "title": _("공정검사 불합격: %s - %s") % (self.name, self.product_id.name),
            "nc_type": "process",
            "severity": "major",
            "problem_description": "<p>공정검사 %s 불합격 자동 생성<br/>제품: %s<br/>MO: %s<br/>불량률: %s%%</p>" % (
                self.name, self.product_id.name,
                self.production_id.name if self.production_id else "-",
                round(self.defect_rate, 2)),
            "product_id": self.product_id.id,
            "production_id": self.production_id.id if self.production_id else False,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "quantity_affected": self.quantity_produced,
            "quantity_rejected": self.quantity_rejected or 0,
        })
        self.nonconformity_id = nc.id
        self.message_post(body=_("부적합 %s 자동 생성됨") % nc.name)

    def _auto_quarantine_lot(self):
        """불합격 로트를 격리 위치로 이동"""
        if not self.lot_id:
            return
        quarantine_loc = self.env.ref("stock.stock_location_scrapped", raise_if_not_found=False)
        if not quarantine_loc:
            return
        quants = self.env["stock.quant"].search([
            ("lot_id", "=", self.lot_id.id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ])
        for quant in quants:
            self.env["stock.move"].create({
                "name": _("PQC 불합격 격리: %s") % self.name,
                "product_id": quant.product_id.id,
                "product_uom_qty": quant.quantity,
                "product_uom": quant.product_id.uom_id.id,
                "location_id": quant.location_id.id,
                "location_dest_id": quarantine_loc.id,
                "origin": self.name,
            })._action_confirm()._action_done()
        if quants:
            self.message_post(body=_("로트 %s 격리 위치로 자동 이동됨") % self.lot_id.name)

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("공정검사 불합격: %s") % self.product_id.name,
            "nc_type": "process",
            "severity": "major",
            "problem_description": "<p>%s</p>" % (self.notes or ""),
            "product_id": self.product_id.id,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }


class IatfProcessInspectionLine(models.Model):
    _name = "iatf.process.inspection.line"
    _description = "공정검사 항목"
    _order = "sequence, id"

    inspection_id = fields.Many2one(
        "iatf.process.inspection", string="검사", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("visual", "외관"), ("functional", "기능"),
         ("performance", "성능"), ("other", "기타")],
        string="항목 유형", default="dimensional",
    )
    special_characteristic = fields.Selection(
        [("none", "없음"), ("cc", "CC - 중요"), ("sc", "SC - 특별")],
        string="특별 특성", default="none",
    )
    specification = fields.Char(string="규격 / 공차")
    measurement_method = fields.Char(string="측정 방법 / 게이지")
    measured_value = fields.Char(string="측정값")
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="판정", default="pass",
    )
    notes = fields.Char(string="비고")
