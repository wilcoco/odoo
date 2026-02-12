from odoo import fields, models


class IatfDocumentRevision(models.Model):
    _name = "iatf.document.revision"
    _description = "Document Revision History"
    _order = "revision_date desc, id desc"

    document_id = fields.Many2one(
        "iatf.document", string="Document", required=True, ondelete="cascade", index=True,
    )
    revision_number = fields.Char(string="Revision", required=True)
    revision_date = fields.Date(string="Date", required=True, default=fields.Date.today)
    reason = fields.Text(string="Reason for Change", required=True)
    change_description = fields.Html(string="Change Description")
    revised_by = fields.Many2one("res.users", string="Revised By", default=lambda self: self.env.user)
    approved_by = fields.Many2one("res.users", string="Approved By")
    attachment_ids = fields.Many2many(
        "ir.attachment", string="Previous Version Files",
        help="Attach the superseded version of the document for record-keeping.",
    )
