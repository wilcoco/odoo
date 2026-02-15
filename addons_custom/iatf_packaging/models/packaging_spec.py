from odoo import api, fields, models, _


class IatfPackagingSpec(models.Model):
    _name = "iatf.packaging.spec"
    _description = "포장 사양서 (IATF 16949 §8.5.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "product_id, customer_id"

    name = fields.Char(
        string="사양 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    customer_id = fields.Many2one("res.partner", string="고객", tracking=True)
    revision = fields.Char(string="개정", default="A")
    effective_date = fields.Date(string="적용일", default=fields.Date.today)

    # ── 내포장 ──
    inner_packaging_type = fields.Char(string="내포장 유형", help="예: PE 봉투, 트레이, 칸막이")
    inner_quantity = fields.Integer(string="내포장 수량 (EA)")
    inner_material = fields.Char(string="내포장 재질")
    inner_dimension = fields.Char(string="내포장 치수")

    # ── 외포장 ──
    outer_packaging_type = fields.Char(string="외포장 유형", help="예: 골판지, 플라스틱 박스")
    outer_quantity = fields.Integer(string="외포장 수량 (EA)")
    outer_material = fields.Char(string="외포장 재질")
    outer_dimension = fields.Char(string="외포장 치수 (LxWxH)")
    gross_weight = fields.Float(string="총 중량 (kg)")

    # ── 파렛트 ──
    pallet_type = fields.Char(string="파렛트 유형")
    boxes_per_pallet = fields.Integer(string="파렛트 당 박스 수")
    pallet_stack = fields.Integer(string="적재 단수", default=1)
    total_per_pallet = fields.Integer(string="파렛트 당 총 수량", compute="_compute_pallet_total", store=True)

    # ── 라벨링 ──
    label_required = fields.Boolean(string="라벨 부착 필요", default=True)
    label_type = fields.Char(string="라벨 유형", help="예: 바코드, QR, 고객 지정 라벨")
    label_info = fields.Text(string="라벨 표기 내용")

    # ── 보존 조건 ──
    storage_condition = fields.Selection(
        [
            ("normal", "일반 보관"),
            ("dry", "건조 보관"),
            ("cool", "냉암소 보관"),
            ("humidity", "항온항습"),
            ("special", "특수 조건"),
        ],
        string="보관 조건", default="normal",
    )
    temperature_range = fields.Char(string="온도 범위", help="예: 5~35°C")
    humidity_range = fields.Char(string="습도 범위", help="예: 40~70%")
    shelf_life_days = fields.Integer(string="유효기간 (일)")
    special_instruction = fields.Text(string="특수 보관 지시")
    anticorrosion_method = fields.Char(string="방청 처리", help="예: VCI 봉투, 방청유")

    # ── 고객 승인 ──
    customer_approved = fields.Boolean(string="고객 승인 완료")
    approval_date = fields.Date(string="승인일")
    approval_reference = fields.Char(string="승인 참조번호")

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user)

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")
    image = fields.Binary(string="포장 사진")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("active", "활성"),
            ("review", "검토 필요"),
            ("obsolete", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("outer_quantity", "boxes_per_pallet")
    def _compute_pallet_total(self):
        for rec in self:
            rec.total_per_pallet = (rec.outer_quantity or 0) * (rec.boxes_per_pallet or 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.packaging.spec") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_review(self):
        self.write({"state": "review"})

    def action_obsolete(self):
        self.write({"state": "obsolete"})
