from odoo import fields, models


class MrpBom(models.Model):
    _inherit = "mrp.bom"

    # [2026-09-18 확정 BOM 보호] BOM 저장 시 변경요청(CR)을 자동 생성하고 미승인 CR 로 잠그던 훅은
    # 제거했다. BOM 변경 통제·이력·결재는 escon_bom_util(활성 잠금 + 개정 결재 + 불변 이력)이 맡는다.
    # 이미 생성된 자동 CR 은 데이터로 남긴다. 필드는 기존 뷰 호환을 위해 유지한다.
    change_locked = fields.Boolean(string="변경 잠금(구)", default=False,
                                   help="구 자동 변경요청 훅의 흔적. 더 이상 잠금에 쓰지 않는다.")
