from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Command

# 자산별 계정 종류 — 기준 계정(회사 설정)에서 자산별 자식 계정을 만들 때 쓴다.
KR_ASSET_ACCOUNT_KINDS = [
    ("asset", "자산(취득원가)"),
    ("down_payment", "계약금"),
    ("interim_payment", "중도금"),
    ("balance_payment", "잔금"),
    ("other", "기타"),
]
KR_COMPANY_BASE_FIELD = {
    "asset": "kr_land_base_account_id",
    "down_payment": "kr_land_down_account_id",
    "interim_payment": "kr_land_interim_account_id",
    "balance_payment": "kr_land_balance_account_id",
}


class AccountAsset(models.Model):
    """비유동자산을 한국식 운영에 맞춘다.

    - 토지처럼 **감가상각을 하지 않고 그때그때 평가**하는 자산을 한 번에 설정한다.
    - 토지 등은 자산 한 건마다 계정과목을 따로 두고 싶은 경우가 있다. 기준 계정 코드 뒤에
      일련번호를 붙인 자식 계정을 만들어(예: 800003 → 8000031, 8000032) 자산에 연결한다.
      계정 유형·조정 여부·태그를 기준 계정에서 그대로 물려받으므로 재무제표·회계 통계에서
      기준 계정과 같은 성격(예: 토지)으로 잡힌다.
    - 계약 단계(계약금·중도금·잔금)도 같은 방식으로 자산별 계정을 만들 수 있다.
    """

    _inherit = "account.asset"

    kr_non_depreciable = fields.Boolean(
        string="비상각(평가형)",
        tracking=True,
        help="토지처럼 감가상각을 하지 않는 자산입니다. 감가상각 제외금액을 취득원가와 같게 맞춰 "
        "감가상각 전표가 생기지 않게 합니다. 가치 변동은 '재평가'로 반영합니다.",
    )
    kr_asset_no = fields.Integer(
        string="자산 일련번호",
        help="자산별 계정과목 코드에 붙는 번호입니다(기준 계정 코드 + 이 번호). 비우면 자동으로 매깁니다.",
    )
    kr_account_ids = fields.One2many(
        "account.asset.kr.account", "asset_id", string="자산별 계정과목",
    )
    kr_account_count = fields.Integer(compute="_compute_kr_account_count")

    # ------------------------------------------------------------------
    # 비상각 처리
    # ------------------------------------------------------------------
    @api.onchange("kr_non_depreciable")
    def _onchange_kr_non_depreciable(self):
        for asset in self:
            if asset.kr_non_depreciable:
                asset.salvage_value = asset.original_value

    # 값 검증은 저장 직후에 돌기 때문에, 제외금액 보정은 반드시 **저장 전**에 해야 한다.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("kr_non_depreciable"):
                vals["salvage_value"] = vals.get("original_value", 0.0)
        return super().create(vals_list)

    def write(self, vals):
        keys = {"kr_non_depreciable", "original_value", "salvage_value"}
        if not (keys & set(vals)):
            return super().write(vals)
        result = True
        for asset in self:
            asset_vals = dict(vals)
            non_depreciable = asset_vals.get("kr_non_depreciable", asset.kr_non_depreciable)
            if non_depreciable and asset.state not in ("close", "cancelled"):
                # 취득원가가 같은 write 안에서 바뀌면 그 값에, 아니면 현재 취득원가에 맞춘다.
                asset_vals["salvage_value"] = asset_vals.get("original_value", asset.original_value)
            result = super(AccountAsset, asset).write(asset_vals) and result
        return result

    @api.constrains("kr_non_depreciable", "salvage_value", "original_value")
    def _check_kr_non_depreciable(self):
        for asset in self:
            if not asset.kr_non_depreciable:
                continue
            if asset.currency_id.compare_amounts(asset.salvage_value, asset.original_value) != 0:
                raise UserError(
                    _("비상각 자산은 감가상각 제외금액이 취득원가와 같아야 합니다: %s", asset.name)
                )

    # ------------------------------------------------------------------
    # 자산별 계정과목
    # ------------------------------------------------------------------
    @api.depends("kr_account_ids")
    def _compute_kr_account_count(self):
        for asset in self:
            asset.kr_account_count = len(asset.kr_account_ids)

    def _kr_next_asset_no(self, base_account):
        """기준 계정 아래에서 아직 쓰지 않은 가장 작은 일련번호."""
        self.ensure_one()
        Account = self.env["account.account"].with_company(self.company_id)
        used = set(
            self.env["account.asset.kr.account"]
            .search([("base_account_id", "=", base_account.id)])
            .mapped("asset_id.kr_asset_no")
        )
        number = 1
        while number in used or Account.search_count([("code", "=", "%s%d" % (base_account.code, number))]):
            number += 1
        return number

    def _kr_get_or_create_account(self, base_account, number, label):
        """기준 계정 코드 + 일련번호로 자식 계정을 찾거나 만든다(멱등).

        계정 유형·조정 여부·태그를 기준 계정에서 물려받는다. 코드가 기준 계정으로 시작하므로
        코드 접두사로 매핑하는 재무제표(재무상태표(KR) 등)에서도 같은 항목에 잡힌다.
        """
        self.ensure_one()
        company = self.company_id
        code = "%s%d" % (base_account.code, number)
        Account = self.env["account.account"].with_company(company)
        account = Account.search([("code", "=", code)], limit=1)
        if account:
            return account
        return Account.create(
            {
                "code": code,
                "name": label,
                "account_type": base_account.account_type,
                "reconcile": base_account.reconcile,
                "company_ids": [Command.link(company.id)],
                "tag_ids": [Command.set(base_account.tag_ids.ids)],
            }
        )

    def _kr_base_account(self, kind):
        self.ensure_one()
        field_name = KR_COMPANY_BASE_FIELD.get(kind)
        base = self.company_id[field_name] if field_name else False
        if not base and kind in ("asset", "other"):
            # 기준 계정을 따로 설정하지 않았으면 자산에 이미 연결된 계정을 기준으로 삼는다.
            base = self.account_asset_id
        if not base:
            raise UserError(
                _(
                    "‘%(kind)s’의 기준 계정이 설정되어 있지 않습니다. 회사 설정의 "
                    "‘자산별 계정 기준’에서 먼저 지정하세요.",
                    kind=dict(KR_ASSET_ACCOUNT_KINDS).get(kind, kind),
                )
            )
        return base

    def action_kr_create_accounts(self, kinds=None):
        """자산별 계정과목을 만든다. 기본은 자산(취득원가) + 계약 3단계."""
        kinds = kinds or ["asset", "down_payment", "interim_payment", "balance_payment"]
        KrAccount = self.env["account.asset.kr.account"]
        created = self.env["account.account"]
        for asset in self:
            for kind in kinds:
                base = asset._kr_base_account(kind)
                if not asset.kr_asset_no:
                    asset.kr_asset_no = asset._kr_next_asset_no(base)
                existing = asset.kr_account_ids.filtered(lambda line: line.kind == kind)
                if existing:
                    continue
                label = "%s - %s" % (base.name, asset.name)
                account = asset._kr_get_or_create_account(base, asset.kr_asset_no, label)
                KrAccount.create(
                    {
                        "asset_id": asset.id,
                        "kind": kind,
                        "base_account_id": base.id,
                        "account_id": account.id,
                    }
                )
                created |= account
                if kind == "asset":
                    asset.account_asset_id = account
        return created

    def action_kr_create_asset_account(self):
        """자산(취득원가) 계정만 만들고 자산에 연결한다."""
        return self.action_kr_create_accounts(kinds=["asset"])

    def action_kr_open_accounts(self):
        self.ensure_one()
        return {
            "name": _("자산별 계정과목"),
            "type": "ir.actions.act_window",
            "res_model": "account.account",
            "view_mode": "list,form",
            "domain": [("id", "in", self.kr_account_ids.account_id.ids)],
        }

    def action_kr_open_reclass_wizard(self):
        """원장 잔액을 자산별 계정으로 옮기는 재분류 전표(초안) 마법사를 연다."""
        return {
            "name": _("자산별 계정 재분류"),
            "type": "ir.actions.act_window",
            "res_model": "account.asset.kr.reclass.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_asset_ids": self.ids},
        }


class AccountAssetKrAccount(models.Model):
    """자산 한 건에 연결된 계정과목(취득원가·계약금·중도금·잔금)."""

    _name = "account.asset.kr.account"
    _description = "자산별 계정과목"
    _order = "asset_id, kind"

    asset_id = fields.Many2one(
        "account.asset", string="자산", required=True, ondelete="cascade", index=True,
    )
    company_id = fields.Many2one(related="asset_id.company_id", store=True)
    kind = fields.Selection(KR_ASSET_ACCOUNT_KINDS, string="구분", required=True)
    base_account_id = fields.Many2one("account.account", string="기준 계정", required=True)
    account_id = fields.Many2one("account.account", string="계정과목", required=True)
    note = fields.Char(string="비고")

    _sql_constraints = [
        (
            "asset_kind_uniq",
            "unique(asset_id, kind)",
            "한 자산에 같은 구분의 계정과목은 하나만 둘 수 있습니다.",
        ),
    ]
