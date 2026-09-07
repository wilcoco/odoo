"""예비부품 분류체계와 적용표.

레거시(SPMSRT)는 분류 코드 4자리 한 칸에 4개 계층을 눌러 담았다. 'AIAA' 의
A/I/A/A 가 각각 부문·공정·설비군·기종이다. 그래서 이런 일이 생겼다.

  1. 계층을 하나 늘리거나 이름을 바꾸려면 코드 자리수를 건드려야 한다.
  2. 잎(부품이 달리는 기종)과 가지(A000, AA00 같은 묶음 노드)가 같은 표에 섞여
     있어서, 부품이 상위 묶음에 달려도 시스템이 막지 못했다.
  3. 분류가 트리라서 부품 하나가 한 자리만 가진다. 같은 베어링이 사출기와
     조립기에 함께 쓰이면 표현할 방법이 없었다.

여기서는 셋을 나눠 푼다.
  - 계층은 진짜 트리로 (parent_id). 코드는 자리별로 따로 저장하고, 레거시처럼
    이어붙인 'AIAA' 는 표시·검색용으로 계산해서 보여준다.
  - 부품은 최하위(기종)에만 달 수 있다. 묶음 노드는 부품을 받지 못한다.
  - "어디에 속하는가"(분류, 한 자리)와 "어디에 들어가는가"(적용, 여러 개)를
    다른 표로 둔다. 둘은 대체 관계가 아니라 둘 다 필요하다.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# 4단 고정. 레거시 코드 자리수와 1:1로 대응한다.
LEVELS = [
    ("division", "부문"),
    ("process", "공정"),
    ("group", "설비군"),
    ("model", "기종"),
]
LEVEL_RANK = {"division": 0, "process": 1, "group": 2, "model": 3}
LEAF_LEVEL = "model"


class IatfSpareCategory(models.Model):
    _name = "iatf.spare.category"
    _description = "예비부품 분류 (부문/공정/설비군/기종)"
    _parent_name = "parent_id"
    _parent_store = True
    _order = "full_code, name"
    _rec_names_search = ["complete_name", "full_code", "code"]

    name = fields.Char(string="분류명", required=True)
    # 자리 코드. 레거시는 한 자리였지만 늘어날 여지를 남긴다. 이어붙인 전체 코드는
    # full_code 가 계산한다 — 한 칸에 4계층을 담던 구조로 돌아가지 않기 위해서다.
    code = fields.Char(
        string="자리 코드", required=True,
        help="이 계층 한 단계의 코드만 넣는다. 상위 코드를 이어붙이지 않는다.",
    )
    level = fields.Selection(
        LEVELS, string="계층", required=True, default="division",
        help="부문 → 공정 → 설비군 → 기종. 한 단계씩만 내려간다.",
    )
    parent_id = fields.Many2one(
        "iatf.spare.category", string="상위 분류", index=True, ondelete="restrict",
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many("iatf.spare.category", "parent_id", string="하위 분류")
    child_count = fields.Integer(string="하위 분류 수", compute="_compute_counts")

    complete_name = fields.Char(
        string="전체 경로", compute="_compute_complete_name",
        recursive=True, store=True,
    )
    full_code = fields.Char(
        string="전체 코드", compute="_compute_full_code",
        recursive=True, store=True, index=True,
        help="상위부터 이어붙인 코드. 레거시 SPMSRT('AIAA')와 같은 모양이지만 "
             "저장은 자리별로 하고 이 값은 표시·검색용으로 계산한다.",
    )

    is_leaf = fields.Boolean(
        string="부품 등록 가능", compute="_compute_is_leaf", store=True,
        help="기종(최하위) 이면서 하위 분류가 없는 노드만 부품을 받는다.",
    )
    spare_ids = fields.One2many(
        "iatf.equipment.spare", "category_id", string="이 분류의 부품")
    spare_count = fields.Integer(string="부품 수", compute="_compute_counts")

    active = fields.Boolean(string="사용", default=True)
    note = fields.Char(string="비고")

    _sql_constraints = [
        # 같은 부모 밑에서 자리 코드가 겹치면 이어붙인 전체 코드가 충돌한다.
        ("uniq_code_under_parent", "unique(parent_id, code)",
         "같은 상위 분류 아래에 같은 자리 코드가 이미 있습니다."),
    ]

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = "%s : %s" % (rec.parent_id.complete_name, rec.name)
            else:
                rec.complete_name = rec.name

    @api.depends("code", "parent_id.full_code")
    def _compute_full_code(self):
        for rec in self:
            rec.full_code = "%s%s" % (rec.parent_id.full_code or "", rec.code or "")

    @api.depends("level", "child_ids")
    def _compute_is_leaf(self):
        for rec in self:
            rec.is_leaf = rec.level == LEAF_LEVEL and not rec.child_ids

    def _compute_counts(self):
        child_data = {
            parent.id: count
            for parent, count in self.env["iatf.spare.category"]._read_group(
                [("parent_id", "in", self.ids)], ["parent_id"], ["__count"])
        }
        spare_data = {
            cat.id: count
            for cat, count in self.env["iatf.equipment.spare"]._read_group(
                [("category_id", "in", self.ids)], ["category_id"], ["__count"])
        }
        for rec in self:
            rec.child_count = child_data.get(rec.id, 0)
            rec.spare_count = spare_data.get(rec.id, 0)

    @api.constrains("parent_id")
    def _check_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("분류 계층이 순환됩니다. 자기 자신을 상위로 둘 수 없습니다."))

    @api.constrains("parent_id", "level")
    def _check_level_chain(self):
        """계층을 건너뛰거나 거꾸로 매달 수 없다.

        레거시는 코드 자리로 계층이 강제됐다(2번째 자리 = 공정). 트리로 옮기면서
        그 강제가 사라지면 '공정' 밑에 '부문' 이 오는 트리가 만들어지고, 이어붙인
        전체 코드가 레거시와 다른 의미를 갖게 된다.
        """
        labels = dict(LEVELS)
        for rec in self:
            if not rec.parent_id:
                if rec.level != "division":
                    raise ValidationError(_(
                        "'%(name)s': 최상위 분류는 '부문' 이어야 합니다. 지금은 '%(level)s' 입니다.",
                        name=rec.name, level=labels[rec.level]))
                continue
            if LEVEL_RANK[rec.level] != LEVEL_RANK[rec.parent_id.level] + 1:
                raise ValidationError(_(
                    "'%(child)s'(%(child_level)s) 을 '%(parent)s'(%(parent_level)s) 아래에 "
                    "둘 수 없습니다.\n계층은 부문 → 공정 → 설비군 → 기종 순으로 한 단계씩만 "
                    "내려갑니다.",
                    child=rec.name, child_level=labels[rec.level],
                    parent=rec.parent_id.name, parent_level=labels[rec.parent_id.level]))

    @api.constrains("level", "child_ids", "spare_ids")
    def _check_leaf_holds_parts(self):
        """부품이 달린 분류는 잎으로 남아야 한다.

        레거시 ②번 문제 — 잎과 가지가 한 표에 섞인 상태 — 를 여기서 막는다.
        잎에서 벗어나는 길이 두 갈래인데 둘 다 막아야 한다.
          - 부품을 가진 노드 밑에 하위 분류를 만드는 것
          - 부품을 가진 기종의 계층을 '설비군' 등으로 올려버리는 것
        부품 쪽 `_check_category_is_leaf` 는 부품이 움직일 때만 도는지라,
        분류만 고치면 그 검사를 거치지 않고 빠져나간다.
        """
        labels = dict(LEVELS)
        for rec in self:
            if not rec.spare_ids:
                continue
            if rec.child_ids:
                raise ValidationError(_(
                    "'%(name)s' 에는 부품 %(count)s 건이 달려 있어 하위 분류를 만들 수 없습니다.\n"
                    "묶음 노드(가지)와 부품이 달리는 노드(잎)를 섞지 않습니다.",
                    name=rec.name, count=len(rec.spare_ids)))
            if rec.level != LEAF_LEVEL:
                raise ValidationError(_(
                    "'%(name)s' 에는 부품 %(count)s 건이 달려 있어 계층을 "
                    "'%(level)s' 로 바꿀 수 없습니다.\n"
                    "부품을 먼저 다른 기종으로 옮기십시오.",
                    name=rec.name, count=len(rec.spare_ids), level=labels[rec.level]))

    def action_view_spares(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("%s 부품", self.name),
            "res_model": "iatf.equipment.spare",
            "view_mode": "list,form",
            "domain": [("category_id", "=", self.id)],
            "context": {"default_category_id": self.id},
        }


class IatfSpareApplication(models.Model):
    """부품 적용표 — 이 부품이 어느 설비에 들어가는가 (다대다).

    분류(`category_id`)와 역할이 다르다. 분류는 "이 부품이 어디에 속하는가" 한
    자리를 정하고, 적용표는 "이 부품이 어디어디에 들어가는가"를 여러 개 적는다.
    같은 베어링이 사출기와 조립기에 함께 쓰이는 상황은 분류로는 표현할 수 없다.
    """

    _name = "iatf.spare.application"
    _description = "예비부품 적용 설비"
    _order = "spare_id, equipment_id"

    spare_id = fields.Many2one(
        "iatf.equipment.spare", string="예비부품", required=True,
        index=True, ondelete="cascade")
    equipment_id = fields.Many2one(
        "iatf.equipment", string="적용 설비", required=True,
        index=True, ondelete="cascade")
    qty_per_unit = fields.Float(
        string="설비 1대당 소요", default=1.0,
        help="이 설비 한 대에 들어가는 개수. 설비마다 다를 수 있어 부품 마스터가 "
             "아니라 여기에 둔다.")
    position = fields.Char(
        string="장착 위치", help="예: 형체 실린더 상부, 3번 축")
    note = fields.Char(string="비고")

    # 화면 필터·그룹용. 적용표에서 바로 분류로 걸러 보기 위해 관련 필드를 편다.
    category_id = fields.Many2one(
        related="spare_id.category_id", string="부품 분류", store=True, index=True)

    _sql_constraints = [
        ("uniq_spare_equipment", "unique(spare_id, equipment_id)",
         "이 부품은 해당 설비에 이미 등록되어 있습니다."),
    ]

    @api.constrains("qty_per_unit")
    def _check_qty(self):
        for rec in self:
            if rec.qty_per_unit <= 0:
                raise ValidationError(_(
                    "'%s': 설비 1대당 소요 수량은 0보다 커야 합니다.",
                    rec.spare_id.name or ""))

    @api.depends("spare_id.name", "equipment_id.complete_name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = "%s → %s" % (
                rec.spare_id.name or "", rec.equipment_id.complete_name or "")
