from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

MATERIAL_TYPE = [
    ("virgin", "신재"),
    ("regrind", "재생재(분쇄재)"),
    ("additive", "첨가제/마스터배치"),
]

SHIFT = [("day", "주간"), ("night", "야간"), ("etc", "기타")]

RATIO_BASIS = [
    ("resin", "수지 기준 (신재+재생재)"),
    ("total", "총 투입량 기준 (첨가제 포함)"),
]


class IatfBlendStandard(models.Model):
    """배합 관리기준 — 품목별 재생재 최대 투입비율 (SQ 사출 1_10 / 3_4).

    가동 전 평가에서 평가자가 먼저 보는 것은 실적이 아니라 **기준이 수립돼 있는가**다.
    그래서 일지보다 이 마스터가 본체다. 일지의 합부 판정은 전부 이 기준에서 나온다.

    비율의 분모를 회사가 정하게 둔 이유: 현장마다 "재생률"을 수지 기준으로 세기도 하고
    첨가제까지 포함한 총 투입량 기준으로 세기도 한다. 개발이 임의로 정하면 합부 판정이
    회사 기준과 어긋나고, 그 어긋난 판정이 그대로 증빙이 된다.
    """

    _name = "iatf.blend.standard"
    _description = "배합 관리기준 (SQ 1_10)"
    _inherit = ["mail.thread"]
    _order = "product_id, effective_date desc, id desc"

    name = fields.Char(string="기준번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("신규"))
    product_id = fields.Many2one(
        "product.product", string="대상 품목", required=True, tracking=True,
        help="이 기준이 적용되는 사출품(완제품/반제품).")
    material_id = fields.Many2one(
        "product.product", string="대상 수지", ondelete="set null", tracking=True,
        help="기준을 수지 단위로 관리하는 경우 입력. 비워 두면 품목 기준으로만 본다.")
    max_regrind_ratio = fields.Float(
        string="재생재 최대비율(%)", required=True, tracking=True, digits=(5, 2),
        help="이 값을 넘는 배합은 배합일지에서 '기준 초과'로 판정된다.")
    ratio_basis = fields.Selection(
        RATIO_BASIS, string="비율 산정 기준", required=True, default="resin", tracking=True)
    max_additive_ratio = fields.Float(
        string="첨가제 최대비율(%)", digits=(5, 2), tracking=True,
        help="0 이면 첨가제 상한을 관리하지 않는다.")
    effective_date = fields.Date(
        string="적용 시작일", required=True, tracking=True,
        default=fields.Date.context_today)
    active = fields.Boolean(default=True)
    customer_approved = fields.Boolean(
        string="고객 승인", tracking=True,
        help="재생재 혼합은 고객 승인이 필요한 경우가 많다 (SQ 1_5).")
    approval_ref = fields.Char(string="승인 문서번호")
    approval_date = fields.Date(string="승인일")
    ms_spec_note = fields.Text(
        string="물성 확인 근거",
        help="혼합 사용 시 MS-SPEC 물성을 만족하는지 확인한 근거(시험성적서 번호 등).")
    note = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("uniq_product_date",
         "unique(product_id, material_id, effective_date, company_id)",
         "같은 품목·수지에 같은 적용일의 기준이 이미 있습니다."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("신규"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "iatf.blend.standard") or _("신규")
        return super().create(vals_list)

    @api.constrains("max_regrind_ratio", "max_additive_ratio")
    def _check_ratio_range(self):
        for rec in self:
            for label, value in ((_("재생재 최대비율"), rec.max_regrind_ratio),
                                 (_("첨가제 최대비율"), rec.max_additive_ratio)):
                if value < 0 or value > 100:
                    raise ValidationError(_(
                        "%(label)s 는 0~100 사이여야 합니다. (%(value)s)",
                        label=label, value=value))

    @api.constrains("customer_approved", "approval_date", "effective_date")
    def _check_approval(self):
        """승인 표시만 켜고 근거가 없는 상태를 막는다."""
        for rec in self:
            if rec.customer_approved and not (rec.approval_ref or rec.approval_date):
                raise ValidationError(_(
                    "'%s': 고객 승인을 표시하려면 승인 문서번호나 승인일 중 하나는 있어야 합니다.",
                    rec.name))
            if rec.approval_date and rec.approval_date > fields.Date.context_today(rec):
                raise ValidationError(_("'%s': 승인일을 미래로 둘 수 없습니다.", rec.name))

    @api.model
    def _standard_for(self, product, date, material=None, company=None):
        """배합일 시점에 유효한 기준을 찾는다.

        적용일이 배합일보다 나중인 기준은 쓰지 않는다. 그렇게 하지 않으면 나중에
        만든 기준으로 과거 배합을 판정하게 되고, 그건 그때의 관리 상태가 아니다.

        `company` 를 반드시 걸러야 한다. 이 모델에는 다중회사 레코드 규칙이 없어서
        걸러 주지 않으면 다른 법인의 상한으로 우리 배합이 합/부 판정된다. 회사가
        비어 있는 기준은 전사 공통으로 보고 함께 후보에 넣는다.
        """
        if not product or not date:
            return self.browse()
        base = [("product_id", "=", product.id), ("effective_date", "<=", date)]

        # 좁은 기준이 넓은 기준을 이긴다: 수지 지정 > 품목 공통, 자사 > 전사 공통.
        # 한 번의 search 로 정렬해서 고를 수 없다 — Postgres 의 DESC 는 NULL 을 먼저
        # 놓기 때문에 company_id 가 빈(전사) 기준이 자사 기준을 밀어낸다.
        company_scopes = [[("company_id", "=", company.id)], [("company_id", "=", False)]] \
            if company else [[]]
        material_scopes = [[("material_id", "=", material.id)]] if material else []
        material_scopes.append([("material_id", "=", False)])

        for material_scope in material_scopes:
            for company_scope in company_scopes:
                found = self.search(base + material_scope + company_scope,
                                    order="effective_date desc, id desc", limit=1)
                if found:
                    return found
        return self.browse()


class IatfRegrindLog(models.Model):
    """분쇄일지 — 스크랩을 분쇄해 재생재 로트를 만든 이력 (SQ 사출 1_10 / 3_4).

    배합일지의 재생재 투입 줄이 이 기록을 가리킨다. 출처 없는 재생재는
    "어디서 온 재생재인지 모르는 상태"라 혼합일지가 있어도 추적이 끊긴다.
    """

    _name = "iatf.regrind.log"
    _description = "분쇄일지 (SQ 1_10)"
    _inherit = ["mail.thread"]
    _order = "regrind_date desc, id desc"

    name = fields.Char(string="분쇄번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("신규"))
    regrind_date = fields.Date(string="분쇄일", required=True, tracking=True,
                               default=fields.Date.context_today)
    shift = fields.Selection(SHIFT, string="교대", default="day")
    equipment_id = fields.Many2one(
        "iatf.equipment", string="분쇄기", ondelete="set null", tracking=True)
    source_product_id = fields.Many2one(
        "product.product", string="투입 스크랩 품목", required=True, tracking=True)
    source_type = fields.Selection(
        [("sprue", "스프루/런너"), ("defect", "불량품"), ("tryout", "시사출품"),
         ("purge", "퍼지재"), ("other", "기타")],
        string="스크랩 출처", required=True, default="sprue", tracking=True)
    input_qty = fields.Float(string="투입량(kg)", required=True, digits=(12, 3))
    output_qty = fields.Float(string="산출 재생재(kg)", required=True, digits=(12, 3))
    loss_qty = fields.Float(string="손실(kg)", compute="_compute_yield", store=True,
                            digits=(12, 3))
    yield_ratio = fields.Float(string="수율(%)", compute="_compute_yield", store=True,
                               digits=(5, 2))
    output_lot_id = fields.Many2one(
        "stock.lot", string="재생재 LOT", ondelete="set null",
        help="재생재에 로트를 부여해 관리하는 경우 연결한다.")
    output_lot_name = fields.Char(
        string="재생재 표시번호",
        help="로트를 발행하지 않고 현장 표시번호만 쓰는 경우 여기에 적는다.")
    foreign_check = fields.Selection(
        [("ok", "이물 없음"), ("ng", "이물 발견")], string="이물 혼입 점검", tracking=True)
    foreign_action = fields.Text(string="이물 발견 시 조치")
    storage_location = fields.Char(string="보관 위치")
    operator_id = fields.Many2one("res.users", string="작업자",
                                  default=lambda self: self.env.user)
    state = fields.Selection([("draft", "작성중"), ("done", "완료")],
                             default="draft", tracking=True, string="상태")
    note = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    blend_line_ids = fields.One2many(
        "iatf.blend.log.line", "regrind_log_id", string="이 재생재를 쓴 배합")
    used_qty = fields.Float(string="배합 투입 누계(kg)", compute="_compute_used",
                            digits=(12, 3))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("신규"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "iatf.regrind.log") or _("신규")
        return super().create(vals_list)

    @api.depends("input_qty", "output_qty")
    def _compute_yield(self):
        for rec in self:
            rec.loss_qty = rec.input_qty - rec.output_qty
            rec.yield_ratio = (rec.output_qty / rec.input_qty * 100.0) if rec.input_qty else 0.0

    @api.depends("blend_line_ids.qty")
    def _compute_used(self):
        """비저장이다. 배합 쪽에서 줄이 추가·삭제될 때마다 다시 센다."""
        for rec in self:
            rec.used_qty = sum(rec.blend_line_ids.mapped("qty"))

    @api.constrains("regrind_date")
    def _check_not_future(self):
        for rec in self:
            if rec.regrind_date and rec.regrind_date > fields.Date.context_today(rec):
                raise ValidationError(_("'%s': 분쇄일을 미래로 기록할 수 없습니다.", rec.name))

    @api.constrains("input_qty", "output_qty")
    def _check_qty(self):
        """산출이 투입보다 많을 수 없다. 물리적으로 불가능한 값이 들어오면
        재생재 재고가 부풀고, 그 숫자가 배합 비율의 분자가 된다."""
        for rec in self:
            if rec.input_qty <= 0:
                raise ValidationError(_("'%s': 투입량은 0보다 커야 합니다.", rec.name))
            if rec.output_qty < 0:
                raise ValidationError(_("'%s': 산출량은 음수일 수 없습니다.", rec.name))
            if rec.output_qty > rec.input_qty:
                raise ValidationError(_(
                    "'%(name)s': 산출 재생재(%(out)s kg)가 투입 스크랩(%(inp)s kg)보다 많습니다.",
                    name=rec.name, out=rec.output_qty, inp=rec.input_qty))

    def _missing_for_done(self):
        self.ensure_one()
        missing = []
        if not self.foreign_check:
            missing.append(_("이물 혼입 점검"))
        if self.foreign_check == "ng" and not self.foreign_action:
            missing.append(_("이물 발견 시 조치"))
        return missing

    @api.constrains("state", "foreign_check", "foreign_action")
    def _check_done_is_complete(self):
        """완료 상태의 백스톱. 버튼을 거치지 않고 `write({'state': 'done'})` 으로
        바꿔도 같은 규칙이 걸리게 한다."""
        for rec in self:
            if rec.state != "done":
                continue
            missing = rec._missing_for_done()
            if missing:
                raise ValidationError(_(
                    "%(fields)s 이(가) 비어 있어 완료할 수 없습니다. (%(name)s)",
                    fields=", ".join(missing), name=rec.name))

    def action_done(self):
        for rec in self:
            missing = rec._missing_for_done()
            if missing:
                raise UserError(_("%(fields)s 을(를) 먼저 입력하십시오. (%(name)s)",
                                  fields=", ".join(missing), name=rec.name))
            rec.state = "done"

    def action_draft(self):
        self.state = "draft"


class IatfBlendLog(models.Model):
    """배합일지 — LOT 단위 신재:재생재 혼합 기록 (SQ 사출 1_10, 1_8).

    합부 판정은 사람이 고르지 않는다. 투입량에서 비율을 계산하고 기준과 비교한다.
    기준값은 배합 시점의 것을 **복사해 둔다**(스냅샷). 나중에 기준을 완화하면
    과거의 초과 배합이 소급해서 '합격'으로 바뀌는데, 그게 곧 허위기재다.
    """

    _name = "iatf.blend.log"
    _description = "배합일지 (SQ 1_10)"
    _inherit = ["mail.thread"]
    _order = "blend_date desc, id desc"

    name = fields.Char(string="배합번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("신규"))
    blend_date = fields.Date(string="배합일", required=True, tracking=True,
                             default=fields.Date.context_today)
    shift = fields.Selection(SHIFT, string="교대", default="day", tracking=True)
    equipment_id = fields.Many2one(
        "iatf.equipment", string="배합기", ondelete="set null", tracking=True)
    product_id = fields.Many2one(
        "product.product", string="생산 품목", required=True, tracking=True,
        help="이 배합으로 생산할 사출품. 관리기준을 찾는 열쇠다.")
    production_id = fields.Many2one(
        "mrp.production", string="생산지시(MO)", ondelete="set null")
    lot_id = fields.Many2one(
        "stock.lot", string="생산 LOT", ondelete="set null",
        help="이 배합으로 만든 제품 LOT. SQ 는 'LOT별 혼합일지'를 요구한다.")
    operator_id = fields.Many2one("res.users", string="작업자",
                                  default=lambda self: self.env.user)

    line_ids = fields.One2many("iatf.blend.log.line", "blend_id", string="투입 내역")

    virgin_qty = fields.Float(string="신재(kg)", compute="_compute_qty", store=True,
                              digits=(12, 3))
    regrind_qty = fields.Float(string="재생재(kg)", compute="_compute_qty", store=True,
                               digits=(12, 3))
    additive_qty = fields.Float(string="첨가제(kg)", compute="_compute_qty", store=True,
                                digits=(12, 3))
    resin_qty = fields.Float(string="수지 계(kg)", compute="_compute_qty", store=True,
                             digits=(12, 3))
    total_qty = fields.Float(string="총 투입(kg)", compute="_compute_qty", store=True,
                             digits=(12, 3))

    standard_id = fields.Many2one(
        "iatf.blend.standard", string="적용 기준", compute="_compute_standard",
        store=True, readonly=True)
    limit_ratio = fields.Float(
        string="기준 상한(%)", compute="_compute_standard", store=True, readonly=True,
        digits=(5, 2), help="배합 시점 기준의 복사본. 기준을 나중에 바꿔도 이 값은 안 바뀐다.")
    limit_additive_ratio = fields.Float(
        string="첨가제 상한(%)", compute="_compute_standard", store=True, readonly=True,
        digits=(5, 2))
    ratio_basis = fields.Selection(
        RATIO_BASIS, string="비율 산정 기준", compute="_compute_standard", store=True,
        readonly=True)

    regrind_ratio = fields.Float(string="재생재 비율(%)", compute="_compute_ratio",
                                 store=True, digits=(5, 2))
    additive_ratio = fields.Float(string="첨가제 비율(%)", compute="_compute_ratio",
                                  store=True, digits=(5, 2))
    result = fields.Selection(
        [("pending", "미판정"), ("ok", "기준 이내"), ("ng", "기준 초과")],
        string="판정", compute="_compute_result", store=True, readonly=True,
        tracking=True, default="pending")
    ng_action = fields.Text(string="기준 초과 시 조치")

    state = fields.Selection([("draft", "작성중"), ("done", "완료")],
                             default="draft", tracking=True, string="상태")
    note = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == _("신규"):
                vals["name"] = self.env["ir.sequence"].next_by_code(
                    "iatf.blend.log") or _("신규")
        return super().create(vals_list)

    @api.depends("line_ids.qty", "line_ids.material_type")
    def _compute_qty(self):
        for rec in self:
            buckets = {"virgin": 0.0, "regrind": 0.0, "additive": 0.0}
            for line in rec.line_ids:
                buckets[line.material_type] = buckets.get(line.material_type, 0.0) + line.qty
            rec.virgin_qty = buckets["virgin"]
            rec.regrind_qty = buckets["regrind"]
            rec.additive_qty = buckets["additive"]
            rec.resin_qty = buckets["virgin"] + buckets["regrind"]
            rec.total_qty = rec.resin_qty + buckets["additive"]

    @api.depends("product_id", "blend_date", "company_id")
    def _compute_standard(self):
        """기준을 배합 시점 기준으로 찾아 값까지 복사해 둔다.

        `standard_id` 만 들고 있으면 기준 레코드를 수정하는 순간 과거 판정이 같이
        움직인다. 그래서 상한값 자체를 여기에 저장한다.
        """
        Standard = self.env["iatf.blend.standard"]
        for rec in self:
            std = Standard._standard_for(
                rec.product_id, rec.blend_date, company=rec.company_id)
            rec.standard_id = std
            rec.limit_ratio = std.max_regrind_ratio if std else 0.0
            rec.limit_additive_ratio = std.max_additive_ratio if std else 0.0
            rec.ratio_basis = std.ratio_basis if std else False

    @api.depends("virgin_qty", "regrind_qty", "additive_qty", "resin_qty",
                 "total_qty", "ratio_basis")
    def _compute_ratio(self):
        for rec in self:
            base = rec.total_qty if rec.ratio_basis == "total" else rec.resin_qty
            rec.regrind_ratio = (rec.regrind_qty / base * 100.0) if base else 0.0
            rec.additive_ratio = (rec.additive_qty / rec.total_qty * 100.0) if rec.total_qty else 0.0

    def _judge(self):
        """판정 규칙 하나. 계산 필드와 백스톱 제약이 같은 함수를 쓰게 한다."""
        self.ensure_one()
        if not self.line_ids or not self.total_qty:
            return "pending"
        if not self.standard_id:
            # 기준이 없으면 '합격'이라고 말할 근거가 없다. 완료는 막지 않되
            # 미판정으로 남겨 '기준 미등록 배합' 목록에 걸리게 한다.
            return "pending"
        if self.regrind_ratio > self.limit_ratio:
            return "ng"
        if self.limit_additive_ratio and self.additive_ratio > self.limit_additive_ratio:
            return "ng"
        return "ok"

    @api.depends("regrind_ratio", "additive_ratio", "limit_ratio",
                 "limit_additive_ratio", "standard_id", "line_ids", "total_qty")
    def _compute_result(self):
        for rec in self:
            rec.result = rec._judge()

    @api.constrains("result", "regrind_ratio", "limit_ratio", "line_ids")
    def _check_result_matches_standard(self):
        """저장된 판정이 계산 결과와 다르면 막는다.

        `_compute_result` 만으로는 부족하다. 의존 필드를 건드리지 않는 write
        (예: result 만 'ok' 로 덮어쓰기)에서는 재계산이 돌지 않는다. 기준을 넘긴
        배합에 '기준 이내'를 적어 넣는 경로가 곧 허위기재(SQ 다수미흡 25%)다.
        """
        labels = dict(self._fields["result"].selection)
        for rec in self:
            judged = rec._judge()
            if rec.result != judged:
                raise ValidationError(_(
                    "'%(name)s': 재생재 비율 %(ratio).2f%% 는 기준 %(limit).2f%% 대비 "
                    "'%(judged)s' 입니다. '%(given)s' 으로 저장할 수 없습니다.",
                    name=rec.name, ratio=rec.regrind_ratio, limit=rec.limit_ratio,
                    judged=labels.get(judged), given=labels.get(rec.result) or _("미판정")))

    @api.constrains("blend_date")
    def _check_not_future(self):
        for rec in self:
            if rec.blend_date and rec.blend_date > fields.Date.context_today(rec):
                raise ValidationError(_("'%s': 배합일을 미래로 기록할 수 없습니다.", rec.name))

    def _missing_for_done(self):
        """완료에 부족한 것. 버튼과 백스톱이 같은 규칙을 쓴다."""
        self.ensure_one()
        if not self.line_ids:
            return _("투입 내역이 없습니다.")
        if self.total_qty <= 0:
            return _("투입량 합계가 0 입니다.")
        no_source = self.line_ids.filtered(
            lambda l: l.material_type == "regrind" and not l.regrind_log_id)
        if no_source:
            return _("재생재 투입 줄에 분쇄일지(출처)가 연결되지 않았습니다.")
        if self.result == "ng" and not self.ng_action:
            return _("기준을 초과했는데 조치 내용이 없습니다.")
        return False

    @api.constrains("state", "line_ids", "result", "ng_action")
    def _check_done_is_complete(self):
        """완료 상태의 백스톱. 완료 후 줄을 지우는 경로는 라인 쪽에서 다시 막는다."""
        for rec in self:
            if rec.state != "done":
                continue
            problem = rec._missing_for_done()
            if problem:
                raise ValidationError(_("%(name)s: %(problem)s",
                                        name=rec.name, problem=problem))

    def action_done(self):
        for rec in self:
            problem = rec._missing_for_done()
            if problem:
                raise UserError(_("%(name)s: %(problem)s", name=rec.name, problem=problem))
            rec.state = "done"

    def action_draft(self):
        self.state = "draft"


class IatfBlendLogLine(models.Model):
    _name = "iatf.blend.log.line"
    _description = "배합 투입 내역"
    _order = "blend_id, sequence, id"

    blend_id = fields.Many2one("iatf.blend.log", required=True, ondelete="cascade",
                               string="배합일지")
    sequence = fields.Integer(default=10)
    material_type = fields.Selection(MATERIAL_TYPE, string="구분", required=True,
                                     default="virgin")
    product_id = fields.Many2one("product.product", string="원료 품목", required=True)
    lot_id = fields.Many2one("stock.lot", string="원료 LOT", ondelete="set null")
    regrind_log_id = fields.Many2one(
        "iatf.regrind.log", string="분쇄일지(출처)", ondelete="restrict",
        help="재생재는 어느 분쇄에서 나온 것인지 연결해야 추적이 이어진다.")
    qty = fields.Float(string="투입량(kg)", required=True, digits=(12, 3))
    note = fields.Char(string="비고")

    @api.constrains("qty")
    def _check_qty(self):
        for rec in self:
            if rec.qty <= 0:
                raise ValidationError(_("투입량은 0보다 커야 합니다. (%s)",
                                        rec.product_id.display_name))

    @api.constrains("material_type", "regrind_log_id")
    def _check_source_matches_type(self):
        """신재 줄에 분쇄일지를 달아 두면 재생재를 신재로 계상한 셈이 된다."""
        for rec in self:
            if rec.material_type != "regrind" and rec.regrind_log_id:
                raise ValidationError(_(
                    "분쇄일지는 재생재 줄에만 연결할 수 있습니다. (%s)",
                    rec.product_id.display_name))

    @api.constrains("material_type", "regrind_log_id", "qty", "blend_id")
    def _check_parent_still_complete(self):
        """부모의 `@api.constrains` 는 점 표기를 지원하지 않아 줄 필드 변경으로는
        돌지 않는다. 그래서 줄 쪽에서 부모를 다시 검사한다."""
        for rec in self:
            parent = rec.blend_id
            if parent.state == "done":
                problem = parent._missing_for_done()
                if problem:
                    raise ValidationError(_("%(name)s: %(problem)s",
                                            name=parent.name, problem=problem))

    def unlink(self):
        """줄을 지운 뒤 부모를 다시 검사한다.

        자식 삭제는 부모의 `@api.constrains("line_ids")` 를 트리거하지 않는다.
        완료된 배합일지의 줄을 전부 지우면 투입 내역 없는 '완료' 기록이 남고,
        비율·판정이 0/미판정으로 굳는다.
        """
        parents = self.blend_id
        res = super().unlink()
        parents.exists()._check_done_is_complete()
        return res
