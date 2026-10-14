"""Two distinct company approvers and an explicit, evidence-bound LOT release."""
import base64
import binascii
import hashlib
import json

from odoo import api, fields, models, Command, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import SQL

_TOKEN = object()
_KEY = '_lot_hold_release_service'
_LOT_PROTECTED = {'hold_revision', 'hold_source_data'}
# [아스트라 20260912 03:58] 「**기술선택은 1번 기존 원천 검증 확장입니다.** …
# 명시 원천 종류별 검증을 사용하고 **임의모델 허용은 금지**합니다.」
# 종류를 여기 적고, 종류마다 검증을 **따로** 쓴다. 모델 이름을 인자로 받아
# 되살리는 일반 통로를 만들지 않는다.
_HOLD_SOURCE_MODELS = ('iatf.process.inspection', 'br.intake.defect', 'br.intake')
# 실물이 없어지거나 고객/공급사로 넘어간 처분은 **LOT 전체 가용 해제**가 아니다.
_NON_RELEASING_DISPOSITIONS = ('scrap', 'return', 'concession')
_RELEASE_PROTECTED = {'release_snapshot', 'release_state', 'released_by', 'released_at'}


def _service(record):
    return record.with_context(**{_KEY: _TOKEN})


def _internal(record):
    return record.env.context.get(_KEY) is _TOKEN


def _reject_defaults(record, values, protected):
    if not _internal(record) and any(k in values or 'default_' + k in record.env.context for k in protected):
        raise UserError(_('보류·해제 증거는 서버의 검증 절차에서만 기록합니다.'))


def _lock(records):
    if records:
        records.flush_recordset()
        records.env.cr.execute(SQL('UPDATE %s SET write_date=write_date WHERE id IN %s',
                                   SQL.identifier(records._table), tuple(sorted(records.ids))))
        records.invalidate_recordset()


class LotHoldPolicy(models.Model):
    _name = 'iatf.lot.hold.policy'
    _description = 'LOT 품질 보류 해제 책임자'
    _rec_name = 'company_id'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    quality_user_id = fields.Many2one('res.users', string='품질책임자', required=True)
    production_user_id = fields.Many2one('res.users', string='생산책임자', required=True)
    policy_revision = fields.Integer(readonly=True, copy=False, default=0)
    _sql_constraints = [('company_unique', 'unique(company_id)', '회사별 해제 책임자 설정은 하나입니다.')]

    @api.constrains('company_id', 'quality_user_id', 'production_user_id')
    def _check_policy(self):
        for rec in self:
            if rec.quality_user_id == rec.production_user_id:
                raise UserError(_('품질과 생산 책임자는 서로 다른 계정이어야 합니다.'))
            for user, role in [(rec.quality_user_id, 'quality'), (rec.production_user_id, 'production')]:
                if (not user.active or user.share or rec.company_id not in user.company_ids
                        or not user.has_group('iatf_incoming_inspection.group_lot_hold_' + role)):
                    raise UserError(_('해당 회사의 활성 내부 사용자와 품질/생산 보류 해제 역할을 지정하세요.'))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('보류 해제 책임자 설정은 시스템 관리자만 변경합니다.'))
        for vals in vals_list:
            _reject_defaults(self, vals, {'policy_revision'})
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su and not self.env.user.has_group('base.group_system'):
            raise AccessError(_('보류 해제 책임자 설정은 시스템 관리자만 변경합니다.'))
        _reject_defaults(self, vals, {'policy_revision'})
        with self.env.cr.savepoint():
            _lock(self)
            for rec in self:
                super(LotHoldPolicy, rec).write(dict(vals, policy_revision=rec.policy_revision + 1))
        return True


