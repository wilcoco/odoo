"""Explicit component agreements and durable, non-financial quantity notices."""
import json
import uuid

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_round
from odoo.addons.supplier_portal_purchase.models.scm_utils import check_actor, check_quantity

_NOTICE_TRANSITION = object()


def _ensure_scope_lock_table(env):
    env.cr.execute("""
        CREATE TABLE IF NOT EXISTS scm_no_po_scope_lock (
            id serial PRIMARY KEY,
            company_id integer NOT NULL,
            commercial_partner_id integer NOT NULL,
            product_id integer NOT NULL,
            touched_at timestamp,
            CONSTRAINT scm_no_po_scope_lock_uniq UNIQUE (company_id, commercial_partner_id, product_id)
        )""")


def lock_supply_scopes(env, company, partner, products):
    """Serialize agreement activation and purchase approval for one supply scope.

    [2026-10-05] 결함 수정(테스트 047 반례 5/5): advisory lock 만으로는 REPEATABLE READ 에서
    뒤 트랜잭션이 옛 스냅숏을 유지해 상대가 방금 커밋한 협약/PO 를 못 본다. 공유 잠금 행에
    실제 쓰기를 넣어, 잠금을 늦게 얻은 트랜잭션이 직렬화 실패(40001)로 재시도되게 한다 —
    gh_vendor_settlement(_approval_lock_target) 와 같은 해법. INSERT..ON CONFLICT DO UPDATE 는
    최초 범위는 생성(advisory lock 이 동시 생성 직렬화), 기존 범위는 UPDATE 로 충돌을 일으킨다.
    """
    _ensure_scope_lock_table(env)
    commercial = partner.commercial_partner_id
    for product in products.sorted('id'):
        key = 'scm-no-po:%s:%s:%s' % (company.id, commercial.id, product.id)
        env.cr.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', (key,))
        env.cr.execute(
            "INSERT INTO scm_no_po_scope_lock (company_id, commercial_partner_id, product_id, touched_at) "
            "VALUES (%s, %s, %s, now()) "
            "ON CONFLICT (company_id, commercial_partner_id, product_id) "
            "DO UPDATE SET touched_at = now()",
            (company.id, commercial.id, product.id))


def check_base_quantity(quantity, product):
    check_quantity(quantity, positive=True)
    rounding = product.uom_id.rounding
    if abs(quantity - float_round(quantity, precision_rounding=rounding)) > rounding * 1e-6:
        raise ValidationError(_('제품 기본 단위의 수량 정밀도에 맞게 입력하세요.'))


