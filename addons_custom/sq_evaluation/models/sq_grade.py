from odoo import fields, models

from .sq_criteria import FRAMEWORK_SELECTION


class SqGrade(models.Model):
    """자체 평가 등급표 — 달성률(%) 구간 → 등급. 설정 메뉴에서 편집.
    (공식 주관사 등급표가 확정되면 여기 값만 교체하면 됨 — 코드 수정 불필요)"""
    _name = "sq.grade"
    _description = "자체 평가 등급표"
    _order = "framework, min_pct desc"

    framework = fields.Selection(FRAMEWORK_SELECTION, string="평가체계", required=True, default="sq")
    name = fields.Char(string="등급", required=True)
    min_pct = fields.Float(string="달성률 하한 (%)", required=True,
                           help="달성률이 이 값 이상이면 이 등급 (높은 구간부터 판정)")
    label = fields.Char(string="판정 라벨", help="예: 심사 준비 완료 / 보완 필요")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("uniq_fw_grade", "unique(framework, name)", "같은 평가체계에 동일 등급이 이미 있습니다."),
    ]
