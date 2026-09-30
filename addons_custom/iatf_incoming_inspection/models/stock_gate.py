"""Receipt-scoped quarantine using ordinary internal locations and stock moves."""
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools.float_utils import float_compare

from .iqc_service import is_service, service


def company_check(record, company):
    if not record.env.su and company not in record.env.companies:
        raise AccessError(_('허용된 회사의 IQC 재고만 처리할 수 있습니다.'))


class StockLocation(models.Model):
    _inherit = 'stock.location'

    iqc_pending = fields.Boolean(readonly=True, copy=False, index=True)
    iqc_warehouse_id = fields.Many2one('stock.warehouse', readonly=True, copy=False)
    iqc_receipt_id = fields.Many2one('stock.picking', readonly=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            for vals in vals_list:
                if any(vals.get(key, self.env.context.get('default_'+key)) for key in
                       ('iqc_pending','iqc_warehouse_id','iqc_receipt_id')):
                    raise UserError(_('IQC 대기 위치는 입고 서비스가 생성합니다.'))
                parent=self.browse(vals.get('location_id', self.env.context.get('default_location_id')))
                if parent.iqc_pending:
                    raise UserError(_('IQC 대기 위치에 임의 하위 위치를 만들 수 없습니다.'))
        return super().create(vals_list)

    def write(self, vals):
        guarded={'iqc_pending','iqc_warehouse_id','iqc_receipt_id','location_id','usage','company_id','active'}
        if not is_service(self.env) and guarded & vals.keys() and (
                self.filtered('iqc_pending') or {'iqc_pending','iqc_warehouse_id','iqc_receipt_id'} & vals.keys()
                or self.browse(vals.get('location_id')).iqc_pending):
            raise UserError(_('검사대기 재고의 위치·회사·대기 표시는 직접 변경할 수 없습니다.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('iqc_pending'):
            raise UserError(_('IQC 대기 위치와 입고 이력은 삭제할 수 없습니다.'))
        return super().unlink()


class StockQuant(models.Model):
    _inherit = 'stock.quant'

    @api.model
    def _iqc_pending_quantities(self, company_id, product_ids=None, warehouse_id=None):
        company=self.env['res.company'].browse(company_id).exists()
        if not company:
            raise UserError(_('회사를 지정하세요.'))
        company_check(self, company)
        domain=[('company_id','=',company.id),('location_id.iqc_pending','=',True)]
        if product_ids is not None:
            domain.append(('product_id','in',product_ids))
        if warehouse_id is not None:
            domain.append(('location_id.iqc_warehouse_id','=',warehouse_id))
        totals={}
        for quant in self.search(domain):
            key=(quant.product_id.id,quant.owner_id.id or False)
            row=totals.setdefault(key,{'company_id':company.id,'product_id':quant.product_id.id,
                'uom_id':quant.product_id.uom_id.id,'owner_id':quant.owner_id.id or False,
                'quantity':0.0,'reserved_quantity':0.0})
            row['quantity']+=quant.quantity
            row['reserved_quantity']+=quant.reserved_quantity
        return list(totals.values())

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            for vals in vals_list:
                location=self.env['stock.location'].browse(vals.get('location_id',self.env.context.get('default_location_id')))
                if location.iqc_pending:
                    raise UserError(_('검사대기 재고는 승인된 입고·해제·반품 이동으로만 생성합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        location=self.env['stock.location'].browse(vals.get('location_id'))
        if not is_service(self.env) and vals and (self.filtered('location_id.iqc_pending') or location.iqc_pending):
            raise UserError(_('검사대기 quant의 직접 수정·재고조정은 허용되지 않습니다.'))
        return super().write(vals)

    def unlink(self):
        if not is_service(self.env) and self.filtered('location_id.iqc_pending'):
            raise UserError(_('검사대기 quant는 직접 삭제할 수 없습니다.'))
        return super().unlink()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    iqc_pending_location_id = fields.Many2one('stock.location', readonly=True, copy=False)

    def _iqc_get_pending_location(self):
        self.ensure_one()
        company_check(self,self.company_id)
        self.env.cr.execute('UPDATE stock_picking SET write_date = write_date WHERE id = %s',[self.id])
        self.invalidate_recordset(['iqc_pending_location_id'])
        if self.iqc_pending_location_id:
            return self.iqc_pending_location_id
        warehouse=self.picking_type_id.warehouse_id
        if not warehouse or warehouse.company_id != self.company_id:
            raise UserError(_('입고 창고와 회사가 명확해야 IQC 대기 위치를 만들 수 있습니다.'))
        self.env.cr.execute('UPDATE stock_warehouse SET write_date = write_date WHERE id = %s',[warehouse.id])
        Location=service(self.env['stock.location'].sudo())
        parent=Location.search([('iqc_pending','=',True),('iqc_warehouse_id','=',warehouse.id),
                                ('iqc_receipt_id','=',False)],limit=1)
        if not parent:
            parent=Location.create({'name':'IQC 검사대기','usage':'internal','company_id':self.company_id.id,
                'location_id':warehouse.view_location_id.id,'iqc_pending':True,'iqc_warehouse_id':warehouse.id})
        location=Location.create({'name':self.name,'usage':'internal','company_id':self.company_id.id,
            'location_id':parent.id,'iqc_pending':True,'iqc_warehouse_id':warehouse.id,'iqc_receipt_id':self.id})
        service(self).write({'iqc_pending_location_id':location.id})
        return location

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env) and any(v.get('iqc_pending_location_id',self.env.context.get('default_iqc_pending_location_id')) for v in vals_list):
            raise UserError(_('IQC 대기 위치 연결은 입고 서비스가 기록합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        if not is_service(self.env) and ('iqc_pending_location_id' in vals or
                (self.filtered('iqc_pending_location_id') and {'company_id','partner_id','picking_type_id','location_id'} & vals.keys())):
            raise UserError(_('IQC 입고의 회사·공급업체·원천 연결은 직접 바꿀 수 없습니다.'))
        return super().write(vals)


class StockMove(models.Model):
    _inherit = 'stock.move'

    iqc_release_location_id = fields.Many2one('stock.location',readonly=True,copy=True)
    iqc_inspection_id = fields.Many2one('iatf.incoming.inspection',readonly=True,copy=False,index=True)
    iqc_approval_request_id = fields.Many2one('iatf.approval.request',readonly=True,copy=False)
    iqc_movement_kind = fields.Selection([('release','합격 재고 이동'),('return','불합격 반품')],readonly=True,copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            for vals in vals_list:
                if any(vals.get(k,self.env.context.get('default_'+k)) for k in
                       ('iqc_inspection_id','iqc_approval_request_id','iqc_movement_kind','iqc_release_location_id')):
                    raise UserError(_('IQC 처리 이동은 검사 문서의 승인 절차로만 만듭니다.'))
        return super().create(vals_list)

    def write(self, vals):
        protected={'iqc_inspection_id','iqc_approval_request_id','iqc_movement_kind','iqc_release_location_id'}
        evidence={'product_id','product_uom','product_uom_qty','quantity','location_id','location_dest_id',
                  'company_id','picking_id','origin_returned_move_id','purchase_line_id','state','date'}
        if not is_service(self.env):
            if protected & vals.keys() or ('state' in vals and self.filtered('iqc_inspection_id')):
                raise UserError(_('IQC 승인 연결·처리 상태를 직접 바꿀 수 없습니다.'))
            if self.filtered(lambda m:m.state=='done' and (m.iqc_inspection_id or m.move_line_ids.filtered('iqc_receipt_managed'))) and evidence & vals.keys():
                raise UserError(_('완료된 IQC 입고·이동 근거는 변경할 수 없습니다.'))
            if vals.get('state')=='done' and self.filtered(lambda m:m.iqc_inspection_id or (m.location_id.usage=='supplier' and m.location_dest_id.usage=='internal')):
                raise UserError(_('입고 완료는 실제 재고 처리로만 기록합니다.'))
            scoped=self.filtered(lambda m:m.iqc_inspection_id and m.state not in ('done','cancel'))
            if scoped and ('picking_id' in vals or 'move_line_ids' in vals):
                raise UserError(_('IQC 처리 전표와 상세 연결을 임의로 바꿀 수 없습니다.'))
            if scoped and evidence & vals.keys():
                with self.env.cr.savepoint():
                    scoped._iqc_check_pending_move()
                    result=super(StockMove,service(self)).write(vals)
                    scoped._iqc_check_pending_move()
                    return result
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda m:m.iqc_inspection_id or m.move_line_ids.filtered('iqc_receipt_managed')):
            raise UserError(_('IQC 입고·처리 이동 근거는 삭제하지 않습니다.'))
        return super().unlink()

    def _iqc_prepare_receipts(self):
        for move in self.filtered(lambda m:m.state not in ('done','cancel') and m.location_id.usage=='supplier'
                                  and m.location_dest_id.usage=='internal' and m.product_id.is_storable):
            if not move.picking_id or not move.picking_id.partner_id:
                raise UserError(_('공급업체와 입고 전표가 있어야 IQC 입고 범위를 확인할 수 있습니다.'))
            pending=move.picking_id._iqc_get_pending_location()
            if not move.iqc_release_location_id:
                if move.location_dest_id.iqc_pending:
                    raise UserError(_('기존 입고의 원래 도착 위치가 확인되지 않습니다.'))
                service(move).write({'iqc_release_location_id':move.location_dest_id.id})
            for line in move.move_line_ids.filtered(lambda ml:ml.quantity>0):
                if (line.company_id!=move.company_id or line.product_id!=move.product_id
                        or line.location_id.usage!='supplier'
                        or (line.picking_id and line.picking_id!=move.picking_id)):
                    raise UserError(_('입고 상세의 회사·제품·공급 위치·전표가 원 이동과 다릅니다.'))
                if not line.iqc_receipt_managed:
                    service(line).write({'iqc_receipt_managed':True,'picking_id':move.picking_id.id,
                        'iqc_release_location_id':(move.iqc_release_location_id if line.location_dest_id.iqc_pending else line.location_dest_id).id,'location_dest_id':pending.id})
            service(move).write({'location_dest_id':pending.id})

    def _iqc_check_pending_move(self):
        for move in self:
            if move.location_dest_id.iqc_pending or move.move_line_ids.filtered('location_dest_id.iqc_pending'):
                lines=move.move_line_ids.filtered(lambda ml:ml.quantity>0)
                if (move.location_id.usage!='supplier' or not move.iqc_release_location_id
                        or move.location_dest_id!=move.picking_id.iqc_pending_location_id
                        or any(not ml.iqc_receipt_managed or ml.location_dest_id!=move.location_dest_id for ml in lines)):
                    raise UserError(_('검사대기 위치로 임의 재고를 추가할 수 없습니다. 실제 공급자 입고를 사용하세요.'))
            if move.iqc_inspection_id or move.location_id.iqc_pending or move.move_line_ids.filtered('location_id.iqc_pending'):
                if not move.iqc_inspection_id:
                    raise UserError(_('검사대기 위치의 재고는 승인된 IQC 해제·반품으로만 이동합니다.'))
                move.iqc_inspection_id._iqc_validate_movement(move)

    def _iqc_check_actual_stock(self, lines=None):
        if lines is None:
            lines=self.move_line_ids.filtered(lambda line:line.quantity>0 and line.picked)
        groups=defaultdict(lambda:{'qty':0.0,'lines':self.env['stock.move.line']})
        for line in lines:
            move=line.move_id
            if line.location_id.usage!='internal':
                continue
            managed=self.env['stock.move.line'].sudo().search_count([
                ('iqc_receipt_managed','=',True),('company_id','=',line.company_id.id),
                ('product_id','=',line.product_id.id),('move_id.state','=','done')],limit=1)
            if not line.location_id.iqc_pending and not (managed and (move.raw_material_production_id or line.location_dest_id.usage=='production')):
                continue
            key=(line.company_id.id,line.product_id.id,line.location_id.id,line.lot_id.id or False,
                 line.package_id.id or False,line.owner_id.id or False)
            groups[key]['qty']+=line.product_uom_id._compute_quantity(line.quantity,line.product_id.uom_id)
            groups[key]['lines']|=line
        for key,data in groups.items():
            company,product,location,lot,package,owner=key
            Quant=self.env['stock.quant'].sudo()
            domain=[('company_id','=',company),('product_id','=',product),('location_id','=',location),
                    ('lot_id','=',lot),('package_id','=',package),('owner_id','=',owner)]
            quants=Quant.search(domain)
            if quants:
                quants.flush_recordset()
                self.env.cr.execute('UPDATE stock_quant SET write_date = write_date WHERE id IN %s',[tuple(quants.ids)])
                quants.invalidate_recordset()
            other_lines=self.env['stock.move.line'].sudo().search([
                ('company_id','=',company),('product_id','=',product),('location_id','=',location),
                ('lot_id','=',lot),('package_id','=',package),('owner_id','=',owner),
                ('move_id','not in',data['lines'].move_id.ids),('state','not in',('draft','done','cancel'))])
            other_reserved=sum(l.product_uom_id._compute_quantity(l.quantity,l.product_id.uom_id) for l in other_lines)
            own_reserved=sum(l.product_uom_id._compute_quantity(l.quantity,l.product_id.uom_id)
                             for l in data['lines'] if l.state not in ('draft','done','cancel'))
            unavailable=max(other_reserved,sum(quants.mapped('reserved_quantity'))-own_reserved,0)
            available=sum(quants.mapped('quantity'))-unavailable
            rounding=data['lines'][0].product_id.uom_id.rounding
            if float_compare(data['qty'],available,precision_rounding=rounding)>0:
                raise UserError(_('IQC 관리 품목은 실제 원위치 가용 재고를 초과하거나 다른 작업 예약을 소비할 수 없습니다.'))

    def _action_cancel(self):
        pending=self.filtered(lambda m:m.iqc_inspection_id and m.state not in ('done','cancel'))
        if pending:
            pending.check_access('write')
            for move in pending:
                company_check(move,move.company_id)
                move.iqc_inspection_id._iqc_lock()
            return super(StockMove,service(self))._action_cancel()
        return super()._action_cancel()

    def _split(self, qty, restrict_partner_id=False):
        vals_list=super()._split(qty,restrict_partner_id=restrict_partner_id)
        if self.iqc_release_location_id and self.location_id.usage=='supplier':
            # Unreceived supplier quantities carry the original destination,
            # not an earlier receipt's service-only capture. Their own actual
            # receipt will validate and capture that destination again.
            for vals in vals_list:
                vals['location_dest_id']=self.iqc_release_location_id.id
                vals['iqc_release_location_id']=False
        if self.iqc_inspection_id:
            if not is_service(self.env):
                raise UserError(_('IQC 이동의 분할은 검증된 재고 처리 중에만 가능합니다.'))
            for vals in vals_list:
                vals.update(iqc_inspection_id=self.iqc_inspection_id.id,
                    iqc_approval_request_id=self.iqc_approval_request_id.id,
                    iqc_movement_kind=self.iqc_movement_kind)
        return vals_list

    def _action_assign(self, force_qty=False):
        self._iqc_check_pending_move()
        scoped=self.filtered('iqc_inspection_id')
        for move in service(scoped):
            if move.state in ('done','cancel'):
                continue
            receipt=move.iqc_inspection_id._iqc_source()
            need=max(move.product_uom_qty-move.quantity,0)
            if need:
                qty=move.product_uom._compute_quantity(need,move.product_id.uom_id)
                move._update_reserved_quantity(qty,receipt.location_dest_id,
                    lot_id=receipt.lot_id,package_id=receipt.result_package_id,
                    owner_id=receipt.owner_id,strict=True)
            move.write({'state':'assigned' if float_compare(move.quantity,move.product_uom_qty,
                        precision_rounding=move.product_uom.rounding)>=0 else 'partially_available'})
        return super(StockMove,service(self-scoped))._action_assign(force_qty=force_qty)

    def _action_done(self, cancel_backorder=False):
        with self.env.cr.savepoint():
            self._iqc_prepare_receipts()
            self._iqc_check_pending_move()
            self._iqc_check_actual_stock()
            done=super(StockMove,service(self))._action_done(cancel_backorder=cancel_backorder)
            for move in done:
                if move.move_line_ids.filtered('iqc_receipt_managed'):
                    move.picking_id._create_iqc_inspections()
            return done


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    iqc_receipt_managed = fields.Boolean(readonly=True,copy=False,index=True)
    iqc_release_location_id = fields.Many2one('stock.location',readonly=True,copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        if not is_service(self.env):
            for vals in vals_list:
                parent=self.env['stock.move'].browse(vals.get('move_id',self.env.context.get('default_move_id')))
                if parent.state=='done' and (parent.iqc_inspection_id or parent.move_line_ids.filtered('iqc_receipt_managed')):
                    raise UserError(_('완료된 IQC 입고·처리에 새 상세를 추가할 수 없습니다.'))
                if any(vals.get(k,self.env.context.get('default_'+k)) for k in ('iqc_receipt_managed','iqc_release_location_id')):
                    raise UserError(_('IQC 입고 범위는 실제 입고 서비스가 기록합니다.'))
        return super().create(vals_list)

    def write(self, vals):
        protected={'iqc_receipt_managed','iqc_release_location_id'}
        evidence={'move_id','picking_id','company_id','product_id','product_uom_id','quantity','lot_id','lot_name',
                  'location_id','location_dest_id','owner_id','package_id','result_package_id','state','date'}
        if not is_service(self.env):
            if protected & vals.keys():
                raise UserError(_('IQC 입고 범위는 직접 바꿀 수 없습니다.'))
            if self.filtered(lambda l:l.state=='done' and (l.iqc_receipt_managed or l.move_id.iqc_inspection_id)) and evidence & vals.keys():
                raise UserError(_('완료된 IQC 입고·처리 상세는 변경할 수 없습니다.'))
        pending=self.filtered(lambda l:l.move_id.iqc_inspection_id and l.state not in ('done','cancel'))
        if pending and not is_service(self.env):
            with self.env.cr.savepoint():
                pending.move_id._iqc_check_pending_move()
                result=super(StockMoveLine,service(self)).write(vals)
                pending.move_id._iqc_check_pending_move()
                pending.move_id._iqc_check_actual_stock()
                return result
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda l:l.state=='done' and (l.iqc_receipt_managed or l.move_id.iqc_inspection_id)):
            raise UserError(_('완료된 IQC 상세 근거는 삭제할 수 없습니다.'))
        return super().unlink()

    def _action_done(self):
        self.move_id._iqc_check_pending_move()
        self.move_id._iqc_check_actual_stock(self.filtered(lambda l:l.quantity>0))
        return super(StockMoveLine,service(self))._action_done()
