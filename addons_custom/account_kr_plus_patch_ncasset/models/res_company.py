from odoo import fields, models


class ResCompany(models.Model):
    """자산별 계정과목을 만들 때 쓰는 기준 계정."""

    _inherit = "res.company"

    kr_land_base_account_id = fields.Many2one(
        "account.account",
        string="자산 기준 계정",
        domain="[('account_type', '=', 'asset_fixed')]",
        help="자산별 계정과목의 기준이 되는 계정입니다(예: 토지). "
        "자산별 계정 코드는 이 계정 코드 뒤에 자산 일련번호를 붙여 만듭니다.",
    )
    kr_land_down_account_id = fields.Many2one(
        "account.account",
        string="계약금 기준 계정",
        help="자산별 계약금 계정의 기준 계정입니다.",
    )
    kr_land_interim_account_id = fields.Many2one(
        "account.account",
        string="중도금 기준 계정",
        help="자산별 중도금 계정의 기준 계정입니다.",
    )
    kr_land_balance_account_id = fields.Many2one(
        "account.account",
        string="잔금 기준 계정",
        help="자산별 잔금 계정의 기준 계정입니다.",
    )
    kr_asset_reclass_journal_id = fields.Many2one(
        "account.journal",
        string="자산 재분류 저널",
        domain="[('type', '=', 'general')]",
        help="자산별 계정으로 원장을 옮기는 재분류 전표를 만들 때 쓰는 저널입니다.",
    )
