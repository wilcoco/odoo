from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfCustomerComplaint(models.Model):
    _name = "iatf.customer.complaint"
    _description = "Customer Complaint (IATF 16949 §10.2.6)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="불만 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    complaint_type = fields.Selection(
        [
            ("quality", "품질 결함"),
            ("delivery", "납기 문제"),
            ("warranty", "보증 청구"),
            ("field_return", "현장 반품"),
            ("ntr", "NTF (문제없음)"),
            ("other", "기타"),
        ],
        string="불만 유형", required=True, default="quality", tracking=True,
    )
    severity_level = fields.Selection(
        [
            ("critical", "치명적 (안전/리콜)"),
            ("major", "중대"),
            ("minor", "경미"),
        ],
        string="심각도", default="major", tracking=True,
    )

    # ── Customer ──
    customer_id = fields.Many2one("res.partner", string="고객", required=True, tracking=True)
    customer_ref = fields.Char(string="고객 참조번호")
    received_date = fields.Date(string="접수일", default=fields.Date.today, required=True)
    response_due_date = fields.Date(string="답변 기한", tracking=True)

    # ── Product / Lot ──
    product_id = fields.Many2one("product.product", string="제품")
    part_number = fields.Char(string="부품 번호")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    quantity_affected = fields.Float(string="영향 수량")
    quantity_returned = fields.Float(string="반품 수량")

    # ── Problem description ──
    problem_description = fields.Html(string="문제 설명", required=True)
    failure_mode = fields.Char(string="고장 모드")
    customer_impact = fields.Html(string="고객 영향")

    # ── Containment ──
    containment_action = fields.Html(string="즉시 격리 조치")
    containment_date = fields.Date(string="격리 일자")

    # ── Root cause & corrective action ──
    root_cause = fields.Html(string="근본원인 분석")
    corrective_action = fields.Html(string="시정 조치")
    preventive_action = fields.Html(string="예방 조치")
    verification_result = fields.Html(string="유효성 검증")

    # ── Links ──
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="연결된 부적합/8D")

    # ── Costs ──
    cost_sorting = fields.Float(string="선별 비용")
    cost_rework = fields.Float(string="재작업 비용")
    cost_scrap = fields.Float(string="폐기 비용")
    cost_freight = fields.Float(string="긴급 운송 비용")
    cost_warranty = fields.Float(string="보증 비용")
    cost_total = fields.Float(string="총 비용", compute="_compute_cost_total", store=True)

    # ── Status ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("new", "신규"),
            ("containment", "격리"),
            ("analysis", "원인분석"),
            ("corrective", "시정조치"),
            ("verification", "검증"),
            ("closed", "종료"),
        ],
        string="상태", default="new", tracking=True,
    )

    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("cost_sorting", "cost_rework", "cost_scrap", "cost_freight", "cost_warranty")
    def _compute_cost_total(self):
        for rec in self:
            rec.cost_total = (rec.cost_sorting + rec.cost_rework + rec.cost_scrap
                              + rec.cost_freight + rec.cost_warranty)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.customer.complaint") or _("New")
        return super().create(vals_list)

    def action_containment(self):
        self.write({"state": "containment"})
        for rec in self:
            if not rec.nonconformity_id:
                rec._auto_create_complaint_nc()

    def _auto_create_complaint_nc(self):
        """고객불만 접수 → NC 자동 생성 (L4-3 폐쇄 루프)"""
        NC = self.env.get("iatf.nonconformity")
        if NC is None:
            return
        nc = NC.create({
            "title": _("고객불만: %s") % self.title,
            "nc_type": "customer",
            "severity": "major" if self.severity_level in ("critical", "major") else "minor",
            "problem_description": self.problem_description,
            "product_id": self.product_id.id if self.product_id else False,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "partner_id": self.customer_id.id if self.customer_id else False,
        })
        self.nonconformity_id = nc.id
        self.message_post(body=_("고객불만 → 부적합 %s 자동 생성됨. 8D CAPA 진행 필요.") % nc.name)

    def action_analysis(self):
        self.write({"state": "analysis"})

    def action_corrective(self):
        self.write({"state": "corrective"})

    def action_verification(self):
        self.write({"state": "verification"})

    def action_close(self):
        """종료 시 연결된 NC의 CAPA 유효성 검증 확인 (L4-3)"""
        for rec in self:
            if rec.nonconformity_id and rec.nonconformity_id.state != "closed":
                from odoo.exceptions import UserError as UE
                raise UE(_(
                    "연결된 부적합(%s)이 아직 종결되지 않았습니다.\n"
                    "CAPA 유효성 검증 완료 후 고객불만을 종결하세요.") % rec.nonconformity_id.name)
        self.write({"state": "closed"})

    # ── 출하 역추적 ──
    related_picking_ids = fields.Many2many(
        "stock.picking", string="관련 출하 전표", readonly=True,
    )
    related_picking_count = fields.Integer(compute="_compute_picking_count")

    def _compute_picking_count(self):
        for rec in self:
            rec.related_picking_count = len(rec.related_picking_ids)

    def action_traceback_shipments(self):
        """로트/제품 기반으로 해당 고객에게 출하한 전표를 자동 역추적"""
        self.ensure_one()
        domain = [
            ("picking_type_code", "=", "outgoing"),
            ("state", "=", "done"),
            ("partner_id", "=", self.customer_id.id),
        ]
        if self.lot_id:
            domain.append(("move_ids.lot_ids", "in", [self.lot_id.id]))
        elif self.product_id:
            domain.append(("move_ids.product_id", "=", self.product_id.id))
        else:
            return

        pickings = self.env["stock.picking"].search(domain)
        self.related_picking_ids = [(6, 0, pickings.ids)]
        msg = _("출하 역추적 완료: %d건의 출하 전표 발견") % len(pickings)
        self.message_post(body=msg)

        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", pickings.ids)],
            "name": _("관련 출하 전표"),
        }

    def action_view_related_pickings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "view_mode": "list,form",
            "domain": [("id", "in", self.related_picking_ids.ids)],
            "name": _("관련 출하 전표"),
        }

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("Customer Complaint: %s") % self.title,
            "nc_type": "customer",
            "severity": self.severity_level if self.severity_level != "critical" else "major",
            "problem_description": self.problem_description,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }
