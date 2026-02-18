from odoo import api, fields, models, _


class IatfOutsourceOrder(models.Model):
    _name = "iatf.outsource.order"
    _description = "외주 발주/입고 기록"
    _inherit = ["mail.thread"]
    _order = "create_date desc"

    name = fields.Char(
        string="발주 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    process_id = fields.Many2one("iatf.outsource.process", string="외주공정", required=True, tracking=True)
    supplier_id = fields.Many2one(
        "res.partner", string="외주업체",
        related="process_id.supplier_id", store=True, readonly=True,
    )
    purchase_id = fields.Many2one("purchase.order", string="구매 오더")
    product_id = fields.Many2one("product.product", string="제품", required=True)
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")

    # ── 수량 ──
    quantity_sent = fields.Float(string="출고 수량", required=True)
    send_date = fields.Date(string="출고일", default=fields.Date.today)
    quantity_received = fields.Float(string="입고 수량")
    receive_date = fields.Date(string="입고일")
    quantity_rejected = fields.Float(string="불합격 수량")

    # ── 검사 ──
    inspection_result = fields.Selection(
        [("pass", "합격"), ("conditional", "조건부 합격"), ("fail", "불합격")],
        string="검사 결과", tracking=True,
    )
    certificate_received = fields.Boolean(string="성적서 수령")
    certificate_ok = fields.Boolean(string="성적서 적합")

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user)
    notes = fields.Text(string="비고")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("sent", "출고됨"),
            ("received", "입고됨"),
            ("inspected", "검사 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.outsource.order") or _("New")
        return super().create(vals_list)

    def action_send(self):
        self.write({"state": "sent"})

    def action_receive(self):
        self.write({"state": "received", "receive_date": fields.Date.today()})
        for rec in self:
            rec._auto_create_outsource_iqc()

    def _auto_create_outsource_iqc(self):
        """외주 입고 시 수입검사(IQC) 자동 생성"""
        IQC = self.env.get("iatf.incoming.inspection")
        if IQC is None:
            return
        iqc = IQC.create({
            "supplier_id": self.supplier_id.id,
            "product_id": self.product_id.id,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "quantity_received": self.quantity_received or self.quantity_sent,
            "quantity_inspected": self.quantity_received or self.quantity_sent,
            "inspection_type": "sampling",
        })
        self.message_post(body=_("외주 입고 수입검사 %s 자동 생성됨") % iqc.name)

    def action_inspect(self):
        self.write({"state": "inspected"})

    def action_close(self):
        self.write({"state": "closed"})
