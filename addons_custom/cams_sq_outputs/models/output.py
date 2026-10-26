import base64
import calendar
import hashlib
import io
import json
from datetime import datetime, time, timedelta
import pytz
import xlsxwriter
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression
from .specs import SPECS, BASE_COLUMNS

MAX_RECORDS = 500
NATIVE_REPORTS = {
    'iatf.control.plan': 'iatf_dashboard.action_report_control_plan',
    'iatf.fmea': 'iatf_dashboard.action_report_fmea',
    'iatf.nonconformity': 'iatf_dashboard.action_report_8d',
}


def source_company(record):
    path = SPECS.get(record._name, {}).get('company', 'company_id')
    current = record
    for part in path.split('.'):
        if part not in current._fields or current._fields[part].type != 'many2one':
            return False
        current.check_access('read')
        current = current[part]
        if not current:
            return False
    return current if current._name == 'res.company' else False


def cell(record, name):
    """Only approved adapter fields are passed here; retain zero as a real value."""
    record.check_access('read')
    if name not in record.fields_get([name]):
        return '미연결'
    field = record._fields[name]
    value = record[name]
    if field.type in ('many2one', 'many2many', 'one2many'):
        value.check_access('read')
        return ', '.join(value.mapped('display_name'))
    if field.type == 'selection':
        return dict(field._description_selection(record.env)).get(value, '')
    if field.type == 'boolean':
        return '예' if value else '아니요'
    if value is False or value is None:
        return ''
    if field.type == 'datetime' and value:
        return str(fields.Datetime.context_timestamp(record, value))
    return str(value)


def safe_fields(record, names):
    names = list(dict.fromkeys(names))
    visible = record.fields_get(names)
    return [name for name in names if name in visible and record._fields[name].type not in ('binary', 'html', 'json')]


def signatures(record):
    author = next((cell(record, key) for key in ('checker_id', 'inspector_id', 'responsible_id', 'owner_id', 'create_uid')
                   if key in record._fields and record[key]), '')
    review, approval = '', ''
    if 'approval_request_id' in record._fields and record.approval_request_id:
        request = record.approval_request_id
        request.check_access('read')
        lines = request.line_ids.sorted('sequence')
        lines.check_access('read')
        if request.state == 'approved' and lines and all(line.state == 'approved' for line in lines):
            def signed(line):
                return cell(line, 'user_id') + ' / ' + cell(line, 'action_date')
            approval = signed(lines[-1])
            review = '; '.join(signed(line) for line in lines[:-1])
    elif record._name == 'iatf.document' and record.state == 'approved':
        review = cell(record, 'reviewer_id') + ' / ' + cell(record, 'review_date')
        approval = cell(record, 'approver_id') + ' / ' + cell(record, 'approval_date')
    return [author, review or '검토 서명 없음', approval or '승인 서명 없음']


