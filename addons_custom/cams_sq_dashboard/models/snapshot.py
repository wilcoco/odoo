from odoo import _
from odoo.exceptions import UserError


def _checks_snapshot(task, records, lock=True):
    if not records:
        return []
    records.check_access('read')
    if lock and records:
        records.flush_recordset()
        records.env.cr.execute('SELECT id FROM iatf_check_record WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(records.ids)])
        records.invalidate_recordset()
    bound = task.sq_item_id._bound_source_ids('iatf.check.sheet') if records else []
    result = []
    for record in records.sorted('id'):
        if (record.company_id != task.sq_company_id or record.sheet_id.company_id != task.sq_company_id
                or record.sheet_id.id not in bound or record.state != 'done'
                or not task.scheduled_date <= record.check_date <= task.sq_performed_date):
            raise UserError(_('예정일~실제 수행일 범위의 같은 회사·연결 시트의 완료 점검표만 사용하십시오.'))
        record.line_ids.check_access('read')
        if task.task_def_id.sq_shift and record.shift != task.task_def_id.sq_shift:
            raise UserError(_('관리계획과 같은 근무조의 완료 점검표를 연결하십시오.'))
        record.snapshot_ids.check_access('read')
        snapshot = record.snapshot_ids.sorted('revision')[-1:]
        if not snapshot or record._derive_overall()[0] == 'pending':
            raise UserError(_('측정과 완료 스냅샷이 있는 점검표가 필요합니다.'))
        result.append({'id': record.id, 'sheet': record.sheet_id.id, 'date': str(record.check_date),
                       'result': record._derive_overall()[0], 'snapshot': snapshot.id,
                       'revision': snapshot.revision, 'content': snapshot.content})
    return result


def _documents_snapshot(documents, company, lock=True):
    if not documents:
        return []
    documents.check_access('read')
    if lock and documents:
        documents.flush_recordset()
        documents.env.cr.execute('SELECT id FROM iatf_document WHERE id IN %s ORDER BY id FOR UPDATE', [tuple(documents.ids)])
        documents.invalidate_recordset()
    result=[]
    for document in documents.sorted('id'):
        if document.company_id != company or document.state != 'approved':
            raise UserError(_('같은 회사의 승인된 문서만 수행 증빙으로 연결하십시오.'))
        attachments = document.attachment_ids
        attachments.check_access('read')
        result.append({'id':document.id,'revision':document.current_revision,
                       'write_date':str(document.write_date),'state':document.state,
                       'attachments': [{'id':a.id,'checksum':a.checksum,'write_date':str(a.write_date)} for a in attachments.sorted('id')]})
    return result
