from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfIncomingInspection(models.Model):
    _name = "iatf.incoming.inspection"
    _description = "수입검사 (IATF 16949 §8.6.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    picking_id = fields.Many2one("stock.picking", string="입고 전표", tracking=True)
    purchase_id = fields.Many2one("purchase.order", string="구매 오더", tracking=True)
    supplier_id = fields.Many2one("res.partner", string="협력업체", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    inspection_date = fields.Date(string="검사일", default=fields.Date.today, required=True)

    # ── 제품 정보 ──
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    quantity_received = fields.Float(string="입고 수량", required=True)
    quantity_inspected = fields.Float(string="검사 수량", required=True)
    quantity_accepted = fields.Float(string="합격 수량")
    quantity_rejected = fields.Float(string="불합격 수량")

    # ── 검사 기준 ──
    inspection_type = fields.Selection(
        [
            ("full", "전수 검사"),
            ("sampling", "샘플링 검사"),
            ("skip", "검사 생략 (면제)"),
            ("certificate", "성적서 확인"),
        ],
        string="검사 유형", required=True, default="sampling",
    )
    sampling_plan = fields.Char(string="샘플링 기준", help="예: AQL 0.65, Level II")
    sample_size = fields.Integer(string="샘플 크기")
    accept_number = fields.Integer(string="합격 판정 개수 (Ac)")
    reject_number = fields.Integer(string="불합격 판정 개수 (Re)")

    # ── 검사 항목 ──
    line_ids = fields.One2many("iatf.incoming.inspection.line", "inspection_id", string="검사 항목")

    # ── 판정 ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("conditional", "조건부 합격"),
            ("fail", "불합격"),
        ],
        string="판정 결과", tracking=True,
    )
    disposition = fields.Selection(
        [
            ("accept", "입고 승인"),
            ("return", "반품"),
            ("rework", "재작업 요청"),
            ("sort", "전수 선별"),
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

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.incoming.inspection") or _("New")
        return super().create(vals_list)

    def action_start_inspection(self):
        self.write({"state": "inspecting"})

    def action_decide(self):
        for rec in self:
            if not rec.result:
                raise UserError(_("판정 결과를 입력해 주세요."))
        self.write({"state": "decided"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("수입검사 불합격: %s") % self.product_id.name,
            "nc_type": "supplier",
            "severity": "major",
            "problem_description": "<p>%s</p>" % (self.notes or ""),
            "product_id": self.product_id.id,
            "partner_id": self.supplier_id.id,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }


class IatfIncomingInspectionLine(models.Model):
    _name = "iatf.incoming.inspection.line"
    _description = "수입검사 항목"
    _order = "sequence, id"

    inspection_id = fields.Many2one(
        "iatf.incoming.inspection", string="검사", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("visual", "외관"), ("functional", "기능"),
         ("material", "재질"), ("other", "기타")],
        string="항목 유형", default="dimensional",
    )
    specification = fields.Char(string="규격 / 공차")
    measurement_method = fields.Char(string="측정 방법")
    measured_value = fields.Char(string="측정값")
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="판정", default="pass",
    )
    notes = fields.Char(string="비고")
