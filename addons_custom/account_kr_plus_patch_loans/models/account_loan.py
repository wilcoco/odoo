from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class AccountLoan(models.Model):
    """차입금(대출) 약정을 한국식 운영에 맞춘다.

    오두 표준 `account_loans` 는 승인하면 상환 일정대로 전표를 만든다. 더존 등 다른 시스템에서
    이관한 전표가 이미 원장에 있는 기간에는 그 전표가 이중 계상이 되므로, 전표를 만들지 않고
    약정·상환일정만 관리하는 `기준정보 전용` 모드를 둔다.
    """

    _inherit = "account.loan"

    kr_manage_only = fields.Boolean(
        string="기준정보 전용",
        default=True,
        tracking=True,
        help="승인해도 전표를 만들지 않고 약정과 상환 일정만 관리합니다. "
        "전표가 이미 다른 경로(예: 더존 이관)로 원장에 들어오는 기간에 사용합니다.",
    )
    kr_open_ended = fields.Boolean(
        string="만기 미정",
        tracking=True,
        help="상환 일정이 아직 확정되지 않은 약정입니다. 기준정보 전용 승인에서 "
        "'원금 합계 = 차입금액' 검증을 건너뜁니다.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="대주(거래처)",
        tracking=True,
        help="돈을 빌려준 금융기관 또는 거래처입니다.",
    )
    kr_interest_rate = fields.Float(
        string="이자율 (%/년)",
        digits=(6, 3),
        tracking=True,
        help="현재 적용 이자율입니다. 변경 이력은 '이자율 이력'에 남깁니다.",
    )
    kr_rate_ids = fields.One2many(
        "account.loan.rate", "loan_id", string="이자율 이력",
    )
    kr_contract_no = fields.Char(string="약정번호", tracking=True)
    kr_limit_amount = fields.Monetary(string="약정 한도")
    kr_collateral = fields.Char(string="담보")
    kr_interest_day = fields.Integer(
        string="이자 지급일",
        help="매월 이자를 내는 날(1~31). 0이면 지정하지 않습니다.",
    )
    kr_purpose = fields.Char(string="자금 용도")
    kr_rollover_from_id = fields.Many2one(
        "account.loan",
        string="원 약정(차환 전)",
        tracking=True,
        help="만기에 같은 금액으로 연장(차환)한 경우, 상환된 원 약정을 지정합니다. "
        "합계를 낼 때 같은 자금이 두 번 잡히지 않도록 하는 근거가 됩니다.",
    )
    kr_rollover_to_ids = fields.One2many(
        "account.loan", "kr_rollover_from_id", string="연장 약정",
    )
    kr_new_money = fields.Monetary(
        string="신규 조달액",
        compute="_compute_kr_new_money",
        store=True,
        help="차환(연장) 약정은 새로 조달한 자금이 아니므로 0으로 집계합니다.",
    )

    # ------------------------------------------------------------------
    # 계산
    # ------------------------------------------------------------------
    @api.depends("amount_borrowed", "kr_rollover_from_id")
    def _compute_kr_new_money(self):
        for loan in self:
            loan.kr_new_money = 0.0 if loan.kr_rollover_from_id else loan.amount_borrowed

    @api.constrains("kr_interest_day")
    def _check_kr_interest_day(self):
        for loan in self:
            if loan.kr_interest_day and not 1 <= loan.kr_interest_day <= 31:
                raise UserError(_("이자 지급일은 1에서 31 사이여야 합니다."))

    @api.constrains("kr_rollover_from_id")
    def _check_kr_rollover_from(self):
        for loan in self:
            if loan.kr_rollover_from_id == loan:
                raise UserError(_("원 약정으로 자기 자신을 지정할 수 없습니다."))

    def kr_rate_on(self, date):
        """해당 일자에 적용되는 이자율. 이력이 없으면 현재 이자율을 돌려준다."""
        self.ensure_one()
        applicable = self.kr_rate_ids.filtered(lambda r: r.date_from <= date)
        if applicable:
            return applicable.sorted("date_from")[-1].rate
        return self.kr_interest_rate

    # ------------------------------------------------------------------
    # 승인
    # ------------------------------------------------------------------
    def _kr_check_master_data(self):
        """기준정보 전용 승인에 필요한 검증. 전표를 만들지 않으므로 계정·저널은 요구하지 않는다."""
        self.ensure_one()
        rounding = self.currency_id.rounding
        if not self.name:
            raise UserError(_("차입금 이름을 입력하세요."))
        if self.is_wrong_date:
            raise UserError(_("차입일은 상환 일정의 모든 회차 날짜보다 빨라야 합니다."))
        if not self.kr_open_ended and float_compare(self.amount_borrowed_difference, 0.0, precision_rounding=rounding) != 0:
            raise UserError(
                _(
                    "차입금액 %(amount)s 과 상환 일정의 원금 합계가 다릅니다(차이 %(diff)s). "
                    "만기·상환조건이 아직 확정되지 않은 약정이면 '만기 미정'을 켜세요.",
                    amount=self.currency_id.format(self.amount_borrowed),
                    diff=self.currency_id.format(self.amount_borrowed_difference),
                )
            )
        if float_compare(self.interest_difference, 0.0, precision_rounding=rounding) != 0:
            raise UserError(_("이자 합계가 상환 일정의 이자 합과 다릅니다."))
        if self.duration_difference != 0:
            raise UserError(_("기간(회차 수)이 상환 일정의 회차 수와 다릅니다."))

    def action_confirm(self):
        """기준정보 전용은 전표 없이 승인하고, 표준 경로는 상태 전환 누락을 보정한다.

        표준 `action_confirm` 은 생성한 전표 중 **전기되지 않은 것이 하나라도 있을 때만**
        상태를 '실행 중'으로 바꾼다. 건너뛰기 날짜가 모든 회차를 덮거나 회차가 모두 과거라
        즉시 전기되면, 오류 없이 초안에 머문다. 그 경우를 보정한다.
        """
        managed = self.filtered("kr_manage_only")
        for loan in managed:
            loan._kr_check_master_data()
            loan.state = "running"
            loan.message_post(
                body=_(
                    "기준정보 전용으로 승인했습니다. 전표는 만들지 않습니다"
                    "(전표는 이관 자료로 이미 원장에 반영되어 있습니다)."
                )
            )
        rest = self - managed
        if rest:
            super(AccountLoan, rest).action_confirm()
            stuck = rest.filtered(lambda loan: loan.state == "draft")
            for loan in stuck:
                loan.state = "running"
                loan.message_post(
                    body=_(
                        "생성할 전표가 없거나 모두 전기되어 표준 로직이 상태를 바꾸지 않아, "
                        "'실행 중'으로 보정했습니다."
                    )
                )
        return True


class AccountLoanRate(models.Model):
    """차입금 이자율 이력 — 표준 모델에는 이자율 필드 자체가 없다."""

    _name = "account.loan.rate"
    _description = "차입금 이자율 이력"
    _order = "date_from, id"

    loan_id = fields.Many2one(
        "account.loan", string="차입금", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="loan_id.company_id", store=True)
    date_from = fields.Date(string="적용 시작일", required=True)
    rate = fields.Float(string="이자율 (%/년)", digits=(6, 3), required=True)
    reason = fields.Char(string="변경 사유")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._kr_sync_loan_rate()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._kr_sync_loan_rate()
        return result

    def _kr_sync_loan_rate(self):
        """가장 최근 적용 이자율을 약정의 현재 이자율에 반영한다."""
        for loan in self.loan_id:
            latest = loan.kr_rate_ids.sorted("date_from")[-1:]
            if latest:
                loan.kr_interest_rate = latest.rate
