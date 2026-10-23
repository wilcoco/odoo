"""Reconcile actual receipts, including receipts without a visible inspection.

This is a read-only projection of stock and IQC, never a second inspection ledger.
"""
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


STATES = [
    ('legacy', '기존 입고 · 상세 연결 확인 필요'),
    ('missing', '검사 연결 미확인'),
    ('mismatch', '입고 근거 불일치'),
    ('pending', '미판정'),
    ('approval', '승인 대기'),
    ('partial', '일부 미판정'),
    ('decided', '판정·승인 완료'),
    ('restricted', '조회 권한 부족'),
    ('outside', '대상 입고 아님'),
]


class SqReceiptLine(models.Model):
    _inherit = 'stock.move.line'

    sq_iqc_status = fields.Selection(STATES, compute='_compute_sq_iqc', string='입고 대비 검사 상태')
    sq_iqc_inspection_id = fields.Many2one('iatf.incoming.inspection', compute='_compute_sq_iqc', string='연결 검사')

    def action_sq_open_inspection(self):
        self.ensure_one()
        self.check_access('read')
        inspection = self.sq_iqc_inspection_id
        if not inspection:
            raise UserError(_('조회 가능한 연결 검사가 없습니다. 입고 근거와 원천 조회 권한을 확인하십시오.'))
        inspection.check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('연결 수입검사'),
                'res_model': inspection._name, 'res_id': inspection.id, 'view_mode': 'form',
                'context': dict(self.env.context, create=False, edit=False, delete=False)}

    @api.depends_context('uid', 'allowed_company_ids')
    def _compute_sq_iqc(self):
        self.check_access('read')
        target = self.env['iatf.incoming.inspection']
        inspections = target.search([('receipt_move_line_id', 'in', self.ids),
                                     ('company_id', 'in', self.env.companies.ids)]) if target.has_access('read') else target
        by_line = {i.receipt_move_line_id.id: i for i in inspections}
        for line in self:
            line.sq_iqc_inspection_id = False
            line.sq_iqc_status = 'outside'
            if not (line.state == 'done' and line.quantity > 0 and line.location_id.usage == 'supplier'
                    and line.location_dest_id.usage == 'internal'):
                continue
            if not target.has_access('read'):
                line.sq_iqc_status = 'restricted'
                continue
            inspection = by_line.get(line.id)
            line.sq_iqc_inspection_id = inspection or False
            if not line.iqc_receipt_managed:
                line.sq_iqc_status = 'legacy'
            elif not inspection:
                # A record rule can hide the inspection: never call this proven absence.
                line.sq_iqc_status = 'missing'
            elif (inspection.receipt_snapshot != inspection._iqc_receipt_values(line)
                  or inspection.company_id != line.company_id or inspection.product_id != line.product_id
                  or inspection.lot_id != line.lot_id or inspection.picking_id != line.picking_id
                  or inspection.product_uom_id != line.product_uom_id
                  or inspection.quantity_received != line.quantity):
                line.sq_iqc_status = 'mismatch'
            elif inspection.state not in ('decided', 'closed') or not inspection.result:
                line.sq_iqc_status = 'pending'
            elif inspection.approval_state != 'approved':
                line.sq_iqc_status = 'approval'
            elif (inspection.result == 'partial'
                  or inspection.quantity_received - inspection.quantity_accepted - inspection.quantity_rejected
                  > line.product_uom_id.rounding / 2):
                line.sq_iqc_status = 'partial'
            else:
                line.sq_iqc_status = 'decided'  # Includes rejected receipts; this is NOT a pass rate.


class SqReceiptDashboard(models.AbstractModel):
    _inherit = 'iatf.sq.dashboard'

    @api.model
    def _receipt_domain(self, date_from, date_to):
        start, end = fields.Date.to_date(date_from), fields.Date.to_date(date_to)
        if not start or not end or end < start or (end - start).days > 366:
            raise UserError(_('입고 대조 기간은 최대 367일로 지정하십시오.'))
        tz = pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')
        def utc(day):
            return fields.Datetime.to_string(tz.localize(datetime.combine(day, time.min)).astimezone(pytz.UTC).replace(tzinfo=None))
        return [('company_id', '=', self.env.company.id), ('state', '=', 'done'), ('quantity', '>', 0),
                ('location_id.usage', '=', 'supplier'), ('location_dest_id.usage', '=', 'internal'),
                ('date', '>=', utc(start)), ('date', '<', utc(end + timedelta(days=1)))]

    @api.model
    def get_receipt_coverage(self, date_from, date_to):
        if not self.env.su and not self.env.user.has_group('cams_sq.group_sq_user'):
            raise AccessError(_('SQ 조회 권한이 필요합니다.'))
        domain = self._receipt_domain(date_from, date_to)
        sources = ('stock.move.line', 'iatf.incoming.inspection')
        if not all(self.env[m].has_access('read') for m in sources):
            return {'restricted': True}
        try:
            lines = self.env['stock.move.line'].search(domain)
            counts = {key: len(lines.filtered(lambda l: l.sq_iqc_status == key)) for key, _label in STATES}
        except AccessError:
            return {'restricted': True}
        return {'total': len(lines), 'counts': counts,
                'decision_rate': 100 * counts['decided'] / len(lines) if lines else None,
                'labels': dict(STATES), 'restricted': False}

    @api.model
    def open_receipt_coverage(self, date_from, date_to):
        if not self.env.su and not self.env.user.has_group('cams_sq.group_sq_user'):
            raise AccessError(_('SQ 조회 권한이 필요합니다.'))
        self.env['stock.move.line'].check_access('read')
        return {'type': 'ir.actions.act_window', 'name': _('입고 대비 검사 대조'),
                'res_model': 'stock.move.line', 'view_mode': 'list',
                'views': [(self.env.ref('cams_sq_dashboard.view_sq_receipt_list').id, 'list')],
                'domain': self._receipt_domain(date_from, date_to),
                'context': dict(self.env.context, create=False, edit=False, delete=False)}
