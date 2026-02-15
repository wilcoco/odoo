from odoo import api, fields, models, _


class IatfEnvironmentCheck(models.Model):
    _name = "iatf.environment.check"
    _description = "작업환경 점검 기록"
    _inherit = ["mail.thread"]
    _order = "check_date desc"

    name = fields.Char(
        string="점검 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    work_area_id = fields.Many2one("iatf.work.area", string="작업 구역", required=True, tracking=True)
    check_type = fields.Selection(
        [
            ("environment", "환경 모니터링"),
            ("fiveS", "5S 점검"),
            ("safety", "안전 점검"),
        ],
        string="점검 유형", required=True, default="environment",
    )
    check_date = fields.Datetime(string="점검 일시", default=fields.Datetime.now, required=True)
    checker_id = fields.Many2one("res.users", string="점검자",
                                  default=lambda self: self.env.user)

    # ── 환경 측정값 ──
    temperature = fields.Float(string="온도 (°C)")
    humidity = fields.Float(string="습도 (%)")
    lighting = fields.Float(string="조도 (Lux)")
    noise = fields.Float(string="소음 (dB)")
    dust = fields.Char(string="분진")

    # ── 5S 점검 ──
    score_seiri = fields.Integer(string="정리 (1S)", help="0~10")
    score_seiton = fields.Integer(string="정돈 (2S)", help="0~10")
    score_seiso = fields.Integer(string="청소 (3S)", help="0~10")
    score_seiketsu = fields.Integer(string="청결 (4S)", help="0~10")
    score_shitsuke = fields.Integer(string="습관화 (5S)", help="0~10")
    fiveS_total = fields.Integer(string="5S 합계", compute="_compute_5s_total", store=True)

    # ── 판정 ──
    line_ids = fields.One2many("iatf.environment.check.line", "check_id", string="세부 점검 항목")
    result = fields.Selection(
        [("pass", "적합"), ("fail", "부적합"), ("action", "조치 필요")],
        string="판정", tracking=True,
    )
    corrective_action = fields.Text(string="시정 조치")

    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("draft", "초안"), ("done", "완료")],
        string="상태", default="draft", tracking=True,
    )

    @api.depends("score_seiri", "score_seiton", "score_seiso", "score_seiketsu", "score_shitsuke")
    def _compute_5s_total(self):
        for rec in self:
            rec.fiveS_total = (rec.score_seiri + rec.score_seiton + rec.score_seiso +
                               rec.score_seiketsu + rec.score_shitsuke)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.environment.check") or _("New")
        return super().create(vals_list)

    def action_done(self):
        self.write({"state": "done"})


class IatfEnvironmentCheckLine(models.Model):
    _name = "iatf.environment.check.line"
    _description = "환경점검 세부 항목"
    _order = "sequence"

    check_id = fields.Many2one("iatf.environment.check", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="기준")
    measured_value = fields.Char(string="측정값/확인 결과")
    result = fields.Selection(
        [("ok", "적합"), ("ng", "부적합"), ("na", "해당없음")],
        string="판정", default="ok",
    )
    remark = fields.Char(string="비고")
