"""Keep an issued plan and its MO quantity consistent; never resize started work."""
import math
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_compare

_QUANTITY_CHANGE = object()


class PlanningQuantity(models.Model):
    _inherit = 'injection.planning.line'

    calculation_detail = fields.Text(string='계획·수지 산정 근거', compute='_compute_calculation_detail')

    def _material_basis(self):
        self.ensure_one()
        bom = self.mo_id.bom_id or self.env['mrp.bom'].find_for_purpose(self.product_id, 'injection')
        if not bom or bom.product_qty <= 0:
            return []
        output = bom.product_uom_id._compute_quantity(bom.product_qty, self.product_id.uom_id, round=False)
        return [{
            'bom_id': bom.id, 'bom': bom.display_name, 'bom_qty': bom.product_qty,
            'bom_uom': bom.product_uom_id.name, 'base_output': output,
            'material': line.product_id.display_name, 'material_id': line.product_id.id,
            'line_qty': line.product_qty, 'line_uom': line.product_uom_id.name,
            'unit_qty': line.product_uom_id._compute_quantity(line.product_qty, line.product_id.uom_id, round=False) / output,
            'unit': line.product_id.uom_id.name,
        } for line in bom.bom_line_ids if not line._skip_bom_line(self.product_id)]

    @api.depends('planned_qty', 'demand_qty', 'defect_rate', 'initial_scrap', 'current_stock',
                 'mold_id', 'mo_id.bom_id', 'product_id')
    def _compute_calculation_detail(self):
        for line in self:
            texts = [_('순수요 %(d)g / 계산 당시 가용재고 %(s)g / 불량률 %(r)g%% / 시업 불량 %(i)g / 확정 계획 %(p)g') % {
                'd': line.demand_qty, 's': line.current_stock, 'r': line.defect_rate,
                'i': line.initial_scrap, 'p': line.planned_qty}]
            texts.append(_('순수요에는 실행 시점의 안전재고·진행 물량 정책이 반영됩니다. 아래는 현재 연결 BOM 기준이며 실측 소비량이 아닙니다.'))
            for basis in line._material_basis():
                texts.append(_('%(bom)s: 기준 %(bom_qty)g %(bom_uom)s / %(material)s %(line_qty)g %(line_uom)s → 개당 %(unit_qty)g %(unit)s × 계획 %(planned)g = %(total)g %(unit)s') % dict(
                    basis, planned=line.planned_qty, total=line.planned_qty * basis['unit_qty']))
            line.calculation_detail = '\n'.join(texts)

    def write(self, values):
        if self.env.context.get('_planning_quantity_change') is not _QUANTITY_CHANGE:
            if set(values) & self._DERIVED_INPUTS and any(line.mo_id for line in self):
                raise UserError(_('제조지시를 발행한 계획은 직접 변경할 수 없습니다. 수량 감축 또는 잔량 취소 후 재계획하십시오.'))
        return super().write(values)

    def unlink(self):
        if any(line.mo_id for line in self):
            raise UserError(_('제조지시가 연결된 계획 행은 이력으로 보존합니다.'))
        return super().unlink()

    def action_quantity_change(self):
        self.ensure_one()
        if not self.mo_id:
            raise UserError(_('제조지시가 발행된 계획을 선택하십시오.'))
        return {'type': 'ir.actions.act_window', 'res_model': 'injection.plan.quantity.change',
                'view_mode': 'form', 'target': 'new', 'context': {
                    'default_line_id': self.id, 'default_expected_qty': self.mo_id.product_qty,
                    'default_quantity': self.mo_id.product_qty}}


class ProductionQuantity(models.Model):
    _inherit = 'mrp.production'

    def write(self, values):
        if {'product_qty', 'product_uom_id'} & values.keys() and self.env.context.get('_planning_quantity_change') is not _QUANTITY_CHANGE:
            for mo in self.filtered('planning_line_id'):
                if ('product_qty' in values and float_compare(mo.product_qty, values['product_qty'], precision_rounding=mo.product_uom_id.rounding)) or ('product_uom_id' in values and values['product_uom_id'] != mo.product_uom_id.id):
                    raise UserError(_('계획 연결 제조지시의 수량·단위는 직접 변경할 수 없습니다. 계획 상세의 수량 감축을 사용하십시오.'))
        return super().write(values)


class QuantityChange(models.TransientModel):
    _name = 'injection.plan.quantity.change'
    _description = '발행 계획 수량 감축'

    line_id = fields.Many2one('injection.planning.line', required=True)
    expected_qty = fields.Float(string='조회 당시 수량', required=True, readonly=True)
    quantity = fields.Float(string='변경 수량', required=True)
    reason = fields.Text(string='감축 사유', required=True)

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group('injection_planning.group_planning_manager'):
            raise AccessError(_('계획 관리자만 발행 계획의 수량 감축을 확정할 수 있습니다.'))
        line = self.line_id
        line.check_access('write')
        run = line.planning_run_id
        run.check_access('write')
        self.env.cr.execute('SELECT id FROM injection_planning_run WHERE id=%s FOR UPDATE', [run.id])
        self.env.cr.execute('SELECT id FROM injection_planning_line WHERE id=%s FOR UPDATE', [line.id])
        line.invalidate_recordset()
        mo = line.mo_id
        mo.check_access('write')
        if not mo or mo.planning_line_id != line:
            raise UserError(_('계획과 제조지시 연결이 다릅니다. 다시 조회하십시오.'))
        self.env.cr.execute('SELECT id FROM mrp_production WHERE id=%s FOR UPDATE', [mo.id])
        mo.invalidate_recordset()
        rounding = mo.product_uom_id.rounding
        if float_compare(mo.product_qty, self.expected_qty, precision_rounding=rounding):
            raise UserError(_('다른 작업에서 수량이 변경됐습니다. 다시 조회하십시오.'))
        if not (self.reason or '').strip() or not math.isfinite(self.quantity) or self.quantity <= 0 or self.quantity >= mo.product_qty:
            raise UserError(_('양수의 감축 수량과 사유를 입력하십시오. 증량은 능력·일정을 재계산해야 합니다.'))
        children = self.env['mrp.production'].search_count([('parent_planning_mo_id', '=', mo.id), ('state', '!=', 'cancel')]) if 'parent_planning_mo_id' in mo._fields else 0
        if mo.state not in ('draft', 'confirmed') or mo.qty_produced or children:
            raise UserError(_('시작하거나 단위 지시를 만든 계획은 수량을 바꾸지 않습니다. 잔량 취소 후 재계획하십시오.'))
        with self.env.cr.savepoint():
            old = mo.product_qty
            wizard = self.env['change.production.qty'].with_context(_planning_quantity_change=_QUANTITY_CHANGE).create({
                'mo_id': mo.id, 'product_qty': self.quantity})
            wizard.change_prod_qty()
            line.with_context(_planning_quantity_change=_QUANTITY_CHANGE).write({'planned_qty': self.quantity})
            mo.message_post(body=_('계획 수량 감축: %(old)g → %(new)g. 사유: %(reason)s. 계획 파생 결과는 재검증이 필요합니다.') % {
                'old': old, 'new': self.quantity, 'reason': self.reason})
        return {'type': 'ir.actions.act_window_close'}
