from odoo import api, fields, models, _
from odoo.exceptions import UserError
from .document import _WORKFLOW_CONTEXT, _WORKFLOW_TOKEN


class IatfDocumentRevision(models.Model):
    _name = "iatf.document.revision"
    _description = "Document Revision History"
    _order = "revision_date desc, id desc"

    document_id = fields.Many2one(
        "iatf.document", string="문서", required=True, ondelete="cascade", index=True,
    )
    revision_number = fields.Char(string="개정", required=True)
    revision_date = fields.Date(string="일자", required=True, default=fields.Date.today)
    reason = fields.Text(string="변경 사유", required=True)
    change_description = fields.Html(string="변경 내용")
    revised_by = fields.Many2one("res.users", string="개정자", default=lambda self: self.env.user)
    approved_by = fields.Many2one("res.users", string="승인자")
    snapshot_name = fields.Char(string='당시 문서 제목', readonly=True)
    snapshot_approval_date = fields.Date(string='당시 승인일', readonly=True)
    attachment_ids = fields.Many2many(
        "ir.attachment", string="이전 버전 파일",
        help="Attach the superseded version of the document for record-keeping.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get(_WORKFLOW_CONTEXT) is not _WORKFLOW_TOKEN:
            raise UserError(_('개정 이력은 승인 문서의 새 개정 기능에서 생성하십시오.'))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get(_WORKFLOW_CONTEXT) is not _WORKFLOW_TOKEN:
            raise UserError(_('이전 개정의 승인 증거는 수정할 수 없습니다.'))
        return super().write(vals)

    def unlink(self):
        raise UserError(_('이전 개정의 승인 증거는 삭제할 수 없습니다.'))
