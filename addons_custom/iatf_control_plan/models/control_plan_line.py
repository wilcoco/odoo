from odoo import fields, models


class IatfControlPlanLine(models.Model):
    _name = "iatf.control.plan.line"
    _description = "Control Plan Line Item"
    _order = "sequence, id"

    control_plan_id = fields.Many2one(
        "iatf.control.plan", string="관리계획서", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)

    # ── Process ──
    process_step_number = fields.Char(string="단계 #")
    process_name = fields.Char(string="공정명 / 작업")
    machine_device = fields.Char(string="설비 / 장치 / 공구")

    # ── Characteristic ──
    characteristic_number = fields.Char(string="특성 #")
    characteristic_name = fields.Char(string="특성", required=True)
    characteristic_type = fields.Selection(
        [
            ("product", "제품"),
            ("process", "공정"),
        ],
        string="특성 유형", default="product",
    )
    special_characteristic = fields.Selection(
        [
            ("none", "None"),
            ("cc", "CC - Critical"),
            ("sc", "SC - Significant"),
            ("hi", "HI - High Impact"),
        ],
        string="특별 특성", default="none",
    )

    # ── Specification ──
    specification = fields.Char(string="규격 / 공차")
    evaluation_method = fields.Char(string="평가 / 측정 방법")
    sample_size = fields.Char(string="시료 크기")
    sample_frequency = fields.Char(string="시료 빈도")

    # ── Control Method ──
    control_method = fields.Text(string="관리 방법")
    reaction_plan = fields.Text(string="대응 계획")

    # ── FMEA link ──
    fmea_line_id = fields.Many2one("iatf.fmea.line", string="FMEA 항목 참조")

    notes = fields.Text(string="비고")
