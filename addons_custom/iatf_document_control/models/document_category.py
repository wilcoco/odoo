from odoo import api, fields, models


class IatfDocumentCategory(models.Model):
    _name = "iatf.document.category"
    _description = "Document Category (IATF 16949)"
    _order = "sequence, name"

    name = fields.Char(string="카테고리명", required=True, translate=True)
    code = fields.Char(string="코드", required=True)
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one("iatf.document.category", string="상위 카테고리", index=True)
    child_ids = fields.One2many("iatf.document.category", "parent_id", string="하위 카테고리")
    description = fields.Text(string="설명")
    retention_years = fields.Integer(
        string="기본 보존기간 (년)",
        default=7,
        help="Default retention period for documents in this category. "
             "IATF 16949 requires retention per customer/regulatory requirements.",
    )
    document_count = fields.Integer(compute="_compute_document_count", string="문서 수")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Category code must be unique."),
    ]

    @api.depends("child_ids")
    def _compute_document_count(self):
        for cat in self:
            cat.document_count = self.env["iatf.document"].search_count(
                [("category_id", "=", cat.id)]
            )
