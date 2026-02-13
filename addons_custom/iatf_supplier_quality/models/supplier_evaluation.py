from odoo import api, fields, models, _


class IatfSupplierEvaluation(models.Model):
    _name = "iatf.supplier.evaluation"
    _description = "Supplier Quality Evaluation (IATF 16949 §8.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "evaluation_date desc"

    name = fields.Char(
        string="평가 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    supplier_id = fields.Many2one("res.partner", string="협력업체", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    evaluation_date = fields.Date(string="평가일", default=fields.Date.today, required=True)
    evaluation_period = fields.Char(string="평가 기간", help="e.g. 2026-Q1")
    evaluator_id = fields.Many2one("res.users", string="평가자", default=lambda self: self.env.user)

    # ── Scoring criteria ──
    score_quality = fields.Float(string="품질 점수 (0-100)", default=0)
    score_delivery = fields.Float(string="납기 점수 (0-100)", default=0)
    score_cost = fields.Float(string="비용 점수 (0-100)", default=0)
    score_responsiveness = fields.Float(string="대응력 점수 (0-100)", default=0)
    score_system = fields.Float(string="QMS/인증 점수 (0-100)", default=0)

    weight_quality = fields.Float(string="품질 가중치 (%)", default=40)
    weight_delivery = fields.Float(string="납기 가중치 (%)", default=25)
    weight_cost = fields.Float(string="비용 가중치 (%)", default=15)
    weight_responsiveness = fields.Float(string="대응력 가중치 (%)", default=10)
    weight_system = fields.Float(string="품질경영시스템 가중치 (%)", default=10)

    total_score = fields.Float(string="총점", compute="_compute_total_score", store=True)
    grade = fields.Selection(
        [
            ("a", "A — 우수 (≥ 90)"),
            ("b", "B — 승인 (70–89)"),
            ("c", "C — 조건부 (50–69)"),
            ("d", "D — 부적격 (< 50)"),
        ],
        string="등급", compute="_compute_total_score", store=True,
    )

    # ── Details ──
    ppm_rate = fields.Float(string="PPM 비율")
    on_time_delivery_pct = fields.Float(string="납기준수율 (%)")
    certification = fields.Char(string="인증 (ISO/IATF)")
    nc_count_period = fields.Integer(string="기간 내 부적합 수")
    scar_count_period = fields.Integer(string="기간 내 SCAR 수")

    notes = fields.Html(string="비고 / 개선 계획")
    state = fields.Selection(
        [("draft", "초안"), ("confirmed", "확정"), ("closed", "종료")],
        default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("score_quality", "score_delivery", "score_cost", "score_responsiveness", "score_system",
                 "weight_quality", "weight_delivery", "weight_cost", "weight_responsiveness", "weight_system")
    def _compute_total_score(self):
        for rec in self:
            total_weight = (rec.weight_quality + rec.weight_delivery + rec.weight_cost
                            + rec.weight_responsiveness + rec.weight_system) or 100
            total = (
                rec.score_quality * rec.weight_quality
                + rec.score_delivery * rec.weight_delivery
                + rec.score_cost * rec.weight_cost
                + rec.score_responsiveness * rec.weight_responsiveness
                + rec.score_system * rec.weight_system
            ) / total_weight
            rec.total_score = total
            if total >= 90:
                rec.grade = "a"
            elif total >= 70:
                rec.grade = "b"
            elif total >= 50:
                rec.grade = "c"
            else:
                rec.grade = "d"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.supplier.evaluation") or _("New")
        return super().create(vals_list)

    def action_confirm(self):
        self.write({"state": "confirmed"})

    def action_close(self):
        self.write({"state": "closed"})
