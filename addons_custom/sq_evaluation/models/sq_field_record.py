from odoo import api, fields, models, _


class SqFieldRecord(models.Model):
    """현장/절차 증빙 기록 — Odoo 트랜잭션 데이터가 없는 SQ 항목의 주기 점검 기록.
    생성 시 해당 평가항목의 점검서식(체크리스트 템플릿)을 라인으로 자동 로드 → 주기마다 입력·저장."""
    _name = "sq.field.record"
    _description = "SQ 현장/절차 점검 기록"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "record_date desc, id desc"

    name = fields.Char(string="번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    criteria_id = fields.Many2one("sq.criteria", string="SQ 평가항목", required=True, index=True,
                                  ondelete="cascade", tracking=True)
    category_id = fields.Many2one(related="criteria_id.category_id", store=True, string="대분류")
    check_cycle = fields.Selection(related="criteria_id.check_cycle", string="점검 주기", store=True)
    record_date = fields.Date(string="점검일", default=fields.Date.today, required=True, tracking=True)
    title = fields.Char(string="제목")
    result = fields.Selection(
        [("conform", "적합"), ("observe", "관찰/개선요"), ("nonconform", "부적합")],
        string="종합 결과", compute="_compute_result", store=True, tracking=True,
    )
    check_line_ids = fields.One2many("sq.field.record.line", "record_id", string="점검 항목")
    pass_rate = fields.Float(string="적합률 (%)", compute="_compute_result", store=True, digits=(5, 1))
    description = fields.Text(string="비고 / 관찰사항")
    responsible_id = fields.Many2one("res.users", string="점검자", default=lambda self: self.env.user)
    attachment_ids = fields.Many2many("ir.attachment", string="증빙 첨부")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("check_line_ids.result")
    def _compute_result(self):
        for rec in self:
            lines = rec.check_line_ids.filtered(lambda l: l.result != "na")
            total = len(lines)
            conform = len(lines.filtered(lambda l: l.result == "pass"))
            rec.pass_rate = (conform / total * 100.0) if total else 0.0
            if not total:
                rec.result = "observe"
            elif lines.filtered(lambda l: l.result == "fail"):
                rec.result = "nonconform"
            elif conform == total:
                rec.result = "conform"
            else:
                rec.result = "observe"

    def _load_checklist(self):
        """평가항목의 체크리스트 템플릿을 점검 라인으로 로드 (비어있을 때)."""
        for rec in self:
            if rec.criteria_id and not rec.check_line_ids:
                rec.check_line_ids = [(0, 0, {
                    "sequence": t.sequence, "name": t.name,
                    "input_type": t.input_type, "spec": t.spec, "unit": t.unit,
                }) for t in rec.criteria_id.checklist_ids]

    @api.onchange("criteria_id")
    def _onchange_criteria_load(self):
        self._load_checklist()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("sq.field.record") or _("New")
        records = super().create(vals_list)
        records._load_checklist()
        return records


class SqFieldRecordLine(models.Model):
    _name = "sq.field.record.line"
    _description = "SQ 점검 기록 라인"
    _order = "sequence, id"

    record_id = fields.Many2one("sq.field.record", string="점검기록", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(string="점검 항목", required=True)
    input_type = fields.Selection(
        [("pass_fail", "적합/부적합"), ("number", "수치"), ("text", "서술")],
        string="입력 유형", default="pass_fail",
    )
    spec = fields.Char(string="기준")
    unit = fields.Char(string="단위")
    result = fields.Selection(
        [("pass", "적합"), ("fail", "부적합"), ("na", "해당없음")],
        string="판정", default="pass",
    )
    value_num = fields.Float(string="측정값")
    value_text = fields.Char(string="기록")
    note = fields.Char(string="비고")
