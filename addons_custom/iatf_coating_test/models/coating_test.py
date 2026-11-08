from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.iatf_document_control.models.quality_guards import is_blank

RESULT_SELECTION = [
    ("pass", "합격"),
    ("conditional", "조건부 합격"),
    ("fail", "불합격"),
]
STATE_SELECTION = [
    ("draft", "초안"),
    ("tested", "시험 완료"),
    ("closed", "종료"),
    ("cancelled", "취소"),
]


class IatfReliabilityTest(models.Model):
    _name = "iatf.reliability.test"
    _description = "신뢰성 시험 (내후성·내열성·내약품성·부착성 등)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="시험 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    product_id = fields.Many2one("product.product", string="제품 / 부품", required=True, tracking=True)
    test_type = fields.Selection(
        [("weather", "내후성"), ("heat", "내열성"), ("chemical", "내약품성"),
         ("adhesion", "부착성"), ("humidity", "내습성"), ("other", "기타")],
        string="시험 유형", tracking=True,
    )
    test_date = fields.Date(string="시험일", default=fields.Date.today, required=True)
    test_standard = fields.Char(string="시험 규격", help="예: MS 시험규격 번호 (현업 입력)")
    test_conditions = fields.Text(string="시험 조건")
    sample_qty = fields.Integer(string="시료 수량")
    test_duration = fields.Char(string="시험 시간 / 기간")
    measured_values = fields.Text(string="측정값")
    report_no = fields.Char(string="성적서 번호")
    result = fields.Selection(RESULT_SELECTION, string="판정", tracking=True)
    tester_id = fields.Many2one("res.users", string="시험자", default=lambda self: self.env.user)
    notes = fields.Text(string="비고")
    state = fields.Selection(STATE_SELECTION, string="상태", default="draft", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.reliability.test") or _("New")
        return super().create(vals_list)


    # ── 478 #51: 판정·근거 없이 종료하지 않는다 ──
    _RESULT_FIELD = "result"
    _EVIDENCE_FIELDS = ("measured_values", "test_standard")

    def _check_testable(self):
        for rec in self:
            if not rec[rec._RESULT_FIELD]:
                raise UserError(_("판정을 입력한 뒤 시험 완료로 넘기십시오. (%s)", rec.name))
            missing = [rec._fields[name].string for name in rec._EVIDENCE_FIELDS
                       if is_blank(rec[name])]
            if missing:
                raise UserError(_(
                    "시험 근거가 비어 있습니다: %(fields)s (%(name)s)",
                    fields=", ".join(missing), name=rec.name))

    def action_test_done(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("초안 상태에서만 시험 완료로 넘길 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "tested"})

    def action_close(self):
        for rec in self:
            if rec.state != "tested":
                raise UserError(_("시험 완료 상태에서만 종료할 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "closed"})

    def action_cancel(self):
        for rec in self:
            if rec.state == "closed":
                raise UserError(_("종료된 시험은 취소할 수 없습니다. 정정은 새 시험으로 남기십시오. (%s)", rec.name))
        self.write({"state": "cancelled"})


class IatfAdhesionTest(models.Model):
    _name = "iatf.adhesion.test"
    _description = "밀착성 시험 (크로스컷)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="시험 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    product_id = fields.Many2one("product.product", string="제품 / 부품", required=True, tracking=True)
    test_date = fields.Date(string="시험일", default=fields.Date.today, required=True)
    color = fields.Char(string="색상")
    # 회사양식: 위치별 크로스컷 등급/판정 (등급값 = 현업 기준, 데이터 입력)
    position1_grade = fields.Char(string="위치1 등급")
    position1_result = fields.Selection(RESULT_SELECTION, string="위치1 판정")
    position2_grade = fields.Char(string="위치2 등급")
    position2_result = fields.Selection(RESULT_SELECTION, string="위치2 판정")
    overall_result = fields.Selection(RESULT_SELECTION, string="종합 판정", tracking=True)
    result = fields.Selection(related="overall_result", string="판정", store=True)
    tester_id = fields.Many2one("res.users", string="시험자", default=lambda self: self.env.user)
    notes = fields.Text(string="비고")
    state = fields.Selection(STATE_SELECTION, string="상태", default="draft", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.adhesion.test") or _("New")
        return super().create(vals_list)


    # ── 478 #51: 판정·근거 없이 종료하지 않는다 ──
    _RESULT_FIELD = "overall_result"
    _EVIDENCE_FIELDS = ("test_standard",)

    def _check_testable(self):
        for rec in self:
            if not rec[rec._RESULT_FIELD]:
                raise UserError(_("판정을 입력한 뒤 시험 완료로 넘기십시오. (%s)", rec.name))
            missing = [rec._fields[name].string for name in rec._EVIDENCE_FIELDS
                       if is_blank(rec[name])]
            if missing:
                raise UserError(_(
                    "시험 근거가 비어 있습니다: %(fields)s (%(name)s)",
                    fields=", ".join(missing), name=rec.name))
            positions = (rec.position1_result, rec.position2_result)
            if not all(positions):
                raise UserError(_("위치1·위치2 판정을 모두 입력하십시오. (%s)", rec.name))
            if rec.overall_result == "pass" and "fail" in positions:
                raise UserError(_(
                    "위치 판정에 불합격이 있어 종합 합격으로 둘 수 없습니다. (%s)", rec.name))

    def action_test_done(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("초안 상태에서만 시험 완료로 넘길 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "tested"})

    def action_close(self):
        for rec in self:
            if rec.state != "tested":
                raise UserError(_("시험 완료 상태에서만 종료할 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "closed"})

    def action_cancel(self):
        for rec in self:
            if rec.state == "closed":
                raise UserError(_("종료된 시험은 취소할 수 없습니다. 정정은 새 시험으로 남기십시오. (%s)", rec.name))
        self.write({"state": "cancelled"})


class IatfColorMeasurement(models.Model):
    _name = "iatf.color.measurement"
    _description = "색상 측정 (ΔE)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="측정 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    product_id = fields.Many2one("product.product", string="제품 / 부품", required=True, tracking=True)
    measurement_date = fields.Date(string="측정일", default=fields.Date.today, required=True)
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")
    color = fields.Char(string="색상")
    delta_l = fields.Float(string="ΔL", digits=(6, 3))
    delta_a = fields.Float(string="Δa", digits=(6, 3))
    delta_b = fields.Float(string="Δb", digits=(6, 3))
    delta_e = fields.Float(string="ΔE", digits=(6, 3),
                           help="ΔE 합격 기준값은 회사 현업 규격에 따라 판정 입력")
    standard_plate_no = fields.Char(string="표준판 번호")
    result = fields.Selection(RESULT_SELECTION, string="판정", tracking=True)
    measurer_id = fields.Many2one("res.users", string="측정자", default=lambda self: self.env.user)
    notes = fields.Text(string="비고")
    state = fields.Selection(STATE_SELECTION, string="상태", default="draft", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.color.measurement") or _("New")
        return super().create(vals_list)


    # ── 478 #51: 판정·근거 없이 종료하지 않는다 ──
    _RESULT_FIELD = "result"
    _EVIDENCE_FIELDS = ("standard_plate_no",)

    def _check_testable(self):
        for rec in self:
            if not rec[rec._RESULT_FIELD]:
                raise UserError(_("판정을 입력한 뒤 시험 완료로 넘기십시오. (%s)", rec.name))
            missing = [rec._fields[name].string for name in rec._EVIDENCE_FIELDS
                       if is_blank(rec[name])]
            if missing:
                raise UserError(_(
                    "시험 근거가 비어 있습니다: %(fields)s (%(name)s)",
                    fields=", ".join(missing), name=rec.name))

    def action_test_done(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("초안 상태에서만 시험 완료로 넘길 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "tested"})

    def action_close(self):
        for rec in self:
            if rec.state != "tested":
                raise UserError(_("시험 완료 상태에서만 종료할 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "closed"})

    def action_cancel(self):
        for rec in self:
            if rec.state == "closed":
                raise UserError(_("종료된 시험은 취소할 수 없습니다. 정정은 새 시험으로 남기십시오. (%s)", rec.name))
        self.write({"state": "cancelled"})


class IatfCoatingThickness(models.Model):
    _name = "iatf.coating.thickness"
    _description = "도막 두께 측정"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="측정 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    product_id = fields.Many2one("product.product", string="제품 / 부품", required=True, tracking=True)
    measurement_date = fields.Date(string="측정일", default=fields.Date.today, required=True)
    color = fields.Char(string="색상")
    position1 = fields.Float(string="위치1 (㎛)", digits=(6, 1))
    position2 = fields.Float(string="위치2 (㎛)", digits=(6, 1))
    position3 = fields.Float(string="위치3 (㎛)", digits=(6, 1))
    position4 = fields.Float(string="위치4 (㎛)", digits=(6, 1))
    position5 = fields.Float(string="위치5 (㎛)", digits=(6, 1))
    average_thickness = fields.Float(string="평균 도막두께 (㎛)", digits=(6, 1),
                                     compute="_compute_average", store=True)
    spec_min = fields.Float(string="규격 하한 (㎛)", digits=(6, 1), help="현업 도막 규격")
    spec_max = fields.Float(string="규격 상한 (㎛)", digits=(6, 1), help="현업 도막 규격")
    result = fields.Selection(RESULT_SELECTION, string="판정", tracking=True)
    measurer_id = fields.Many2one("res.users", string="측정자", default=lambda self: self.env.user)
    notes = fields.Text(string="비고")
    state = fields.Selection(STATE_SELECTION, string="상태", default="draft", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("position1", "position2", "position3", "position4", "position5")
    def _compute_average(self):
        for rec in self:
            vals = [v for v in (rec.position1, rec.position2, rec.position3,
                                rec.position4, rec.position5) if v]
            rec.average_thickness = sum(vals) / len(vals) if vals else 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.coating.thickness") or _("New")
        return super().create(vals_list)


    # ── 478 #51: 판정·근거 없이 종료하지 않는다 ──
    _RESULT_FIELD = "result"
    _EVIDENCE_FIELDS = ()

    def _check_testable(self):
        for rec in self:
            if not rec[rec._RESULT_FIELD]:
                raise UserError(_("판정을 입력한 뒤 시험 완료로 넘기십시오. (%s)", rec.name))
            missing = [rec._fields[name].string for name in rec._EVIDENCE_FIELDS
                       if is_blank(rec[name])]
            if missing:
                raise UserError(_(
                    "시험 근거가 비어 있습니다: %(fields)s (%(name)s)",
                    fields=", ".join(missing), name=rec.name))
            if not any((rec.position1, rec.position2, rec.position3, rec.position4, rec.position5)):
                raise UserError(_("측정 위치 값을 입력한 뒤 판정하십시오. (%s)", rec.name))
            if rec.result == "pass" and rec.spec_min and rec.average_thickness < rec.spec_min:
                raise UserError(_("평균 도막두께가 규격 하한 미만입니다. (%s)", rec.name))
            if rec.result == "pass" and rec.spec_max and rec.average_thickness > rec.spec_max:
                raise UserError(_("평균 도막두께가 규격 상한 초과입니다. (%s)", rec.name))

    def action_test_done(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("초안 상태에서만 시험 완료로 넘길 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "tested"})

    def action_close(self):
        for rec in self:
            if rec.state != "tested":
                raise UserError(_("시험 완료 상태에서만 종료할 수 있습니다. (%s)", rec.name))
        self._check_testable()
        self.write({"state": "closed"})

    def action_cancel(self):
        for rec in self:
            if rec.state == "closed":
                raise UserError(_("종료된 시험은 취소할 수 없습니다. 정정은 새 시험으로 남기십시오. (%s)", rec.name))
        self.write({"state": "cancelled"})
