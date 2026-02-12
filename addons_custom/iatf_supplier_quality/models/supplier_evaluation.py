from odoo import api, fields, models, _


class IatfSupplierEvaluation(models.Model):
    _name = "iatf.supplier.evaluation"
    _description = "Supplier Quality Evaluation (IATF 16949 §8.4)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "evaluation_date desc"

    name = fields.Char(
        string="Evaluation Number", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    supplier_id = fields.Many2one("res.partner", string="Supplier", required=True,
                                   domain="[('supplier_rank','>',0)]", tracking=True)
    evaluation_date = fields.Date(string="Evaluation Date", default=fields.Date.today, required=True)
    evaluation_period = fields.Char(string="Evaluation Period", help="e.g. 2026-Q1")
    evaluator_id = fields.Many2one("res.users", string="Evaluator", default=lambda self: self.env.user)

    # ── Scoring criteria ──
    score_quality = fields.Float(string="Quality Score (0-100)", default=0)
    score_delivery = fields.Float(string="Delivery Score (0-100)", default=0)
    score_cost = fields.Float(string="Cost Score (0-100)", default=0)
    score_responsiveness = fields.Float(string="Responsiveness Score (0-100)", default=0)
    score_system = fields.Float(string="QMS/Certification Score (0-100)", default=0)

    weight_quality = fields.Float(string="Quality Weight (%)", default=40)
    weight_delivery = fields.Float(string="Delivery Weight (%)", default=25)
    weight_cost = fields.Float(string="Cost Weight (%)", default=15)
    weight_responsiveness = fields.Float(string="Responsiveness Weight (%)", default=10)
    weight_system = fields.Float(string="QMS Weight (%)", default=10)

    total_score = fields.Float(string="Total Score", compute="_compute_total_score", store=True)
    grade = fields.Selection(
        [
            ("a", "A — Preferred (≥ 90)"),
            ("b", "B — Approved (70–89)"),
            ("c", "C — Conditional (50–69)"),
            ("d", "D — Disqualified (< 50)"),
        ],
        string="Grade", compute="_compute_total_score", store=True,
    )

    # ── Details ──
    ppm_rate = fields.Float(string="PPM Rate")
    on_time_delivery_pct = fields.Float(string="On-Time Delivery (%)")
    certification = fields.Char(string="Certifications (ISO/IATF)")
    nc_count_period = fields.Integer(string="NC Count in Period")
    scar_count_period = fields.Integer(string="SCAR Count in Period")

    notes = fields.Html(string="Notes / Improvement Plan")
    state = fields.Selection(
        [("draft", "Draft"), ("confirmed", "Confirmed"), ("closed", "Closed")],
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
