from odoo import api, fields, models, _


class IatfCustomerProperty(models.Model):
    _name = "iatf.customer.property"
    _description = "고객재산 관리 (IATF 16949 §8.5.3)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "customer_id, name"

    name = fields.Char(
        string="관리 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    customer_id = fields.Many2one("res.partner", string="고객", required=True, tracking=True)
    title = fields.Char(string="품명/명칭", required=True, tracking=True)

    property_type = fields.Selection(
        [
            ("mold", "금형/치공구"),
            ("material", "지급 자재"),
            ("drawing", "도면"),
            ("specification", "규격서/사양서"),
            ("software", "소프트웨어"),
            ("gauge", "게이지/측정기"),
            ("packaging", "포장재/용기"),
            ("equipment", "설비/장비"),
            ("ip", "지적 재산"),
            ("other", "기타"),
        ],
        string="재산 유형", required=True, default="mold", tracking=True,
    )

    # ── 식별 ──
    customer_code = fields.Char(string="고객 관리 번호")
    serial_number = fields.Char(string="시리얼 번호")
    description = fields.Html(string="상세 설명")

    # ── 입고/관리 ──
    receive_date = fields.Date(string="입고일")
    received_by = fields.Many2one("res.users", string="입고 확인자")
    quantity = fields.Float(string="수량", default=1)
    uom = fields.Char(string="단위")
    condition_on_receipt = fields.Selection(
        [("good", "양호"), ("damaged", "손상"), ("incomplete", "불완전")],
        string="입고 시 상태", default="good",
    )

    # ── 현재 상태 ──
    current_condition = fields.Selection(
        [
            ("good", "양호"),
            ("in_use", "사용 중"),
            ("damaged", "손상"),
            ("lost", "분실"),
            ("returned", "반환"),
            ("consumed", "소모"),
            ("disposed", "폐기"),
        ],
        string="현재 상태", default="good", tracking=True,
    )
    location = fields.Char(string="보관 위치")
    preservation_method = fields.Char(string="보존 방법")

    # ── 이상 발생 ──
    incident_date = fields.Date(string="이상 발생일")
    incident_description = fields.Text(string="이상 내용")
    customer_notified = fields.Boolean(string="고객 통보 여부")
    notification_date = fields.Date(string="통보일")

    # ── 반환 ──
    return_date = fields.Date(string="반환일")
    return_condition = fields.Selection(
        [("good", "양호"), ("damaged", "손상"), ("consumed", "소모")],
        string="반환 시 상태",
    )

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    department_id = fields.Many2one("hr.department", string="관리 부서")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "등록"),
            ("active", "관리 중"),
            ("returned", "반환"),
            ("disposed", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.customer.property") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_return(self):
        self.write({"state": "returned", "return_date": fields.Date.today(),
                     "current_condition": "returned"})

    def action_dispose(self):
        self.write({"state": "disposed", "current_condition": "disposed"})
