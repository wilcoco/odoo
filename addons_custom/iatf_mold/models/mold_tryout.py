from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class IatfMoldTryout(models.Model):
    """시사출(T/O) 보고서 — SQ 4_5.

    신규 제작·이관·수정 후 금형을 양산에 올리기 전에 시험 사출한 결과를 남긴다.
    동종업체 SQ 실사 감점 사유가 "이관품 시사출 보고서 작성 누락" 이었으므로,
    보고서가 없는 금형을 찾아내는 것(iatf.mold.is_tryout_missing)이 이 모델의
    존재 이유의 절반이다.
    """

    _name = "iatf.mold.tryout"
    _description = "시사출(T/O) 보고서 (SQ 4_5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "tryout_date desc, id desc"

    name = fields.Char(
        string="보고서 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    mold_id = fields.Many2one(
        "iatf.mold", string="금형", required=True, index=True, tracking=True,
        # cascade 가 아니라 restrict 다. 시사출 보고서는 금형에 딸린 명세 줄이 아니라
        # 그 자체가 심사 증빙 문서다. 금형을 지우면서 증빙이 조용히 같이 사라지면
        # 나중에 "그때 T/O 를 했는가" 를 아무도 답할 수 없다. 금형은 지우지 말고
        # 폐기(disposed) 상태로 두는 것이 정상 경로다.
        ondelete="restrict",
    )
    tryout_date = fields.Date(
        string="시사출일", required=True, default=fields.Date.context_today, tracking=True,
    )
    tryout_no = fields.Integer(
        string="차수", default=0, copy=False,
        help="같은 금형의 몇 번째 시사출인지. 비워두면 자동으로 다음 번호가 붙는다.",
    )
    reason = fields.Selection(
        [("new", "신규제작"), ("transfer", "이관"), ("repair", "수정 후")],
        string="사유", required=True, default="new", tracking=True,
    )

    # ── 결과 ──
    shot_count = fields.Integer(string="시사출 타수(샷)")
    ok_qty = fields.Integer(string="양품 수량")
    ng_qty = fields.Integer(string="불량 수량")
    defect_rate = fields.Float(
        string="불량률(%)", compute="_compute_defect_rate", store=True, digits=(16, 2),
    )
    conclusion = fields.Selection(
        [("pass", "합격"), ("rework", "재수정"), ("hold", "보류")],
        string="판정", tracking=True,
    )

    # ── 연계 ──
    inspection_id = fields.Many2one(
        "iatf.process.inspection", string="초품 검사",
        help="수정·이관 후 초품 검사 성적서 (SQ 4_3 연계).",
    )
    responsible_id = fields.Many2one(
        "res.users", string="담당자", default=lambda self: self.env.user, tracking=True,
    )
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="특이사항")

    state = fields.Selection(
        [("draft", "작성 중"), ("done", "완료"), ("cancelled", "취소")],
        string="상태", default="draft", required=True, tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        # 차수 중복은 조용히 넘어가면 안 된다. 보고서 번호가 증빙이라 같은 차수가
        # 둘이면 어느 쪽이 그 차수인지 설명할 수 없다. 동시 생성이 겹치면 저장이
        # 실패하고 사용자가 다시 저장하면서 다음 번호를 받는다.
        ("uniq_mold_tryout_no", "unique(mold_id, tryout_no)",
         "같은 금형에 동일 차수의 시사출 보고서가 이미 있습니다."),
    ]

    @api.depends("ok_qty", "ng_qty")
    def _compute_defect_rate(self):
        for rec in self:
            total = (rec.ok_qty or 0) + (rec.ng_qty or 0)
            rec.defect_rate = (rec.ng_qty / total * 100.0) if total else 0.0

    @api.constrains("shot_count", "ok_qty", "ng_qty")
    def _check_quantities(self):
        for rec in self:
            if rec.ok_qty < 0 or rec.ng_qty < 0 or rec.shot_count < 0:
                raise ValidationError(_("타수·수량은 음수가 될 수 없습니다."))
            # 타수를 적었으면 양품+불량이 그 안에 들어와야 한다. 넘으면 어느 한쪽이
            # 오타이므로, 틀린 불량률이 증빙으로 굳기 전에 저장을 막는다.
            if rec.shot_count and (rec.ok_qty + rec.ng_qty) > rec.shot_count:
                raise ValidationError(_(
                    "양품(%(ok)s) + 불량(%(ng)s) 이 시사출 타수(%(shot)s) 를 초과합니다.",
                    ok=rec.ok_qty, ng=rec.ng_qty, shot=rec.shot_count,
                ))

    def _next_tryout_no(self, mold_id):
        last = self.search(
            [("mold_id", "=", mold_id)], order="tryout_no desc", limit=1,
        )
        return (last.tryout_no or 0) + 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.mold.tryout") or _("New")
            if not vals.get("tryout_no") and vals.get("mold_id"):
                vals["tryout_no"] = self._next_tryout_no(vals["mold_id"])
        return super().create(vals_list)

    def action_done(self):
        for rec in self:
            if not rec.conclusion:
                raise UserError(_("판정(합격/재수정/보류)을 정한 뒤 완료하십시오."))
            rec.state = "done"

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})
