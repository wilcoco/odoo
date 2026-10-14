"""Read-only accounting-source review; a candidate is never a duplicate verdict."""
from collections import defaultdict

from odoo import Command, api, fields, models, _
from odoo.exceptions import UserError


class KrPurchaseSourceReview(models.TransientModel):
    _name = 'kr.purchase.source.review'
    _description = '매입 원천 중복 후보 검토'

    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    date_from = fields.Date(required=True, string='작성일 시작',
                            default=lambda self: fields.Date.start_of(fields.Date.context_today(self), 'month'))
    date_to = fields.Date(required=True, string='작성일 종료',
                          default=lambda self: fields.Date.end_of(fields.Date.context_today(self), 'month'))
    line_ids = fields.One2many('kr.purchase.source.review.line', 'review_id', readonly=True)
    result = fields.Text(string='조회 범위와 한계', readonly=True)

    @api.onchange('company_id', 'date_from', 'date_to')
    def _onchange_scope(self):
        self.line_ids = [Command.clear()]
        self.result = False

    @api.model
    def _source_families(self, move):
        families = set()
        if 'vendor_settlement_bill' in move._fields and move.vendor_settlement_bill:
            families.add('production')
        lines = move.invoice_line_ids
        if 'purchase_line_id' in lines._fields and lines.purchase_line_id:
            families.add('purchase')
        # A tax number on an already linked production/PO bill is supporting
        # evidence of that bill, not an additional recognition source.
        if not families and move.kr_approval_number:
            families.add('tax_document')
        return families

    def action_review(self):
        self.ensure_one()
        self.check_access('write')
        if self.company_id not in self.env.companies:
            raise UserError(_('현재 허용된 회사만 조회할 수 있습니다.'))
        if self.date_from > self.date_to:
            raise UserError(_('시작일은 종료일보다 늦을 수 없습니다.'))
        moves = self.env['account.move'].search([
            ('company_id', '=', self.company_id.id), ('state', '=', 'posted'),
            ('move_type', 'in', ('in_invoice', 'in_refund')),
            ('invoice_date', '>=', self.date_from), ('invoice_date', '<=', self.date_to),
        ], order='invoice_date,id', limit=5001)
        if len(moves) > 5000:
            raise UserError(_('조회 대상이 5,000건을 초과합니다. 기간을 나누어 조회하세요.'))
        groups = defaultdict(list)
        source_by_id = {}
        unclassified = 0
        for move in moves:
            families = self._source_families(move)
            source_by_id[move.id] = families
            if not families:
                unclassified += 1
                continue
            currency = move.currency_id
            key = (move.commercial_partner_id.id, currency.id, move.move_type,
                   currency.round(move.amount_untaxed), currency.round(move.amount_tax))
            groups[key].append(move)
        commands = [Command.clear()]
        labels = {'production': _('생산 정산'), 'purchase': _('구매 주문'),
                  'tax_document': _('세금 증빙만 연결')}
        for key, entries in groups.items():
            families = set().union(*(source_by_id[move.id] for move in entries))
            # Equal amounts within one source (e.g. repeat deliveries) are not
            # included here. This tool reviews disconnected source families.
            if len(entries) < 2 or len(families) < 2:
                continue
            commands.append(Command.create({
                'partner_id': key[0], 'currency_id': key[1], 'move_type': key[2],
                'amount_untaxed': key[3], 'amount_tax': key[4],
                'source_labels': ', '.join(labels[name] for name in sorted(families)),
                'invoice_count': len(entries),
                'invoice_ids': [Command.set([move.id for move in entries])],
            }))
        self.write({
            'line_ids': commands,
            'result': _('%(company)s · 작성일 %(start)s ~ %(end)s · 전기된 매입/환불 %(count)s건 조회. '
                        '원천 미분류 %(unknown)s건. 같은 업체·통화·문서유형·공급가액·세액이면서 '
                        '서로 다른 원천을 가진 전표를 검토 후보로 표시합니다. '
                        '실제 서로 다른 거래일 수 있으므로 중복으로 확정하지 않습니다. '
                        '금액이 다른 분할·합산 증빙, 미분류 전표, 기간 밖 거래는 대사하지 않습니다. '
                        '원천 명세를 확인하세요. 청구·승인번호·분개는 변경하지 않았습니다.') % {
                            'company': self.company_id.display_name, 'start': self.date_from,
                            'end': self.date_to, 'count': len(moves), 'unknown': unclassified},
        })
        return {'type': 'ir.actions.act_window', 'res_model': self._name, 'res_id': self.id,
                'view_mode': 'form', 'target': 'new', 'name': _('매입 원천 중복 후보 검토')}


class KrPurchaseSourceReviewLine(models.TransientModel):
    _name = 'kr.purchase.source.review.line'
    _description = '매입 원천 검토 후보'

    review_id = fields.Many2one('kr.purchase.source.review', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='업체', readonly=True)
    currency_id = fields.Many2one('res.currency', readonly=True)
    move_type = fields.Selection([('in_invoice', '매입 청구'), ('in_refund', '매입 환불')],
                                 string='문서 유형', readonly=True)
    amount_untaxed = fields.Monetary(string='전표별 공급가액', readonly=True)
    amount_tax = fields.Monetary(string='전표별 세액', readonly=True)
    source_labels = fields.Char(string='확인할 원천', readonly=True)
    invoice_count = fields.Integer(string='전표 수', readonly=True)
    invoice_ids = fields.Many2many('account.move', string='검토할 전표', readonly=True)

    def action_open_invoices(self):
        self.ensure_one()
        self.check_access('read')
        self.invoice_ids.check_access('read')
        return {'type': 'ir.actions.act_window', 'res_model': 'account.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.invoice_ids.ids)],
                'name': _('매입 원천 검토 전표')}
