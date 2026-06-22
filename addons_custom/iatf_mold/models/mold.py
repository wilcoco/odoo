from odoo import api, fields, models, _


class IatfMold(models.Model):
    _name = "iatf.mold"
    _description = "금형/치공구 대장 (IATF 16949 §8.5.1.6)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "code"

    code = fields.Char(
        string="금형 코드", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    name = fields.Char(string="금형명", required=True, tracking=True)
    mold_type = fields.Selection(
        [
            ("injection", "사출 금형"),
            ("press", "프레스 금형"),
            ("die_casting", "다이캐스팅 금형"),
            ("forging", "단조 금형"),
            ("jig", "지그"),
            ("fixture", "치공구"),
            ("gauge", "게이지"),
            ("other", "기타"),
        ],
        string="유형", required=True, default="injection", tracking=True,
    )

    # ── 사양 ──
    product_id = fields.Many2one("product.product", string="생산 제품", tracking=True)
    part_number = fields.Char(string="부품 번호")
    cavity_count = fields.Integer(string="캐비티 수", default=1)
    material = fields.Char(string="금형 재질")
    weight_kg = fields.Float(string="중량 (kg)")
    dimensions = fields.Char(string="치수 (LxWxH)")
    manufacturer = fields.Char(string="금형 제작사")
    manufacture_date = fields.Date(string="제작일")
    receive_date = fields.Date(string="입고일")
    cost = fields.Float(string="제작 비용")

    # ── 소유권 (§8.5.3) ──
    ownership = fields.Selection(
        [("company", "자사 소유"), ("customer", "고객 소유"), ("supplier", "협력업체 소유")],
        string="소유 구분", required=True, default="company", tracking=True,
    )
    owner_id = fields.Many2one("res.partner", string="소유자 (고객/협력업체)")
    customer_mold_number = fields.Char(string="고객 금형 번호")

    # ── 수명 관리 ──
    guaranteed_shots = fields.Integer(string="보증 타수 (샷)")
    current_shots = fields.Integer(string="현재 타수", tracking=True)
    remaining_shots = fields.Integer(string="잔여 타수", compute="_compute_remaining", store=True)
    life_percentage = fields.Float(string="수명 사용률 (%)", compute="_compute_remaining", store=True)
    pm_cycle_shots = fields.Integer(string="PM 주기 (타수)", default=50000)
    last_pm_shots = fields.Integer(string="최근 PM 타수")
    next_pm_shots = fields.Integer(string="다음 PM 타수", compute="_compute_next_pm", store=True)

    # ── 보관 ──
    storage_location = fields.Char(string="보관 위치")
    preservation_method = fields.Char(string="보존 방법", help="예: 방청유 도포, 건조 보관")

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자", tracking=True)
    department_id = fields.Many2one("hr.department", string="관리 부서")

    # ── 관련 기록 ──
    maintenance_ids = fields.One2many("iatf.mold.maintenance", "mold_id", string="보전/수리 이력")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    image = fields.Binary(string="금형 사진")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "등록"),
            ("active", "사용 중"),
            ("maintenance", "보전 중"),
            ("inactive", "비사용"),
            ("disposed", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("guaranteed_shots", "current_shots")
    def _compute_remaining(self):
        for rec in self:
            if rec.guaranteed_shots:
                rec.remaining_shots = max(rec.guaranteed_shots - rec.current_shots, 0)
                rec.life_percentage = (rec.current_shots / rec.guaranteed_shots) * 100.0
            else:
                rec.remaining_shots = 0
                rec.life_percentage = 0.0

    @api.depends("last_pm_shots", "pm_cycle_shots")
    def _compute_next_pm(self):
        for rec in self:
            rec.next_pm_shots = (rec.last_pm_shots or 0) + (rec.pm_cycle_shots or 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("iatf.mold") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_maintenance(self):
        self.write({"state": "maintenance"})

    def action_inactive(self):
        self.write({"state": "inactive"})

    def action_dispose(self):
        self.write({"state": "disposed"})

    def action_add_shots(self):
        """타수 추가 위저드 대신 간단히 처리"""
        return True