class Requirement(models.Model):
    _inherit = 'sq.doc.requirement'

    def _output_records(self, start, end):
        self.ensure_one()
        self.check_access('read')
        if self.company_id not in self.env.companies:
            raise AccessError(_('허용된 회사의 서류만 출력하십시오.'))
        key = self.output_model
        if key not in SPECS or key not in self.env:
            raise UserError(_('출력 원천이 미연결 또는 미설치 상태입니다.'))
        spec = SPECS[key]
        target = self.env[key].with_context(allowed_company_ids=[self.company_id.id])
        target.check_access('read')
        scope = []
        for binding in self.output_binding_ids.filtered('active'):
            binding.check_access('read')
            binding._check_source()
            source = binding.source_ref
            if source._name == key:
                scope.append([('id', '=', source.id)])
            elif source._name in spec['scopes']:
                path = spec['scopes'][source._name]
                if path not in target._fields or target._fields[path].comodel_name != source._name:
                    raise UserError(_('현재 설치 버전의 원천 범위 연결을 확인하십시오.'))
                scope.append([(path, '=', source.id)])
            else:
                raise UserError(_('이 출력 원천에 사용할 수 없는 범위 연결입니다.'))
        if not scope:
            raise UserError(_('실제 원천 기록 또는 점검 대상을 먼저 연결하십시오.'))
        domain = expression.AND([expression.OR(scope), [(spec['company'], '=', self.company_id.id)]])
        if spec['date']:
            date_field = target._fields.get(spec['date'])
            if not date_field or date_field.type not in ('date', 'datetime'):
                raise UserError(_('원천 기간 필드의 연결 검증이 필요합니다.'))
            if date_field.type == 'datetime':
                tz = pytz.timezone(self.env.user.tz or 'UTC')
                lower = tz.localize(datetime.combine(start, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                upper = tz.localize(datetime.combine(end + timedelta(days=1), time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
                domain += [(spec['date'], '>=', lower), (spec['date'], '<', upper)]
            else:
                domain += [(spec['date'], '>=', start), (spec['date'], '<=', end)]
        result = target.search(domain, order='id', limit=MAX_RECORDS + 1)
        if len(result) > MAX_RECORDS:
            raise UserError(_('출력 원천이 500건을 넘습니다. 기간이나 대상을 나누십시오.'))
        for record in result:
            if source_company(record) != self.company_id:
                raise AccessError(_('원천의 회사 범위가 일치하지 않습니다.'))
        return result

    def _output_payload(self, start, end):
        self.ensure_one()
        result = {'key': self.source_key, 'title': self.name, 'company': self.company_id.name,
            'period': '%s ~ %s' % (start, end), 'kind': self.output_type or '', 'rows': [],
            'warning': '', 'grids': [], 'documents': [], 'current_master': False}
        if self.output_type == 'external':
            result['warning'] = '외부·수동: 현물/현장 확인 필요'
            return result
        if self.output_type == 'upload':
            self.check_access('read')
            if not self.document_ids:
                result['warning'] = '업로드 문서 미연결'
            for document in self.document_ids:
                document.check_access('read')
                if document.company_id != self.company_id:
                    raise AccessError(_('다른 회사의 문서입니다.'))
                result['documents'].append({'number': document.doc_number, 'name': document.name,
                    'state': document.state, 'id': document.id})
            if any(doc['state'] != 'approved' for doc in result['documents']):
                result['warning'] = '승인되지 않은 문서 포함'
            return result
        records = self._output_records(start, end)
        spec = SPECS[self.output_model]
        result['current_master'] = not spec['date']
        if not records:
            result['warning'] = '지정 기간·범위의 원천 자료 없음'
        pending = records.filtered(lambda r:
            ('evidence_state' in r._fields and r.evidence_state != 'done') or
            ('state' in r._fields and r.state in ('draft', 'cancel', 'cancelled', 'rejected')) or
            ('approval_state' in r._fields and r.approval_state and r.approval_state != 'approved'))
        if pending:
            result['warning'] = '미완료·미승인·취소 원천 %d건 포함. 심사 증빙 확정 전 원천 상태를 확인하십시오.' % len(pending)
        for record in records:
            names = safe_fields(record, spec['columns'] + BASE_COLUMNS)
            descriptions = record.fields_get(names)
            pairs = [(descriptions[name]['string'], cell(record, name)) for name in names]
            details = []
            if spec['lines']:
                relation, columns = spec['lines']
                if relation in record._fields:
                    lines = record[relation]
                    lines.check_access('read')
                    if len(lines) > 2000:
                        raise UserError(_('상세 행이 2,000건을 넘습니다. 원천을 나누십시오.'))
                    visible = safe_fields(lines, columns.split())
                    labels = lines.fields_get(visible)
                    # Narrow blocks retain all columns without shrinking an A4 page.
                    for index in range(0, len(visible[1:]), 5):
                        block = visible[:1] + visible[1:][index:index + 5]
                        details.append({'headers': [labels[key]['string'] for key in block],
                            'rows': [[cell(line, key) for key in block] for line in lines]})
            snapshot = record.completion_snapshot if 'completion_snapshot' in record._fields else False
            file_ids, layouts, revisions = [], [], []
            attachments = self.env['ir.attachment']
            if 'attachment_ids' in record._fields:
                attachments |= record.attachment_ids
            documents = self.env['iatf.document']
            if record._name == 'iatf.document':
                documents |= record
            if 'document_ids' in record._fields:
                documents |= record.document_ids
            for key in names:
                if record._fields[key].type == 'many2one' and record._fields[key].comodel_name == 'iatf.document':
                    documents |= record[key]
            documents.check_access('read')
            for document in documents:
                if document.company_id != self.company_id:
                    raise AccessError(_('다른 회사의 원천 문서입니다.'))
                attachments |= document.attachment_ids
                if ('quality_evidence_kind' in document._fields and document.quality_evidence_kind == 'work_area_layout'
                        and document.state == 'approved'):
                    for attachment in document.attachment_ids:
                        attachment.check_access('read')
                        if attachment.mimetype in ('image/png', 'image/jpeg') and attachment.file_size <= 2 * 1024**2 and len(layouts) < 4:
                            layouts.append({'name': document.display_name, 'uri': 'data:%s;base64,%s' %
                                (attachment.mimetype, base64.b64encode(attachment.raw or b'').decode())})
            attachments.check_access('read')
            for attachment in attachments:
                if attachment.company_id and attachment.company_id != self.company_id:
                    raise AccessError(_('다른 회사의 원천 첨부입니다.'))
                file_ids.append(attachment.id)
            if 'snapshot_ids' in record._fields:
                snapshots = record.snapshot_ids
                snapshots.check_access('read')
                for old in snapshots:
                    revisions.append(' / '.join(cell(old, key) for key in ('revision', 'done_at', 'done_by_id') if key in old._fields))
            result['rows'].append({'model': record._name, 'id': record.id, 'name': record.display_name,
                'pairs': pairs, 'details': details, 'signatures': signatures(record),
                'trace': ' / '.join('%s: %s' % (record.fields_get([key])[key]['string'], cell(record, key) or '미기록')
                    for key in ('product_id', 'lot_id', 'production_id', 'workcenter_id', 'trace_exception') if key in record.fields_get([key])),
                'snapshot_sha256': hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest() if snapshot else '',
                'file_ids': file_ids, 'layouts': layouts, 'revisions': revisions,
                'state': cell(record, 'evidence_state') if 'evidence_state' in record._fields else cell(record, 'state') if 'state' in record._fields else '완료 상태 구분 없음'})
        if spec['grid'] and records:
            result['grids'] = self._output_grids(records, spec, start, end)
        return result

    def _output_grids(self, records, spec, start, end):
        groups = {}
        for record in records:
            date = record[spec['date']]
            if isinstance(date, datetime):
                date = fields.Datetime.context_timestamp(record, date).date()
            target = next((cell(record, field) for field in ('sheet_id', 'equipment_id', 'mold_id') if field in record._fields), record.display_name)
            revision = cell(record, 'sheet_revision') if 'sheet_revision' in record._fields else cell(record, 'evidence_revision') if 'evidence_revision' in record._fields else '개정 미기록'
            key = (target, revision, date.year, date.month)
            group = groups.setdefault(key, {})
            if spec['lines']:
                lines = record[spec['lines'][0]]
                for line in lines:
                    title = cell(line, 'item_name')
                    standard = cell(line, 'standard')
                    labels = {'value':'실측', 'text_value':'입력', 'result':'판정', 'five_point_score':'점수', 'remark':'비고'}
                    value = ' / '.join('%s %s' % (label, cell(line, field))
                        for field, label in labels.items() if field in line.fields_get([field]) and cell(line, field))
                    if 'five_point_definition' in line._fields and line.five_point_definition:
                        standard += '\n점수 기준: ' + line.five_point_definition
                    group.setdefault((title, standard), {}).setdefault(date.day, []).append(record.display_name + ': ' + value)
            else:
                for field in safe_fields(record, spec['columns']):
                    title = record.fields_get([field])[field]['string']
                    group.setdefault((title, ''), {}).setdefault(date.day, []).append(cell(record, field))
        pages = []
        for (target, revision, year, month), items in groups.items():
            first = max(start, start.replace(year=year, month=month, day=1))
            last = min(end, end.replace(year=year, month=month, day=calendar.monthrange(year, month)[1]))
            days = list(range(first.day, last.day + 1))
            for index in range(0, len(days), 7):
                block = days[index:index + 7]
                pages.append({'target': target, 'revision': revision, 'month': '%04d-%02d' % (year, month), 'days': block,
                    'rows': [{'name': title, 'standard': standard,
                        'values': ['\n'.join(values.get(day, [])) or '미기록' for day in block]} for (title, standard), values in items.items()]})
        return pages


class OutputWizard(models.TransientModel):
    _name = 'sq.output.wizard'
    _description = 'SQ 서류 기간별 출력'
    requirement_ids = fields.Many2many('sq.doc.requirement', string='서류', required=True)
    date_from = fields.Date('시작일', required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date('종료일', required=True, default=fields.Date.context_today)
    include_details = fields.Boolean('점검표 상세 원천도 출력', default=False,
        help='기본 점검표는 항목×일자와 실제 서명·개정 이력을 출력합니다. 선택하면 원천 필드와 상세 행도 추가합니다.')
    data = fields.Binary(attachment=False, readonly=True)
    filename = fields.Char(readonly=True)

    def _payloads(self):
        self.ensure_one()
        self.check_access('read')
        if not (self.env.su or self.env.user.has_group('cams_sq.group_sq_user')):
            raise AccessError(_('SQ 조회 권한이 필요합니다.'))
        if not self.requirement_ids or not self.date_from or not self.date_to or self.date_from > self.date_to:
            raise UserError(_('서류와 올바른 출력 기간을 선택하십시오.'))
        if (self.date_to - self.date_from).days > 366 or len(self.requirement_ids) > 467:
            raise UserError(_('한 번에 1년/467서류 이하로 출력하십시오.'))
        self.requirement_ids.check_access('read')
        if len(self.requirement_ids.company_id) != 1 or self.requirement_ids.company_id not in self.env.companies:
            raise AccessError(_('한 회사의 서류만 출력할 수 있습니다.'))
        output = []
        for requirement in self.requirement_ids.sorted(lambda r: (r.output_sequence, r.source_key)):
            try:
                payload = requirement._output_payload(self.date_from, self.date_to)
                payload['include_details'] = self.include_details
                output.append(payload)
            except (AccessError, UserError) as error:
                output.append({'key': requirement.source_key, 'title': requirement.name, 'company': requirement.company_id.name,
                    'period': '%s ~ %s' % (self.date_from, self.date_to), 'kind': requirement.output_type or '',
                    'rows': [], 'grids': [], 'documents': [], 'current_master': False,
                    'include_details': self.include_details,
                    'warning': '원천 조회 권한/회사 범위 제한' if isinstance(error, AccessError) else str(error)})
        return output

    def action_pdf(self):
        self._payloads()
        return self.env.ref('cams_sq_outputs.report_output').report_action(self)

    def _native_report(self):
        self._payloads()
        self.requirement_ids.ensure_one()
        requirement = self.requirement_ids
        xmlid = NATIVE_REPORTS.get(requirement.output_model)
        action = self.env.ref(xmlid, raise_if_not_found=False) if xmlid else False
        if not action or action.model != requirement.output_model:
            raise UserError(_('선택한 원천에 설치된 기존 전용 리포트가 없습니다. 공용 PDF를 사용하십시오.'))
        records = requirement._output_records(self.date_from, self.date_to)
        if not records:
            raise UserError(_('기간·범위에 해당하는 원천이 없습니다.'))
        return action, records

    def action_native_pdf(self):
        action, records = self._native_report()
        return action.with_company(self.requirement_ids.company_id).report_action(records)

    def _xlsx(self):
        payloads = self._payloads()
        stream = io.BytesIO()
        book = xlsxwriter.Workbook(stream, {'in_memory': True, 'strings_to_formulas': False, 'strings_to_urls': False})
        head = book.add_format({'bold': True, 'bg_color': '#E7EEF7', 'border': 1})
        wrap = book.add_format({'text_wrap': True, 'valign': 'top'})
        for number, payload in enumerate(payloads, 1):
            sheet = book.add_worksheet('%03d' % number)
            sheet.freeze_panes(5, 0); sheet.set_column(0, 0, 28); sheet.set_column(1, 6, 24)
            sheet.write_row(0, 0, [payload['key'], payload['title']], head)
            sheet.write_row(1, 0, [payload['company'], payload['period']], wrap)
            sheet.write(2, 0, payload['warning'] or '출력 시점 원천 / 자동 합격 판정 아님', wrap)
            row = 4
            for source in payload['rows']:
                sheet.write_row(row, 0, [source['model'], source['id'], source['name'], source['state']], head); row += 1
                sheet.write_row(row, 0, ['작성', '검토', '승인'], head); row += 1
                sheet.write_row(row, 0, source['signatures'], wrap); row += 1
                for pair in source['pairs']:
                    sheet.write_row(row, 0, pair, wrap); row += 1
                for block in source['details']:
                    sheet.write_row(row, 0, block['headers'], head); row += 1
                    for values in block['rows']:
                        sheet.write_row(row, 0, values, wrap); row += 1
                row += 1
            for document in payload['documents']:
                sheet.write_row(row, 0, [document['number'], document['name'], document['state']], wrap); row += 1
        book.close()
        return stream.getvalue()

    def action_xlsx(self):
        self.ensure_one()
        self.write({'data': base64.b64encode(self._xlsx()), 'filename': 'SQ-documents.xlsx'})
        return {'type': 'ir.actions.act_url', 'url': '/web/content/sq.output.wizard/%d/data?download=true&filename_field=filename' % self.id, 'target': 'self'}


class Report(models.AbstractModel):
    _name = 'report.cams_sq_outputs.document'
    _description = 'SQ 원천 서류 출력'

    @api.model
    def _get_report_values(self, docids, data=None):
        wizard = self.env['sq.output.wizard'].browse(docids).exists()
        wizard.ensure_one()
        return {'doc_ids': wizard.ids, 'doc_model': wizard._name, 'docs': wizard,
                'payloads': wizard._payloads(), 'company': wizard.requirement_ids.company_id}
