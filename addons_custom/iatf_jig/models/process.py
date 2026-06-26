from odoo import fields, models


class IatfProcess(models.Model):
    _name = "iatf.process"
    _description = "공정(Process) 마스터"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "code"

    code = fields.Char(string="공정 코드", required=True, copy=False, tracking=True)
    name = fields.Char(string="공정명", required=True, tracking=True)
    category = fields.Selection(
        [("quality", "품질"), ("production", "생산"), ("purchase", "구매"),
         ("development", "개발"), ("other", "기타")],
        string="분류", tracking=True,
    )
    document_no = fields.Char(string="문서 번호")
    revision = fields.Char(string="개정")
    effective_date = fields.Date(string="시행일")
    owner_dept_id = fields.Many2one("hr.department", string="주관 부서")
    # ── 제조 연동 (G3): 공정 기준정보 ↔ 실제 작업장/라우팅 ──
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장",
                                     help="이 공정이 수행되는 제조 작업장 (G3 연동)")
    operation_id = fields.Many2one("mrp.routing.workcenter", string="라우팅 작업",
                                    help="BoM 라우팅의 작업 단계 (선택)")
    description = fields.Text(string="설명")
    active = fields.Boolean(string="활성", default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
