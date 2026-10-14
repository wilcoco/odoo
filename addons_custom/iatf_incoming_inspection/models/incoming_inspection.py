from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfIncomingInspection(models.Model):
    _name = "iatf.incoming.inspection"
    _description = "수입검사 (IATF 16949 §8.6.4)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
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
    quantity_inspected = fields.Float(string="실제 검사(샘플) 수량", required=True)
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

    # ── 항목별 판정 요약 (회사양식: 외관/치수/재질) ──
    visual_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="외관 판정", tracking=True,
    )
    dimension_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="치수 판정", tracking=True,
    )
    material_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="재질 판정 (Mill Sheet)", tracking=True,
        help="자재 성적서(Mill Sheet) 확인 결과",
    )
    defect_rate = fields.Float(
        string="입고 불합격 비율 (%)", compute="_compute_defect_rate", store=True,
        digits=(5, 2), help="불합격 처분 수량 / 실제 입고 수량 × 100 (샘플 불량률과 구별)",
    )
    supplier_cert_no = fields.Char(string="성적서 번호", help="협력사 시험성적서 번호")

    # ── 판정 ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("conditional", "조건부 합격"),
            ("partial", "부분 합격 (잔량 검사대기)"),
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
                                    tracking=True)
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
        records = super().create(vals_list)
        records._load_inspection_criteria()
        return records

    def _load_inspection_criteria(self):
        """[R144 정책 #9/#12] 제품(·협력업체) 검사 기준 마스터를 **한 번 넣어 두면** 수입검사가
        생성될 때 검사 항목·샘플링 기준·샘플 수량·Ac/Re 를 물려받는다. 이미 항목이 있으면 건드리지 않는다.
        협력업체 전용 기준이 있으면 그것을, 없으면 공통(협력업체 미지정) 기준을 쓴다."""
        Criteria = self.env["iatf.inspection.criteria"].sudo()
        for rec in self:
            if rec.line_ids or not rec.product_id:
                continue
            crit = Criteria.search([("product_id", "=", rec.product_id.id), ("active", "=", True),
                                    ("supplier_id", "=", rec.supplier_id.id)], order="sequence, id")
            if not crit:
                crit = Criteria.search([("product_id", "=", rec.product_id.id), ("active", "=", True),
                                        ("supplier_id", "=", False)], order="sequence, id")
            if not crit:
                continue
            rec.line_ids = [(0, 0, {
                "sequence": c.sequence, "characteristic_name": c.characteristic_name,
                "characteristic_type": c.characteristic_type or "other",
                "specification": c.specification, "measurement_method": c.measurement_method,
            }) for c in crit]
            head = crit.filtered("sampling_plan")[:1] or crit[:1]
            vals = {}
            if not rec.sampling_plan and head.sampling_plan:
                vals["sampling_plan"] = head.sampling_plan
            if not rec.sample_size and head.sample_size:
                vals.update({"sample_size": head.sample_size, "accept_number": head.accept_number,
                             "reject_number": head.reject_number})
            if vals:
                rec.write(vals)
            rec.message_post(body=_("검사 기준 마스터에서 검사 항목 %d개를 적재했습니다.", len(crit)))

    @api.depends("quantity_rejected", "quantity_received")
    def _compute_defect_rate(self):
        for rec in self:
            rec.defect_rate = (
                rec.quantity_rejected / rec.quantity_received * 100.0
                if rec.quantity_received else 0.0
            )



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
        string="판정",
    )
    notes = fields.Char(string="비고")
