from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IatfLayoutInspection(models.Model):
    _name = "iatf.layout.inspection"
    _description = "레이아웃 검사 (IATF 16949 §8.6.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    inspection_date = fields.Date(string="검사일", default=fields.Date.today, required=True)

    # ── 제품 정보 ──
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    customer_id = fields.Many2one("res.partner", string="고객", tracking=True)
    drawing_number = fields.Char(string="도면 번호")
    drawing_revision = fields.Char(string="도면 개정")

    # ── 검사 유형 ──
    inspection_type = fields.Selection(
        [
            ("layout", "레이아웃 검사 (전 치수)"),
            ("functional", "기능 시험"),
            ("both", "레이아웃 + 기능 시험"),
        ],
        string="검사 유형", required=True, default="layout",
    )
    frequency = fields.Char(string="검사 주기", help="예: 연 1회, 고객 요구 시")
    last_inspection_date = fields.Date(string="이전 검사일")

    # ── 샘플 ──
    sample_size = fields.Integer(string="샘플 수량", default=1)
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")

    # ── 검사 항목 ──
    line_ids = fields.One2many("iatf.layout.inspection.line", "inspection_id", string="검사 항목")
    total_characteristics = fields.Integer(string="총 항목 수", compute="_compute_stats", store=True)
    pass_count = fields.Integer(string="합격 수", compute="_compute_stats", store=True)
    fail_count = fields.Integer(string="불합격 수", compute="_compute_stats", store=True)

    # ── 판정 ──
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("conditional", "조건부 합격")],
        string="판정 결과", tracking=True,
    )

    # ── 담당자 ──
    inspector_id = fields.Many2one("res.users", string="검사원",
                                    default=lambda self: self.env.user, tracking=True)
    approved_by = fields.Many2one("res.users", string="승인자")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("inspecting", "검사 중"),
            ("decided", "판정 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids.result")
    def _compute_stats(self):
        for rec in self:
            lines = rec.line_ids
            rec.total_characteristics = len(lines)
            rec.pass_count = len(lines.filtered(lambda l: l.result == "pass"))
            rec.fail_count = len(lines.filtered(lambda l: l.result == "fail"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.layout.inspection") or _("New")
        return super().create(vals_list)

    def action_start(self):
        self.write({"state": "inspecting"})

    def action_decide(self):
        for rec in self:
            if not rec.result:
                raise UserError(_("판정 결과를 입력해 주세요."))
        self.write({"state": "decided"})

    def action_close(self):
        self.write({"state": "closed"})


class IatfLayoutInspectionLine(models.Model):
    _name = "iatf.layout.inspection.line"
    _description = "레이아웃 검사 항목"
    _order = "sequence, id"

    inspection_id = fields.Many2one(
        "iatf.layout.inspection", string="검사", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    balloon_number = fields.Char(string="풍선 번호")
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("geometric", "기하공차"), ("surface", "표면"),
         ("functional", "기능"), ("material", "재질"), ("visual", "외관")],
        string="항목 유형", default="dimensional",
    )
    special_characteristic = fields.Selection(
        [("none", "없음"), ("cc", "CC"), ("sc", "SC")],
        string="특별 특성", default="none",
    )
    nominal = fields.Char(string="규격 / 기준값")
    tolerance = fields.Char(string="공차")
    measured_value = fields.Char(string="측정값")
    deviation = fields.Char(string="편차")
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="판정", default="pass",
    )
    measurement_tool = fields.Char(string="측정기")
    notes = fields.Char(string="비고")
