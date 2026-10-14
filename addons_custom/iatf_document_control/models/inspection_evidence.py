"""Bounded, content-sensitive references for existing inspection approvals."""
import hashlib
import json

from odoo import _
from odoo.exceptions import UserError
from odoo.tools import SQL


def _lock(records):
    if records:
        records.flush_recordset()
        records.env.cr.execute(SQL('UPDATE %s SET write_date=write_date WHERE id IN %s',
                                  SQL.identifier(records._table), tuple(sorted(records.ids))))
        records.invalidate_recordset()


def _linked(record):
    documents = record.document_ids if 'document_ids' in record._fields else record.env['iatf.document']
    attachments = record.attachment_ids if 'attachment_ids' in record._fields else record.env['ir.attachment']
    return documents, attachments


def validate_inspection_links(records):
    """The user adding references must be allowed to read their contents."""
    for record in records:
        documents, attachments = _linked(record)
        if documents:
            documents.check_access('read')
        all_files = attachments | documents.attachment_ids
        if all_files:
            all_files.check_access('read')
        for source in documents:
            if source.company_id and source.company_id != record.company_id:
                raise UserError(_('다른 회사의 문서를 검사 근거로 연결할 수 없습니다.'))
        for attachment in attachments | documents.attachment_ids:
            if attachment.company_id and attachment.company_id != record.company_id:
                raise UserError(_('다른 회사의 첨부파일을 검사 근거로 연결할 수 없습니다.'))


def inspection_documents_snapshot(record):
    """Compare only linked records; stock staff need no document editing rights.

    The caller validates its inspection/stock scope. Elevated reads are confined
    to those references, and return fingerprints, never document body or bytes.
    Empty legacy scopes keep their original serialization.
    """
    record.ensure_one()
    record.check_access('read')
    documents, attachments = _linked(record.sudo())
    if not documents and not attachments:
        return False
    _lock(documents)
    all_files = attachments | documents.attachment_ids
    _lock(all_files)
    for source in documents:
        if source.company_id and source.company_id != record.company_id:
            raise UserError(_('검사와 연결 문서의 회사가 다릅니다. 자료 적용 범위를 재검토하십시오.'))
    if any(item.company_id and item.company_id != record.company_id for item in all_files):
        raise UserError(_('검사와 첨부파일의 회사가 다릅니다. 자료 적용 범위를 재검토하십시오.'))

    def files(rows):
        return [{'id': item.id, 'checksum': item.checksum, 'size': item.file_size,
                 'name': item.name, 'mimetype': item.mimetype, 'type': item.type,
                 'url': item.url, 'company_id': item.company_id.id,
                 'external_content_verified': False if item.type == 'url' else None}
                for item in rows.sorted('id')]

    result = {'version': 1, 'attachments': files(attachments), 'documents': []}
    for doc in documents.sorted('id'):
        content = {key: doc[key] for key in ('doc_number', 'name', 'description', 'current_revision',
                    'state', 'active', 'doc_type', 'external_origin')}
        content.update({key: str(doc[key]) for key in ('revision_date', 'review_date', 'approval_date')})
        content.update({key: doc[key].id for key in ('company_id', 'category_id', 'owner_id',
                                                    'reviewer_id', 'approver_id')})
        content['attachments'] = files(doc.attachment_ids)
        result['documents'].append({'id': doc.id, 'company_id': doc.company_id.id,
            'number': doc.doc_number, 'revision': doc.current_revision, 'state': doc.state, 'active': doc.active,
            'content_sha256': hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()})
    return result