class LotHoldGuard(models.Model):
    _inherit = 'stock.lot'

    hold_revision = fields.Integer(readonly=True, copy=False, default=0,
        help='0인 기존 보류는 소급 승인하지 않고 새 근거 검토가 필요합니다.')
    hold_source_data = fields.Json(readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _reject_defaults(self, vals, _LOT_PROTECTED)
        return super().create(vals_list)

    def write(self, vals):
        if _internal(self):
            return super().write(vals)
        _reject_defaults(self, vals, _LOT_PROTECTED)
        if not ({'quality_hold', 'hold_reason', 'name', 'product_id', 'company_id'} & vals.keys()):
            return super().write(vals)
        self.check_access('write')
        with self.env.cr.savepoint():
            _lock(self)
            for lot in self:
                if lot.quality_hold:
                    if 'quality_hold' in vals and not vals['quality_hold']:
                        raise UserError(_('품질·생산 두 단계 승인 후 보류 해제 요청에서 명시적으로 실행하세요.'))
                    if any(key in vals and vals[key] != (lot[key].id if key != 'name' else lot[key])
                           for key in ('name', 'product_id', 'company_id')):
                        raise UserError(_('보류 중인 LOT의 이름·제품·회사는 변경할 수 없습니다.'))
                    if 'hold_reason' in vals and (lot.hold_reason or '') not in (vals['hold_reason'] or ''):
                        raise UserError(_('기존 보류 사유를 삭제하거나 대체할 수 없습니다. 새 사유를 추가하세요.'))
                changed = (('quality_hold' in vals and bool(vals['quality_hold']) != lot.quality_hold)
                           or ('hold_reason' in vals and vals['hold_reason'] != lot.hold_reason))
                values = dict(vals)
                if changed:
                    values['hold_revision'] = lot.hold_revision + 1
                super(LotHoldGuard, _service(lot)).write(values)
        return True

    def _hold_source_pair(self, entry):
        """등록된 **종류만** 되살린다. 없는 모델·다른 모델은 거부한다."""
        self.ensure_one()
        model = entry.get('model')
        if model not in _HOLD_SOURCE_MODELS:
            raise UserError(_('지원하지 않는 보류 원천입니다.'))
        if model not in self.env:
            # BR 없는 독립 설치에서도 서야 한다. 강제 의존성을 만들지 않고
            # **이 설치에 실제로 있는지**를 본다.
            raise UserError(_('이 설치에 없는 보류 원천 모델입니다: %s') % model)
        source = self.env[model].sudo().browse(entry['id']).exists()
        nc = self.env['iatf.nonconformity'].sudo().browse(entry['nc_id']).exists()
        if not source or not nc:
            raise UserError(_('보류 원천 또는 부적합 근거가 없습니다.'))
        return source, nc

    def _assert_hold_source(self, source, nc):
        """원천 종류별 **회사·품목·LOT·실물·수량·NC 동일성**을 확인한다.

        [아스트라 20260912 03:58] 「BR 원천의 회사/품목/LOT/생산 또는 실제반품이동/
        연결NC의 **동일성·수량**을 확인하고 …」
        """
        self.ensure_one()
        if nc.company_id != self.company_id or nc.product_id != self.product_id:
            raise UserError(_('보류 부적합의 회사/제품 연결이 변경되었습니다.'))
        # LOT 연결은 **원천 종류마다 다르다.** 공정검사·BR 불량의 부적합은 그 LOT
        # 하나를 가리키지만, **BR 반품의 부적합은 여러 LOT 에 걸친 한 건**이라
        # `lot_id` 가 비어 있다. 그 경우의 결속은 **실제 반품 입고 이동**이 한다.
        if source._name != 'br.intake' and nc.lot_id != self:
            raise UserError(_('보류 부적합의 LOT 연결이 변경되었습니다.'))
        if source._name == 'iatf.process.inspection':
            if (source.lot_id != self or source.company_id != self.company_id
                    or source.product_id != self.product_id
                    or source.nonconformity_id != nc):
                raise UserError(_('보류 검사·부적합의 회사/제품/LOT 연결이 변경되었습니다.'))
            return True
        if source._name == 'br.intake.defect':
            br = source.br_id
            if (source.lot_id != self or source.company_id != self.company_id
                    or source.nonconformity_res_id != nc.id
                    or br.company_id != self.company_id
                    or br.product_id != self.product_id):
                raise UserError(_('BR 불량 원천의 회사/품목/LOT/부적합 연결이 변경되었습니다.'))
            if source.production_id not in br._br_supply_productions():
                raise UserError(_('BR 불량의 생산이 그 BR 의 조립·재작업이 아닙니다.'))
            # **만들지 않은 것을 보류 근거로 쓸 수 없다.**
            produced = br._br_produced_by_lot(source.production_id).get(self, 0.0)
            if produced <= 0:
                raise UserError(_('그 생산이 이 LOT 을 만든 실적이 없습니다.'))
            if source.quantity > produced + 1e-6:
                raise UserError(_('BR 불량 수량이 그 LOT 실생산량보다 많습니다.'))
            if abs((nc.quantity_rejected or 0.0) - source.quantity) > 1e-6:
                raise UserError(_('BR 불량 수량과 부적합 불합격 수량이 다릅니다.'))
            return True
        if source._name == 'br.intake':
            if (source.company_id != self.company_id
                    or source.product_id != self.product_id
                    or source.return_nonconformity_res_id != nc.id
                    or (nc.lot_id and nc.lot_id != self)):
                raise UserError(_('BR 반품 원천의 회사/품목/부적합 연결이 변경되었습니다.'))
            # [아스트라 20260912 04:27] 「BR반품 분기에서 **공통 NC.quantity_rejected 를
            # 해당 LOT 한 개의 returned 와 비교**합니다. BR반품 NC가 여러 LOT 한
            # 건이면 예를 들어 A1+B1 반품/NC2 에서 각 LOT 1 과 비교하여 **정상 반품을
            # 막을 수 있습니다.** 전체반품 수량 대사와 LOT별 실물결속을 구분해
            # 고치십시오.」
            #
            # 맞습니다. 하나는 **수량 대사**(NC 한 건 ↔ 반품 전체)이고 다른 하나는
            # **실물 결속**(이 LOT 이 실제로 돌아왔는가)입니다. 섞어서 비교했습니다.
            returned_by_lot = source._br_returned_by_lot()
            if returned_by_lot.get(self, 0.0) <= 0:
                raise UserError(_('실제 반품 입고 이동에 이 LOT 이 없습니다.'))
            if (nc.quantity_rejected or 0.0) > sum(returned_by_lot.values()) + 1e-6:
                raise UserError(_('반품 부적합 수량이 실제 반품 입고 총량보다 많습니다.'))
            return True
        raise UserError(_('지원하지 않는 보류 원천입니다.'))

    def _assert_hold_disposition_releasable(self, source, nc):
        """처분이 **정해졌고**, LOT 전체 가용 해제로 바꿀 수 있는 처분인지 본다.

        [아스트라 20260912 03:58] 「**미정처분**/변경근거/다른LOT를 검증실패로 남기고
        **폐기·공급사반품 또는 고객특채가 LOT전체 가용해제로 전환되지 않도록** 기존
        수량/실물 처분 경로를 구분하십시오. 재사용/재작업/선별은 재검사 근거와 정상
        해제 승인과정으로 확인합니다. **NC 메모만 넣어 실물 폐기 완료라고 표시하면
        안 됩니다.**」

        [아스트라 20260912 04:27] 「**PQC 경로 유지**란 원래 승인/증빙 검증을
        보존하라는 뜻이며 미정처분 또는 폐기/반품의 전체가용해제를 허용하라는
        뜻은 아닙니다. … **PQC 도 미정처분/폐기/반품/특채→전체가용 해제 거부**를
        같은 절차에서 검증하도록 보완하십시오. 정상 재검사/재사용·선별은
        유지합니다. **신규 사업정책 없이 발견된 검증 누락 수정**입니다.」

        제가 「PQC 는 건드리지 않는다」로 읽었는데 그게 아니었습니다. 원천 종류와
        무관하게 같은 처분 게이트를 받습니다.
        """
        self.ensure_one()
        if nc.disposition == 'concession':
            raise UserError(_('고객 특채 원천은 LOT 전체 일반 해제 범위 밖입니다. 고객/수량 한정 승인을 전체 해제로 바꿀 수 없습니다.'))
        if not nc.disposition:
            raise UserError(_('부적합 처분이 아직 정해지지 않았습니다. 재사용·재작업·선별 판정을 먼저 확정하세요.'))
        if nc.disposition in _NON_RELEASING_DISPOSITIONS:
            raise UserError(_(
                '처분 「%s」는 실물이 남지 않거나 넘어가는 경로입니다. LOT 전체 '
                '가용 해제로 전환하지 않고 기존 수량·실물 처분 절차로 처리하세요.'
            ) % dict(nc._fields['disposition'].selection).get(nc.disposition, nc.disposition))
        return True

    def _set_quality_hold_from_source(self, source, reason):
        """검증된 원천만 보류 출처를 등록한다 (PQC 불합격 · BR 불량 · BR 반품)."""
        self.ensure_one()
        source.ensure_one()
        if source._name not in _HOLD_SOURCE_MODELS:
            raise UserError(_('지원하지 않는 자동 보류 원천입니다.'))
        if source._name == 'iatf.process.inspection':
            source._check_auto_evidence_source(require_decision=True)
            if (source.result != 'fail' or source.state != 'decided'
                    or not source.nonconformity_id):
                raise UserError(_('LOT와 불합격 검사·회사·부적합 원천이 다릅니다.'))
            nc = source.nonconformity_id
        elif source._name == 'br.intake.defect':
            nc = self.env['iatf.nonconformity'].sudo().browse(
                source.nonconformity_res_id).exists()
        else:
            nc = self.env['iatf.nonconformity'].sudo().browse(
                source.return_nonconformity_res_id).exists()
        if not nc:
            raise UserError(_('보류 원천에 연결된 부적합 근거가 없습니다.'))
        self._assert_hold_source(source, nc)
        _lock(self)
        entry = {'model': source._name, 'id': source.id, 'nc_id': nc.id}
        entries = list(self.hold_source_data or [])
        if self.quality_hold and entry in entries and reason in (self.hold_reason or ''):
            return True
        if entry not in entries:
            entries.append(entry)
        _service(self).write({'quality_hold': True,
            'hold_reason': '\n'.join(filter(None, [self.hold_reason, reason])) if reason not in (self.hold_reason or '') else self.hold_reason,
            'hold_revision': self.hold_revision + 1, 'hold_source_data': entries})
        return True

    def _hold_sources_fingerprint(self):
        self.ensure_one()
        result = []
        for entry in self.hold_source_data or []:
            # IDs are server-owned, already bound to this readable company LOT.
            # Read only provenance metadata; no added public rights to inspect/edit NC.
            source, nc = self._hold_source_pair(entry)
            self._assert_hold_source(source, nc)
            self._assert_hold_disposition_releasable(source, nc)
            # Include values, not only second-resolution write timestamps.
            evidence = {
                'nc': nc.read(['title', 'state', 'disposition', 'quantity_affected', 'quantity_rejected',
                    'containment_action', 'containment_verified', 'root_cause', 'verification_result',
                    'closure_notes', 'document_ids', 'attachment_ids', 'corrective_action_ids'])[0],
                'related_evidence': self._hold_related_evidence(nc)}
            evidence.update(self._hold_source_evidence(source))
            digest = hashlib.sha256(json.dumps(evidence, sort_keys=True, default=str).encode()).hexdigest()
            result.append(dict(entry, source_version=str(source.write_date), nc_version=str(nc.write_date), evidence_sha256=digest))
        return result

    def _hold_source_evidence(self, source):
        """원천 **기록 내용**을 지문에 넣는다. write_date 만으로는 내용 변경을 못 본다."""
        self.ensure_one()
        if source._name == 'iatf.process.inspection':
            return {'pqc': source.auto_evidence_snapshot, 'pqc_state': source.state}
        if source._name == 'br.intake.defect':
            return {'br_defect': source.read([
                'br_id', 'production_id', 'lot_id', 'quantity', 'reason',
                'rework_production_id', 'rework_kind', 'company_id',
                'nonconformity_ref', 'nonconformity_res_id',
                'adjustment_request_ids', 'recorded_by'])[0]}
        if source._name == 'br.intake':
            return {'br_return': source.read([
                'br_no', 'revision', 'product_id', 'company_id', 'state',
                'returned_qty', 'return_approved_qty', 'return_approved_by',
                'return_approved_at', 'return_approval_note',
                'return_nonconformity_ref', 'return_nonconformity_res_id'])[0]}
        raise UserError(_('지원하지 않는 보류 원천입니다.'))

    def _hold_related_evidence(self, nc, lock_records=False):
        """Fingerprint the actual files, including NC-linked document/CAPA files."""
        documents = nc.document_ids.sorted('id')
        actions = nc.corrective_action_ids.sorted('id')
        if any(doc.company_id and doc.company_id != self.company_id for doc in documents):
            raise UserError(_('부적합 근거 문서의 회사가 LOT 회사와 다릅니다.'))
        if lock_records:
            _lock(documents)
            _lock(actions)
        attachments = (nc.attachment_ids | documents.attachment_ids | actions.attachment_ids).sorted('id')
        if lock_records:
            _lock(attachments)
            return
        files = []
        for attachment in attachments:
            if attachment.company_id and attachment.company_id != self.company_id:
                raise UserError(_('부적합 증거 파일의 회사가 LOT 회사와 다릅니다.'))
            if attachment.type != 'binary':
                raise UserError(_('외부 URL 증거는 내용을 고정할 수 없습니다. 검토할 원본 파일을 보존한 뒤 새 요청으로 상신하세요.'))
            data = attachment.read(['name', 'mimetype', 'type', 'res_model', 'res_id', 'res_field',
                                    'company_id', 'file_size', 'checksum', 'write_date'])[0]
            data['content_sha256'] = hashlib.sha256(attachment.raw or b'').hexdigest()
            files.append(data)
        return {'files': files,
            'documents': documents.read(['name', 'company_id', 'state', 'current_revision', 'revision_date',
                'approver_id', 'approval_date', 'description', 'attachment_ids']),
            'corrective_actions': actions.read(['nonconformity_id', 'company_id', 'state', 'description',
                'verification_method', 'verification_result', 'effective', 'verified_by',
                'verification_date', 'attachment_ids'])}

    def _lock_hold_sources(self):
        """Use source -> NC -> LOT order shared with automatic quality holds."""
        self.ensure_one()
        for entry in sorted(self.hold_source_data or [],
                            key=lambda item: (item.get('model') or '', item['id'])):
            # [아스트라 20260912 03:58] 「`_set`와 `_fingerprint` 뿐 아니라 `_lock`도
            # 같은 원천 종류를 처리해야 합니다.」
            if entry.get('model') not in _HOLD_SOURCE_MODELS:
                raise UserError(_('지원하지 않는 보류 원천입니다.'))
            if entry['model'] not in self.env:
                raise UserError(_('이 설치에 없는 보류 원천 모델입니다: %s') % entry['model'])
            _lock(self.env[entry['model']].sudo().browse(entry['id']))
            nc = self.env['iatf.nonconformity'].sudo().browse(entry['nc_id'])
            _lock(nc)
            self._hold_related_evidence(nc, lock_records=True)


class LotHoldRelease(models.Model):
    _name = 'iatf.lot.hold.release'
    _description = 'LOT 품질 보류 해제 요청'
    _inherit = ['iatf.approval.mixin', 'mail.thread', 'mail.activity.mixin']
    _rec_name = 'lot_id'
    _order = 'id desc'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    lot_id = fields.Many2one('stock.lot', required=True, ondelete='restrict', string='전체 해제 LOT')
    reason = fields.Text(string='해제 요청 사유', required=True)
    evidence_note = fields.Text(string='재검사·전체 보류 사유 검토 근거')
    evidence_file = fields.Binary(string='검토 근거 파일', attachment=False, copy=False)
    evidence_filename = fields.Char(string='근거 파일명')
    all_causes_reviewed = fields.Boolean(string='전체 보류 사유 및 LOT 전체의 일반 해제 근거 검토')
    release_snapshot = fields.Json(readonly=True, copy=False)
    release_state = fields.Selection([('draft', '검토'), ('executed', '해제 실행 완료')], default='draft', readonly=True, copy=False)
    released_by = fields.Many2one('res.users', readonly=True, copy=False, string='해제 실행자')
    released_at = fields.Datetime(readonly=True, copy=False, string='해제 실행 시각')

    def _policy(self):
        self.ensure_one()
        policy = self.env['iatf.lot.hold.policy'].search([('company_id', '=', self.company_id.id)])
        if len(policy) != 1:
            raise UserError(_('해당 회사의 품질·생산 책임자를 먼저 설정하세요.'))
        policy._check_policy()
        return policy

    def _scope(self):
        self.ensure_one()
        self.check_access('read')
        self.lot_id.check_access('read')
        if self.company_id not in self.env.companies or self.lot_id.company_id != self.company_id:
            raise UserError(_('허용된 회사의 LOT와 요청 회사가 일치해야 합니다.'))

    def _evidence_hash(self):
        try:
            raw = base64.b64decode(self.evidence_file or b'', validate=True)
        except (ValueError, binascii.Error):
            raise UserError(_('유효한 검토 근거 파일을 첨부하세요.'))
        if not raw or len(raw) > 10 * 1024 * 1024:
            raise UserError(_('검토 근거 파일은 비어 있지 않은 10MB 이하 파일이어야 합니다.'))
        return hashlib.sha256(raw).hexdigest()

    def _payload(self):
        self.ensure_one()
        self._scope()
        if not self.lot_id.quality_hold:
            raise UserError(_('현재 보류 중인 LOT만 해제를 검토합니다.'))
        if not self.all_causes_reviewed or not (self.evidence_note or '').strip() or not self.evidence_filename:
            raise UserError(_('전체 보류 사유의 일반 해제 검토 및 재검사 근거 파일·설명을 기록하세요. 고객/부분수량 특채는 이 절차로 해제하지 않습니다.'))
        policy = self._policy()
        return {'company_id': self.company_id.id, 'lot_id': self.lot_id.id,
            'product_id': self.lot_id.product_id.id, 'lot_name': self.lot_id.name,
            'hold_revision': self.lot_id.hold_revision, 'hold_reason': self.lot_id.hold_reason,
            'sources': self.lot_id._hold_sources_fingerprint(),
            'reason': self.reason, 'evidence_note': self.evidence_note,
            'evidence_filename': self.evidence_filename, 'evidence_sha256': self._evidence_hash(),
            'all_causes_reviewed': self.all_causes_reviewed,
            'policy_id': policy.id, 'policy_version': str(policy.write_date),
            'policy_revision': policy.policy_revision,
            'quality_user_id': policy.quality_user_id.id, 'production_user_id': policy.production_user_id.id,
            'approval_request_id': self.approval_request_id.id}

    def _validate_contract(self):
        self.ensure_one()
        if self.release_state != 'draft' or not self.release_snapshot or self.release_snapshot != self._payload():
            raise UserError(_('승인한 LOT·보류·책임자·근거와 현재 내용이 다릅니다. 새 요청으로 검토하세요.'))
        lines = self.approval_request_id._get_ordered_lines()
        expected = [(10, self.release_snapshot['quality_user_id']), (20, self.release_snapshot['production_user_id'])]
        if [(line.sequence, line.user_id.id) for line in lines] != expected:
            raise UserError(_('품질책임자 다음 생산책임자의 두 단계 결재선을 유지해야 합니다.'))
        return True

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            _reject_defaults(self, vals, _RELEASE_PROTECTED)
        records = super().create(vals_list)
        for rec in records:
            rec._scope()
        return records

    def _approval_should_reset(self, vals):
        return False if _internal(self) else super()._approval_should_reset(vals)

    def write(self, vals):
        if 'approval_request_id' in vals and any(rec.release_snapshot for rec in self):
            raise UserError(_('상신한 해제 요청의 결재 연결은 교체하지 않고 새 해제 요청을 만드세요.'))
        if not _internal(self):
            _reject_defaults(self, vals, _RELEASE_PROTECTED)
            substantive = set(vals) - self._approval_reset_ignored_fields()
            if substantive and any(rec.release_state == 'executed' for rec in self):
                raise UserError(_('해제 완료 증거는 수정할 수 없습니다. 새 보류는 새 요청으로 처리하세요.'))
            if substantive and any(rec.release_snapshot for rec in self):
                raise UserError(_('상신한 해제 대상과 근거는 수정하지 않고 새 요청으로 검토하세요.'))
        result = super().write(dict(vals))
        for rec in self:
            rec._scope()
        return result

    def copy(self, default=None):
        if self.release_snapshot:
            raise UserError(_('상신한 해제 증거는 복사하지 않고 새 요청에서 현재 근거를 검토하세요.'))
        return super().copy(default)

    def action_reset_approval(self):
        if any(rec.release_snapshot for rec in self):
            raise UserError(_('기존 해제 승인을 보존하고 새 해제 요청으로 검토하세요.'))
        return super().action_reset_approval()

    def action_submit_approval(self):
        with self.env.cr.savepoint():
            for rec in self:
                rec.check_access('write')
                rec._approval_lock_target()
                rec.lot_id._lock_hold_sources()
                _lock(rec.lot_id)
                if rec.release_snapshot or rec.release_state != 'draft' or rec.approval_state != 'draft':
                    raise UserError(_('이미 상신한 해제 요청은 새 요청으로 다시 검토하세요.'))
                policy = rec._policy()
                rec.approval_request_id.write({'line_ids': [Command.clear(),
                    Command.create({'sequence': 10, 'user_id': policy.quality_user_id.id}),
                    Command.create({'sequence': 20, 'user_id': policy.production_user_id.id})]})
                _service(rec).write({'release_snapshot': rec._payload()})
                rec.approval_request_id.action_submit()
        return True

    def action_release_hold(self):
        self.ensure_one()
        with self.env.cr.savepoint():
            self.check_access('write')
            self._approval_lock_target()
            _lock(self.approval_request_id)
            self.lot_id._lock_hold_sources()
            _lock(self.lot_id)
            self._scope()
            policy = self._policy()
            _lock(policy)
            if self.env.user != policy.production_user_id:
                raise AccessError(_('두 단계 승인 후 지정 생산책임자가 명시적으로 실행합니다.'))
            if self.release_state == 'executed':
                if self.lot_id.quality_hold or self.lot_id.hold_revision != self.release_snapshot['hold_revision'] + 1:
                    raise UserError(_('새 보류에는 이전 해제 요청을 재사용할 수 없습니다.'))
                return True
            self._validate_contract()
            self._approval_check_approved(_('LOT 전체 품질 보류 해제'))
            _service(self.lot_id.sudo()).write({'quality_hold': False, 'hold_revision': self.lot_id.hold_revision + 1})
            _service(self).write({'release_state': 'executed', 'released_by': self.env.user.id,
                                 'released_at': fields.Datetime.now()})
            self.message_post(body=_('품질·생산 두 단계 승인 후 LOT 전체 보류 해제를 명시 실행했습니다. 검사대기 이동·양품 판정·출고 승인은 별도입니다.'))
        return True


class HoldReleaseApproval(models.Model):
    _inherit = 'iatf.approval.request'

    def _hold_release_target(self):
        return self._get_target_record() if self.res_model == 'iatf.lot.hold.release' else False

    def action_submit(self):
        for request in self:
            rec = request._hold_release_target()
            if rec:
                rec._scope()  # Check the caller's original company access first.
                request._lock_workflow()
                rec.lot_id._lock_hold_sources()
                _lock(rec.lot_id)
                rec._validate_contract()
                request = request.with_context(allowed_company_ids=rec.company_id.ids)
            super(HoldReleaseApproval, request).action_submit()
        return True

    def _approve_user(self, user):
        rec = self._hold_release_target()
        if rec:
            rec._scope()
            self._lock_workflow()
            rec.lot_id._lock_hold_sources()
            _lock(rec.lot_id)
            rec._validate_contract()
            return super(HoldReleaseApproval, self.with_context(allowed_company_ids=rec.company_id.ids))._approve_user(user)
        return super()._approve_user(user)