class SupplyAgreement(models.Model):
    _name = 'scm.no.po.agreement'
    _description = '회사·협력사·부품 무발주 공급 협약'
    _rec_name = 'name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=False, help='검토한 협약만 담당자가 명시적으로 활성화합니다.')
    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company, index=True)
    partner_id = fields.Many2one('res.partner', required=True, ondelete='restrict')
    product_id = fields.Many2one('product.product', required=True, ondelete='restrict')
    picking_type_id = fields.Many2one('stock.picking.type', required=True, ondelete='restrict')
    reference = fields.Char(required=True, string='협약 근거')
    component_confirmed = fields.Boolean(default=False, string='수지 제외 부품 협약 확인')
    date_start = fields.Date(required=True)
    date_end = fields.Date()
    notice_ids = fields.One2many('scm.no.po.notice', 'agreement_id')

    def init(self):
        self.env.cr.execute('CREATE UNIQUE INDEX IF NOT EXISTS scm_no_po_agreement_active_scope '
            'ON scm_no_po_agreement (company_id, partner_id, product_id) WHERE active')
        _ensure_scope_lock_table(self.env)

    def _check_component(self):
        for rec in self:
            tmpl = rec.product_id.product_tmpl_id
            if getattr(tmpl, 'settle_by_ton', False) or getattr(tmpl, 'resin_settlement_policy', False) == 'purchase_order':
                raise ValidationError(_('수지/톤정산 원재료는 무발주 부품 협약에 등록할 수 없습니다.'))
            if rec.active and not rec.component_confirmed:
                raise ValidationError(_('수지가 아닌 부품 협약임을 확인한 후 활성화하세요.'))

    @api.constrains('company_id', 'partner_id', 'product_id', 'picking_type_id', 'date_start', 'date_end', 'active', 'component_confirmed')
    def _check_scope(self):
        for rec in self:
            check_actor(rec, rec.partner_id)
            if rec.partner_id != rec.partner_id.commercial_partner_id:
                raise ValidationError(_('협약에는 공급사의 상위 상업 거래처를 지정하세요.'))
            rec.partner_id._scm_check_supply_product(rec.product_id, rec.company_id)
            if rec.product_id.company_id and rec.product_id.company_id != rec.company_id:
                raise ValidationError(_('다른 회사의 품목입니다.'))
            if not rec.product_id.is_storable:
                raise ValidationError(_('재고 관리되는 부품만 무발주 협약에 등록할 수 있습니다.'))
            pt = rec.picking_type_id
            if (pt.company_id != rec.company_id or pt.code != 'incoming'
                    or pt.default_location_src_id.usage != 'supplier'
                    or pt.default_location_dest_id.usage != 'internal'
                    or any(loc.company_id and loc.company_id != rec.company_id
                           for loc in pt.default_location_src_id | pt.default_location_dest_id)):
                raise ValidationError(_('같은 회사의 공급처→내부 입고 유형을 지정하세요.'))
            if rec.date_end and rec.date_end < rec.date_start:
                raise ValidationError(_('협약 종료일이 시작일보다 빠릅니다.'))
            rec._check_component()
            if rec.active:
                lock_supply_scopes(self.env, rec.company_id, rec.partner_id, rec.product_id)
                duplicate = self.search_count([('id', '!=', rec.id), ('active', '=', True),
                    ('company_id', '=', rec.company_id.id), ('partner_id', '=', rec.partner_id.id),
                    ('product_id', '=', rec.product_id.id)], limit=1)
                if duplicate:
                    raise ValidationError(_('동일 회사·공급사·품목의 활성 협약이 이미 있습니다.'))
                open_po = self.env['purchase.order.line'].search_count([
                    ('order_id.company_id', '=', rec.company_id.id),
                    ('order_id.partner_id', 'child_of', rec.partner_id.id),
                    ('order_id.state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
                    ('product_id', '=', rec.product_id.id),
                ], limit=1)
                if open_po:
                    raise ValidationError(_(
                        '미결 구매요청/발주가 남아 있습니다. 취소·입고잔량을 정리한 후 무발주 협약을 활성화하세요.'))
                rec._check_valuation()

    def _check_valuation(self):
        for rec in self:
            if rec.product_id.with_company(rec.company_id).categ_id.property_valuation != 'manual_periodic':
                raise UserError(_('무발주 부품 입고는 수동 정기 재고평가 설정에서만 가능합니다. 분류 설정을 확인하세요.'))

    def write(self, vals):
        if set(vals) & {'company_id', 'partner_id', 'product_id', 'picking_type_id', 'reference', 'date_start', 'date_end', 'component_confirmed'}:
            if self.notice_ids:
                raise UserError(_('통보 근거가 있는 협약은 변경할 수 없습니다. 새 협약을 작성하세요.'))
        return super().write(vals)


class SupplyNotice(models.Model):
    _name = 'scm.no.po.notice'
    _description = '무발주 부품 수량 요구통보'
    _order = 'id desc'
    _inherit = ['mail.thread']

    name = fields.Char(required=True, string='통보 관리번호', copy=False)
    agreement_id = fields.Many2one('scm.no.po.agreement', required=True, ondelete='restrict')
    company_id = fields.Many2one(related='agreement_id.company_id', store=True, index=True)
    partner_id = fields.Many2one(related='agreement_id.partner_id', store=True)
    product_id = fields.Many2one(related='agreement_id.product_id', store=True)
    uom_id = fields.Many2one('uom.uom', required=True, ondelete='restrict', string='제품 기본 단위')
    quantity = fields.Float(required=True, string='요구 수량')
    need_date = fields.Date(required=True, string='필요일')
    source_reference = fields.Text(required=True, string='원청 계획·수요 근거', help='계획 버전, 일자, 원문 위치와 산출근거. 소요전망 행 ID만 적지 마세요.')
    source_kind = fields.Selection([('manual', '담당자 확인 계획 근거'), ('forecast', '현재 소요전망 원본 복사')],
        default='manual', required=True)
    revision_of_id = fields.Many2one('scm.no.po.notice', ondelete='restrict', copy=False, string='대체하는 취소 통보')
    revision_reason = fields.Text(string='개정 사유')
    snapshot = fields.Text(readonly=True, copy=False)
    state = fields.Selection([('draft', '초안'), ('issued', '발행'), ('closed', '잔량 종료'), ('cancelled', '취소')], default='draft', required=True, readonly=True, tracking=True, copy=False)
    issued_at = fields.Datetime(readonly=True, copy=False)
    issued_by = fields.Many2one('res.users', readonly=True, copy=False)
    allocation_revision = fields.Integer(readonly=True, copy=False)
    asn_line_ids = fields.One2many('supplier.asn.line', 'no_po_notice_id', readonly=True)
    allocated_quantity = fields.Float(compute='_compute_quantities', string='ASN 예약 수량')
    received_quantity = fields.Float(compute='_compute_quantities', string='실입고 누계')
    available_quantity = fields.Float(compute='_compute_quantities', string='추가 ASN 가능 수량')

    _sql_constraints = [
        ('notice_reference_company', 'unique(company_id, name)', '회사 내 통보 관리번호는 중복될 수 없습니다.'),
        ('notice_revision_once', 'unique(revision_of_id)', '취소 통보의 대체 통보가 이미 있습니다.'),
    ]

    @api.depends('quantity', 'state', 'asn_line_ids.qty', 'asn_line_ids.asn_id.state',
        'asn_line_ids.move_ids.state', 'asn_line_ids.move_ids.quantity',
        'asn_line_ids.move_ids.product_uom', 'asn_line_ids.move_ids.location_id',
        'asn_line_ids.move_ids.location_dest_id')
    def _compute_quantities(self):
        for rec in self:
            lines = rec.asn_line_ids.filtered(lambda l: l.asn_id.state != 'cancelled')
            rec.allocated_quantity = sum(lines.mapped('qty'))
            rec.received_quantity = sum(m.product_uom._compute_quantity(m.quantity, rec.uom_id)
                for m in lines.move_ids if m.state == 'done' and m.location_id.usage == 'supplier'
                and m.location_dest_id.usage == 'internal')
            rec.available_quantity = max(0, rec.quantity - rec.allocated_quantity) if rec.state == 'issued' else 0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if set(vals) & {'snapshot', 'issued_at', 'issued_by', 'allocation_revision'} or vals.get('state', 'draft') != 'draft':
                raise UserError(_('통보 발행 정보는 발행 동작으로만 생성합니다.'))
            vals.update(state='draft', snapshot=False, issued_at=False, issued_by=False, allocation_revision=0)
        return super().create(vals_list)

    def write(self, vals):
        protected = {'state', 'snapshot', 'issued_at', 'issued_by', 'allocation_revision'}
        content = {'name', 'agreement_id', 'uom_id', 'quantity', 'need_date', 'source_reference', 'source_kind', 'revision_of_id', 'revision_reason'}
        if set(vals) & protected and self.env.context.get('_no_po_transition') is not _NOTICE_TRANSITION:
            raise UserError(_('상태와 발행 스냅샷은 통보 처리 동작으로만 변경합니다.'))
        if set(vals) & content and any(r.state != 'draft' for r in self):
            raise UserError(_('발행 통보는 불변입니다. 취소 후 대체 통보를 작성하세요.'))
        return super().write(vals)

    def unlink(self):
        if any(r.state != 'draft' or r.asn_line_ids for r in self):
            raise UserError(_('발행 또는 ASN 근거가 있는 통보는 삭제할 수 없습니다.'))
        return super().unlink()

    def _lock(self):
        if not self:
            return
        self.check_access('read')
        self.flush_recordset()
        for rec in self.sorted('id'):
            check_actor(rec, rec.partner_id)
            # UPDATE serializes competing allocations under repeatable read too.
            self.env.cr.execute('UPDATE scm_no_po_notice SET allocation_revision=COALESCE(allocation_revision,0)+1 WHERE id=%s', (rec.id,))
        self.invalidate_recordset()

    @api.constrains('agreement_id', 'quantity', 'uom_id', 'need_date', 'revision_of_id', 'revision_reason')
    def _check_scope(self):
        for rec in self:
            check_actor(rec, rec.partner_id)
            check_base_quantity(rec.quantity, rec.product_id)
            if rec.uom_id != rec.product_id.uom_id:
                raise ValidationError(_('통보는 제품 기본 단위로만 발행합니다.'))
            prior = rec.revision_of_id
            if prior and (prior == rec or prior.state not in ('cancelled', 'closed')
                    or prior.company_id != rec.company_id or prior.partner_id != rec.partner_id
                    or prior.product_id != rec.product_id or not rec.revision_reason):
                raise ValidationError(_('같은 회사·공급사·품목의 취소 통보 및 개정 사유가 필요합니다.'))

    def _check_issued(self):
        for rec in self:
            rec._check_scope()
            agreement = rec.agreement_id
            if rec.state != 'issued' or not agreement.active:
                raise UserError(_('발행된 통보와 활성 협약이 필요합니다.'))
            agreement._check_valuation()
            agreement._check_component()

    def action_issue(self):
        self.check_access('write')
        self._lock()
        for rec in self:
            if rec.state == 'issued':
                continue
            if rec.state != 'draft':
                raise UserError(_('취소 통보를 다시 발행할 수 없습니다.'))
            agreement = rec.agreement_id
            agreement._check_scope()
            rec._check_scope()
            if not agreement.active or rec.need_date < agreement.date_start or (agreement.date_end and rec.need_date > agreement.date_end):
                raise UserError(_('협약 활성 여부와 필요일의 협약 유효기간을 확인하세요.'))
            snapshot = {'company_id': rec.company_id.id, 'supplier_id': rec.partner_id.id,
                'product_id': rec.product_id.id, 'uom_id': rec.uom_id.id, 'quantity': rec.quantity,
                'need_date': str(rec.need_date), 'agreement_reference': agreement.reference,
                'source_reference': rec.source_reference, 'revision_of_id': rec.revision_of_id.id or None,
                'revision_reason': rec.revision_reason or '', 'basis': 'non_financial_quantity_notice',
                'source_kind': rec.source_kind}
            if rec.source_kind == 'forecast':
                forecast = self.env['supplier.demand.forecast'].search([
                    ('company_id', '=', rec.company_id.id), ('partner_id', '=', rec.partner_id.id),
                    ('product_id', '=', rec.product_id.id), ('date', '=', rec.need_date)], limit=1)
                if not forecast:
                    raise UserError(_('현재 회사·업체·품목·필요일에 해당하는 소요전망이 없습니다.'))
                snapshot['forecast'] = {key: forecast[key] for key in (
                    'qty_required', 'cum_required', 'qty_onhand', 'qty_incoming', 'qty_shortfall')}
                snapshot['forecast'].update(original_id=forecast.id,
                    snapshot_at=str(forecast.snapshot_at), captured_at=str(fields.Datetime.now()),
                    date=str(forecast.date))
            snapshot.update(supplier_name=rec.partner_id.display_name,
                product_name=rec.product_id.display_name, product_code=rec.product_id.default_code or '',
                uom_name=rec.uom_id.name)
            rec.with_context(_no_po_transition=_NOTICE_TRANSITION).write({'state': 'issued',
                'issued_at': fields.Datetime.now(), 'issued_by': self.env.user.id,
                'snapshot': json.dumps(snapshot, ensure_ascii=False, sort_keys=True)})
        return True

    def action_cancel(self):
        self.check_access('write')
        self._lock()
        for rec in self:
            if rec.state == 'cancelled':
                continue
            if rec.asn_line_ids.move_ids.filtered(lambda m: m.state == 'done'):
                raise UserError(_('실입고가 있는 통보는 취소/대체할 수 없습니다. 별도 반품·잔량 정정 검토가 필요합니다.'))
            rec.asn_line_ids.asn_id.filtered(lambda a: a.state != 'cancelled').action_cancel()
            rec.with_context(_no_po_transition=_NOTICE_TRANSITION).write({'state': 'cancelled'})
        return True

    def action_close_remaining(self):
        """Keep partial receipts and stop all unreceived stock demand permanently.

        A successor notice contains only NEW remaining demand, never historical
        delivered quantity. Existing ASN quantities stay immutable as evidence.
        """
        self.check_access('write')
        self._lock()
        for rec in self:
            if rec.state == 'closed':
                continue
            if rec.state != 'issued':
                raise UserError(_('발행 통보만 잔량 종료할 수 있습니다.'))
            # Only this notice's unreceived moves are closed; receipts stay intact.
            rec.asn_line_ids.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))._action_cancel()
            from odoo.addons.supplier_portal_purchase.models.supplier_asn import _ASN_WRITE
            rec.asn_line_ids.asn_id.filtered(lambda a: a.state == 'announced').with_context(
                _asn_write=_ASN_WRITE).write({'state': 'closed'})
            rec.with_context(_no_po_transition=_NOTICE_TRANSITION).write({'state': 'closed'})
        return True

    def action_prepare_asn(self):
        self.ensure_one()
        self._check_issued()
        return {'type': 'ir.actions.act_window', 'res_model': 'supplier.asn', 'view_mode': 'form',
            'context': {'default_company_id': self.company_id.id, 'default_partner_id': self.partner_id.id,
                'default_expected_date': str(self.need_date), 'default_line_ids': [(0, 0, {
                    'product_id': self.product_id.id, 'no_po_notice_id': self.id,
                    'qty': self.available_quantity})]}}

    def _supplier_create_asn(self, quantity, expected_date, lot_name, request_key):
        """Only the authenticated controller calls this private adapter with sudo.

        The server-created partner/company capability is checked again here;
        client context flags cannot impersonate that capability.
        """
        self.ensure_one()
        check_actor(self, self.partner_id)
        key = str(uuid.UUID(request_key))
        check_base_quantity(quantity, self.product_id)
        date = fields.Date.to_date(expected_date)
        if not date:
            raise ValidationError(_('도착 예정일이 필요합니다.'))
        self._lock()
        existing = self.env['supplier.asn'].search([
            ('company_id', '=', self.company_id.id), ('partner_id', '=', self.partner_id.id),
            ('no_po_request_key', '=', key)], limit=1)
        if existing:
            line = existing.line_ids
            if (len(line) != 1 or line.no_po_notice_id != self or line.qty != quantity
                    or existing.expected_date != date or (line.lot_name or '') != lot_name):
                raise ValidationError(_('같은 제출번호에 서로 다른 납품내용을 사용할 수 없습니다.'))
            return existing
        self._check_issued()
        return self.env['supplier.asn'].create({
            'partner_id': self.partner_id.id, 'company_id': self.company_id.id,
            'expected_date': date, 'no_po_request_key': key,
            'line_ids': [(0, 0, {'product_id': self.product_id.id,
                'no_po_notice_id': self.id, 'qty': quantity, 'lot_name': lot_name})]})
