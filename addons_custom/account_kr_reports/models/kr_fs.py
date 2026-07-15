from odoo import api, fields, models, _

# K-GAAP 표준 골격 — 오두 계정유형(account_type) 기반 기본 매핑.
# 매핑 조정은 kr.fs.line 마스터에서(계정 추가/제외) — 코드 수정 불필요. (리포트 #29)
BS_SEED = [
    ("CA", "유동자산", "asset_receivable,asset_cash,asset_current,asset_prepayments", 1, 1),
    ("NCA", "비유동자산", "asset_non_current,asset_fixed", 1, 1),
    ("TA", "자산총계", "=CA+NCA", 0, 1),
    ("CL", "유동부채", "liability_payable,liability_credit_card,liability_current", 1, -1),
    ("NCL", "비유동부채", "liability_non_current", 1, -1),
    ("TL", "부채총계", "=CL+NCL", 0, 1),
    ("EQ", "자본금·잉여금", "equity,equity_unaffected", 1, -1),
    ("NIY", "당기순이익(누계)", "income,income_other,expense,expense_depreciation,expense_direct_cost", 1, -1),
    ("TE", "자본총계", "=EQ+NIY", 0, 1),
    ("TLE", "부채와 자본총계", "=TL+TE", 0, 1),
]
PL_SEED = [
    ("REV", "매출액", "income", 1, -1),
    ("COGS", "매출원가", "expense_direct_cost", 1, 1),
    ("GP", "매출총이익", "=REV-COGS", 0, 1),
    ("SGA", "판매비와관리비", "expense,expense_depreciation", 1, 1),
    ("OP", "영업이익", "=GP-SGA", 0, 1),
    ("NOI", "영업외수익", "income_other", 1, -1),
    ("NI", "당기순이익", "=OP+NOI", 0, 1),
]


class KrFsLine(models.Model):
    """재무제표 라인 마스터 — account_type 기본 매핑 + 계정 추가/제외로 조정."""
    _name = "kr.fs.line"
    _description = "K-재무제표 라인 정의"
    _order = "report, sequence, id"

    report = fields.Selection([("bs", "재무상태표"), ("pl", "손익계산서")], required=True)
    sequence = fields.Integer(default=10)
    code = fields.Char(string="코드", required=True)
    name = fields.Char(string="항목명", required=True)
    account_types = fields.Char(string="계정유형(콤마)",
                                help="오두 account_type 목록. '=A+B' 형식이면 다른 라인 합산식")
    extra_account_ids = fields.Many2many(
        "account.account", "kr_fs_line_extra_rel", string="추가 계정",
        help="유형 매핑 외에 이 라인에 포함할 계정 (예: 영업외비용 재분류)")
    exclude_account_ids = fields.Many2many(
        "account.account", "kr_fs_line_excl_rel", string="제외 계정")
    sign = fields.Integer(string="부호", default=1, help="표시 부호 (수익계열은 -1: 대변잔액 양수화)")
    bold = fields.Boolean(string="합계 강조", default=False)

    _sql_constraints = [("code_report_uniq", "unique(report, code)", "같은 보고서에 코드 중복")]

    @api.model
    def ensure_seed(self):
        for report, seed in (("bs", BS_SEED), ("pl", PL_SEED)):
            for i, (code, name, types, _lvl, sign) in enumerate(seed):
                if not self.search_count([("report", "=", report), ("code", "=", code)]):
                    self.create({"report": report, "code": code, "name": name,
                                 "sequence": (i + 1) * 10, "account_types": types,
                                 "sign": sign, "bold": types.startswith("=")})
        return True


class KrFinancialStatement(models.TransientModel):
    """K-GAAP 양식 재무상태표/손익계산서 조회."""
    _name = "kr.financial.statement"
    _description = "K-재무제표"

    report = fields.Selection([("bs", "재무상태표"), ("pl", "손익계산서")],
                              required=True, default="bs")
    date_to = fields.Date(string="기준일(까지)", required=True, default=fields.Date.context_today)
    date_from = fields.Date(string="기간 시작(손익)",
                            default=lambda self: fields.Date.context_today(self).replace(month=1, day=1))
    line_ids = fields.One2many("kr.financial.statement.line", "statement_id", string="라인")
    currency_id = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id)

    def action_compute(self):
        self.ensure_one()
        self.env["kr.fs.line"].ensure_seed()
        self.line_ids.unlink()
        AML = self.env["account.move.line"]
        masters = self.env["kr.fs.line"].search([("report", "=", self.report)])
        amounts = {}
        # 1패스: 유형/계정 라인
        for m in masters.filtered(lambda l: not (l.account_types or "").startswith("=")):
            types = [t.strip() for t in (m.account_types or "").split(",") if t.strip()]
            dom = [("parent_state", "=", "posted"), ("date", "<=", self.date_to)]
            if self.report == "pl" and self.date_from:
                dom.append(("date", ">=", self.date_from))
            tdom = []
            if types:
                tdom = [("account_id.account_type", "in", types)]
            if m.extra_account_ids:
                tdom = ["|"] + tdom + [("account_id", "in", m.extra_account_ids.ids)] if tdom \
                    else [("account_id", "in", m.extra_account_ids.ids)]
            dom += tdom
            if m.exclude_account_ids:
                dom.append(("account_id", "not in", m.exclude_account_ids.ids))
            data = AML.read_group(dom, ["balance:sum"], [])
            bal = (data[0]["balance"] or 0.0) if data else 0.0
            amounts[m.code] = bal * (m.sign or 1)
        # 2패스: 합산식 (=A+B / =A-B)
        for m in masters.filtered(lambda l: (l.account_types or "").startswith("=")):
            expr = m.account_types[1:]
            val, op = 0.0, 1
            token = ""
            for ch in expr + "+":
                if ch in "+-":
                    if token:
                        val += op * amounts.get(token.strip(), 0.0)
                    op = 1 if ch == "+" else -1
                    token = ""
                else:
                    token += ch
            amounts[m.code] = val
        Line = self.env["kr.financial.statement.line"]
        for m in masters:
            Line.create({"statement_id": self.id, "sequence": m.sequence,
                         "name": m.name, "amount": amounts.get(m.code, 0.0), "bold": m.bold})
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": self.id,
                "view_mode": "form", "target": "current", "name": _("K-재무제표")}

    @api.model
    def action_open(self):
        rec = self.create({})
        rec.action_compute()
        return {"type": "ir.actions.act_window", "res_model": self._name, "res_id": rec.id,
                "view_mode": "form", "target": "current", "name": _("K-재무제표")}


class KrFinancialStatementLine(models.TransientModel):
    _name = "kr.financial.statement.line"
    _description = "K-재무제표 라인"
    _order = "sequence, id"

    statement_id = fields.Many2one("kr.financial.statement", required=True, ondelete="cascade")
    sequence = fields.Integer()
    name = fields.Char(string="항목")
    amount = fields.Monetary(string="금액", currency_field="currency_id")
    currency_id = fields.Many2one(related="statement_id.currency_id")
    bold = fields.Boolean()
