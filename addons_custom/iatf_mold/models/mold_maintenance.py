from odoo import api, fields, models, _


class IatfMoldMaintenance(models.Model):
    _name = "iatf.mold.maintenance"
    _description = "금형 보전/수리 이력"
    _inherit = ["mail.thread"]
    _order = "date desc"

    name = fields.Char(
        string="번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    mold_id = fields.Many2one("iatf.mold", string="금형", required=True, tracking=True)
    maintenance_type = fields.Selection(
        [
            ("pm", "예방보전"),
            ("repair", "수리"),
            ("modification", "개조"),
            ("inspection", "점검"),
            # 세척은 별도 모델을 만들지 않고 이 이력에 유형으로 넣는다.
            # iatf.mold.clean_cycle_days 와 짝이 되어 SQ 4_2(계획 대비 실적)의
            # 실적 쪽 원장이 된다. 완료(done) 건만 실적으로 센다.
            ("clean", "세척"),
        ],
        string="유형", required=True, default="pm",
    )
    date = fields.Date(string="일자", default=fields.Date.today, required=True)
    shots_at_maintenance = fields.Integer(string="보전 시 타수")

    # ── 작업 내용 ──
    work_description = fields.Html(string="작업 내용")
    parts_replaced = fields.Text(string="교체 부품")
    cost = fields.Float(string="비용")
    vendor = fields.Char(string="수리 업체")
    responsible_id = fields.Many2one("res.users", string="담당자")
    duration_hours = fields.Float(string="소요 시간")

    result = fields.Selection(
        [("ok", "양호"), ("monitor", "경과 관찰"), ("replace_needed", "교체 필요")],
        string="결과",
    )

    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("planned", "계획"), ("done", "완료"), ("cancelled", "취소")],
        string="상태", default="planned", tracking=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.mold.maintenance") or _("New")
        return super().create(vals_list)

    def action_done(self):
        for rec in self:
            rec.write({"state": "done"})
            if rec.shots_at_maintenance:
                rec.mold_id.write({"last_pm_shots": rec.shots_at_maintenance})
