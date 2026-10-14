"""Protect controlled file bytes as well as their document relation."""
from odoo import models, _
from odoo.exceptions import UserError


class Attachment(models.Model):
    _inherit = 'ir.attachment'

    def _check_controlled_file_change(self):
        if not self.ids:
            return
        # Use elevated lookup only to find references, never to grant access to
        # the file. A hidden approved document must still protect its evidence.
        documents = self.env['iatf.document'].sudo().with_context(active_test=False).search(
            [('attachment_ids', 'in', self.ids)])
        documents._lock_document()
        revisions = self.env['iatf.document.revision'].sudo().search([
            ('attachment_ids', 'in', self.ids)], limit=1)
        if revisions or any(doc.state != 'draft' for doc in documents):
            raise UserError(_('승인 문서·이전 개정의 첨부 증거는 교체하거나 삭제할 수 없습니다.'))

    def write(self, vals):
        if {'datas', 'raw', 'db_datas', 'store_fname', 'name', 'mimetype', 'type',
                'url', 'res_model', 'res_id', 'public'} & vals.keys():
            self._check_controlled_file_change()
        return super().write(vals)

    def unlink(self):
        self._check_controlled_file_change()
        return super().unlink()
