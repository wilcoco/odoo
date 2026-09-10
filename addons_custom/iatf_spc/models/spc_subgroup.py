from odoo import api, fields, models


class IatfSpcSubgroup(models.Model):
    _name = "iatf.spc.subgroup"
    _description = "SPC Subgroup Data"
    _order = "sequence, id"

    study_id = fields.Many2one(
        "iatf.spc.study", string="SPC Study", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="Subgroup #", default=10)
    sample_date = fields.Datetime(string="Sample Date", default=fields.Datetime.now)
    operator_id = fields.Many2one("res.users", string="Operator", default=lambda self: self.env.user)

    # Up to 10 individual measurements per subgroup
    x1 = fields.Float(string="X1", digits=(16, 4))
    x2 = fields.Float(string="X2", digits=(16, 4))
    x3 = fields.Float(string="X3", digits=(16, 4))
    x4 = fields.Float(string="X4", digits=(16, 4))
    x5 = fields.Float(string="X5", digits=(16, 4))
    x6 = fields.Float(string="X6", digits=(16, 4))
    x7 = fields.Float(string="X7", digits=(16, 4))
    x8 = fields.Float(string="X8", digits=(16, 4))
    x9 = fields.Float(string="X9", digits=(16, 4))
    x10 = fields.Float(string="X10", digits=(16, 4))

    # 실제로 채워진 표본 수. 0 이면 '부분군 크기 n 전부 입력됨' 으로 본다(수기 입력 호환).
    # 자동 주입(공정검사 → SPC)은 값을 하나씩 채우므로 이 수를 올려 가며 쓴다.
    # 이게 없으면 x1 하나만 넣은 부분군의 x2~x5 가 0 으로 평균에 들어가
    # 10.0 측정 하나가 평균 2.0 / 범위 10 으로 왜곡된다. (제3자 검토 Q14)
    sample_count = fields.Integer(string="입력 표본 수", default=0)
    origins = fields.Char(string="자동 주입 출처",
                          help="공정검사 라인 키 목록. 같은 판정을 두 번 눌러도 중복 주입되지 않게.")

    # Computed
    sg_mean = fields.Float(string="X̄", digits=(16, 4), compute="_compute_stats", store=True)
    sg_range = fields.Float(string="R", digits=(16, 4), compute="_compute_stats", store=True)
    is_ooc = fields.Boolean(string="Out of Control", default=False)

    notes = fields.Char(string="Notes")

    def _get_values(self):
        """통계에 쓸 값. 입력 표본 수가 있으면 그만큼만, 없으면 부분군 크기만큼.

        0 을 '빈 칸' 으로 걸러내면 안 된다 — 0 은 유효한 측정값일 수 있다. 그래서
        몇 개가 입력됐는지를 따로 센다. (이전 코드의 `v != 0.0 or True` 는 항상 참이라
        아무것도 거르지 않았다.)
        """
        self.ensure_one()
        n = self.study_id.subgroup_size or 5
        if 1 <= (self.sample_count or 0) <= 10:
            n = min(n, self.sample_count)
        all_fields = [self.x1, self.x2, self.x3, self.x4, self.x5,
                       self.x6, self.x7, self.x8, self.x9, self.x10]
        return all_fields[:n]

    @api.depends("x1", "x2", "x3", "x4", "x5", "x6", "x7", "x8", "x9", "x10",
                 "sample_count", "study_id.subgroup_size")
    def _compute_stats(self):
        for sg in self:
            vals = sg._get_values()
            if vals:
                sg.sg_mean = sum(vals) / len(vals)
                sg.sg_range = max(vals) - min(vals)
            else:
                sg.sg_mean = 0.0
                sg.sg_range = 0.0
