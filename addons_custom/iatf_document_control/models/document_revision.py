from odoo import fields, models


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
    attachment_ids = fields.Many2many(
        "ir.attachment", string="이전 버전 파일",
        help="Attach the superseded version of the document for record-keeping.",
    )
