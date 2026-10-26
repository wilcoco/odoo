import base64
import csv
import hashlib
import io
import json
import re
import zipfile
from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError


def csv_value(value):
    text = str(value or '')
    return "'" + text if text.lstrip().startswith(('=', '+', '-', '@')) else text


class SqAuditPackage(models.Model):
    _inherit = 'iatf.audit'

    def _sq_package_outputs(self, archive, remaining_bytes):
        """Optional report-module hook; source ACLs and the package cap still apply."""
        return None

    def action_sq_package(self):
        self.ensure_one()
        self.check_access('read')
        if self.audit_type != 'sq' or not (self.env.su or self.env.user.has_group('cams_sq.group_sq_user')):
            raise AccessError(_('SQ 평가서 조회 권한이 필요합니다.'))
        if not self.sq_date_from or not self.sq_date_to:
            raise UserError(_('증빙 시작일과 종료일을 입력하십시오.'))
        output = io.BytesIO()
        manifest, seen_records, seen_files = [], set(), set()
        total_bytes = 0
        company = self.company_id
        def add_attachment(archive, attachment, origin):
            nonlocal total_bytes
            if attachment.id in seen_files:
                return
            try:
                attachment.check_access('read')
                if attachment.company_id and attachment.company_id != company:
                    raise AccessError(_('다른 회사의 첨부입니다.'))
                if attachment.type != 'binary':
                    manifest.append(dict(origin, attachment_id=attachment.id, status='외부 링크: 파일 미수집'))
                    return
                if attachment.file_size > 25 * 1024**2 or total_bytes + attachment.file_size > 100 * 1024**2:
                    raise UserError(_('첨부 크기 한도(파일 25MB / 합계 100MB)를 초과합니다. 평가 범위를 나누십시오.'))
                raw = attachment.raw or b''
                if len(raw) > 25 * 1024**2 or total_bytes + len(raw) > 100 * 1024**2:
                    raise UserError(_('첨부 합계가 100MB를 초과합니다. 평가 범위를 나누십시오.'))
                name = re.sub(r'[^\w .()-]', '_', attachment.name or 'attachment').strip('. ')[:120] or 'attachment'
                path = 'attachments/%d-%s' % (attachment.id, name)
                archive.writestr(path, raw)
                seen_files.add(attachment.id)
                total_bytes += len(raw)
                manifest.append(dict(origin, attachment_id=attachment.id, path=path, bytes=len(raw),
                                     sha256=hashlib.sha256(raw).hexdigest(), status='포함'))
            except AccessError:
                manifest.append(dict(origin, status='첨부 조회 권한 또는 회사 범위 제한'))

        def add_record(archive, record, origin):
            key = (record._name, record.id)
            record.check_access('read')
            if 'company_id' in record._fields and record.company_id and record.company_id != company:
                raise AccessError(_('다른 회사의 원천입니다.'))
            link = '/web#model=%s&id=%d&view_type=form' % key
            row = dict(origin, model=record._name, record_id=record.id, name=record.display_name, link=link, status='원천 조회')
            manifest.append(row)
            if key in seen_records:
                return
            if len(seen_records) >= 5000:
                raise UserError(_('원천 기록이 5,000건을 넘습니다. 증빙 기간을 줄이십시오.'))
            seen_records.add(key)
            attachments = self.env['ir.attachment'].search([('res_model', '=', record._name), ('res_id', '=', record.id)])
            if 'attachment_ids' in record._fields and record._fields['attachment_ids'].comodel_name == 'ir.attachment':
                attachments |= record.attachment_ids
            for attachment in attachments:
                add_attachment(archive, attachment, row)
            if 'document_ids' in record._fields and record._fields['document_ids'].comodel_name == 'iatf.document':
                for document in record.document_ids:
                    try:
                        add_record(archive, document, origin)
                    except AccessError:
                        manifest.append(dict(origin, status='연결 문서 조회 권한 제한'))

        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            text = io.StringIO()
            writer = csv.writer(text)
            writer.writerow(['코드', '항목', '배점', '확정 판정', '득점', '근거', '제안', '제안 근거'])
            for line in self.sq_line_ids:
                line.check_access('read')
                writer.writerow([csv_value(v) for v in [line.item_id.code, line.item_id.name, line.points,
                    line.rating, line.score, line.reason, line.proposed_rating, line.proposed_reason]])
                for rule in line.item_id.rule_ids.with_context(sq_date_from=str(self.sq_date_from), sq_date_to=str(self.sq_date_to)):
                    origin = {'item': line.item_id.code, 'rule': rule.id}
                    try:
                        target, domain = rule._target()
                        records = target.search(domain, limit=5001)
                        if len(records) > 5000:
                            raise UserError(_('원천 기록이 5,000건을 넘습니다. 증빙 기간을 줄이십시오.'))
                        manifest.append(dict(origin, model=target._name, domain=domain, count=len(records), status='조회 조건'))
                        for record in records:
                            add_record(archive, record, origin)
                    except AccessError:
                        manifest.append(dict(origin, status='원천 조회 권한 제한'))
                    except UserError as error:
                        if '5,000' in str(error) or 'MB' in str(error):
                            raise
                        manifest.append(dict(origin, status=str(error)))
                for requirement in line.item_id.requirement_ids:
                    for document in requirement.document_ids:
                        try:
                            add_record(archive, document, {'item': line.item_id.code, 'requirement': requirement.id})
                        except AccessError:
                            manifest.append({'item': line.item_id.code, 'requirement': requirement.id, 'status': '준비 문서 조회 권한 제한'})
            # Explicitly linked audit documents/attachments are part of the package too.
            for document in self.document_ids:
                try:
                    add_record(archive, document, {'assessment': self.id})
                except AccessError:
                    manifest.append({'assessment': self.id, 'status': '평가서 연결 문서 조회 권한 제한'})
            for attachment in self.attachment_ids:
                add_attachment(archive, attachment, {'assessment': self.id})
            self._sq_package_outputs(archive, 100 * 1024**2 - total_bytes)
            archive.writestr('assessment.csv', text.getvalue().encode('utf-8-sig'))
            # Preserve the approved historical judgment separately from current
            # source exports. Never represent today's attachments as old evidence.
            request = self.approval_request_id
            if request:
                request.check_access('read')
                archive.writestr('approval-snapshot.json', json.dumps({
                    'request_id': request.id, 'state': request.state,
                    'snapshot': request.snapshot,
                }, ensure_ascii=False, indent=2, default=str))
            archive.writestr('evidence.json', json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
            archive.writestr('summary.json', json.dumps({'assessment': self.name, 'company': company.name,
                'standard': self.sq_standard_id.name, 'state': self.state, 'raw_score': self.sq_raw_score,
                'applicable_points': self.sq_applicable, 'score': self.sq_score, 'unknown': self.sq_unknown,
                'ratios': self.sq_ratios, 'areas': self.sq_area_scores, 'exported_at': str(fields.Datetime.now()),
                'exported_by': self.env.user.display_name, 'attachments': len(seen_files), 'attachment_bytes': total_bytes,
                'note': '내보내기 시점에 현재 사용자가 조회 가능한 원천만 포함합니다. 미조회·미설치 사유는 evidence.json에 남깁니다. 자동 합격 판정이 아닙니다.'}, ensure_ascii=False, indent=2))
        package = self.env['sq.package'].create({'data': base64.b64encode(output.getvalue()), 'name': 'SQ-%d.zip' % self.id})
        return {'type': 'ir.actions.act_url', 'url': '/web/content/sq.package/%d/data?download=true&filename_field=name' % package.id, 'target': 'self'}
