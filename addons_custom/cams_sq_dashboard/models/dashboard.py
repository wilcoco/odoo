from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class SqDashboard(models.AbstractModel):
    _name = 'iatf.sq.dashboard'
    _description = 'SQ 준비·운영 현황 조회'

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None):
        if not self.env.user.has_group('cams_sq.group_sq_user') and not self.env.su:
            raise AccessError(_('SQ 조회 권한이 필요합니다.'))
        start = fields.Date.to_date(date_from) if date_from else fields.Date.context_today(self).replace(day=1)
        end = fields.Date.to_date(date_to) if date_to else fields.Date.context_today(self)
        if end < start:
            raise UserError(_('조회 기간을 확인하십시오.'))
        standards = self.env['sq.standard'].search([('company_id','=',self.env.company.id)])
        sectors=[]
        for standard in standards:
            reqs=self.env['sq.doc.requirement'].search([('item_ids.standard_id','=',standard.id),('kind','=','document')])
            rules=self.env['sq.evidence.rule'].search([('item_id.standard_id','=',standard.id)]).with_context(sq_date_from=str(start),sq_date_to=str(end))
            snapshots=[r._snapshot() for r in rules]
            tasks=[]
            if self.env['ops.task'].has_access('read'):
                tasks=self.env['ops.task'].search([('sq_item_id.standard_id','=',standard.id),('due_date','>=',str(start)),('due_date','<=',str(end))])
            sectors.append({'id':standard.id,'name':standard.name,'items':len(standard.item_ids),
                'points':standard.total_points,'requirements':len(reqs),
                'ready':len(reqs.filtered(lambda r:r.state=='ready')),
                'candidate_rules':sum(bool(s['count']) and not s.get('unavailable') for s in snapshots),
                'unknown_rules':sum(not s['count'] or s.get('unavailable',False) for s in snapshots),
                'ops_tasks':len(tasks), 'ops_overdue':len([t for t in tasks if t.due_date<fields.Date.context_today(self) and t.state!='approved'])})
        boards=[]
        for model, label, date, qty in [('iatf.incoming.inspection','수입검사','inspection_date','quantity_received'),('iatf.shipping.inspection','출하검사','shipping_date','quantity')]:
            target=self.env[model]
            if not target.has_access('read'):
                boards.append({'name':label,'restricted':True});continue
            records=target.search([('company_id','=',self.env.company.id),(date,'>=',str(start)),(date,'<=',str(end)),('state','!=','cancelled')])
            decided=records.filtered(lambda r:r.state in ('decided','closed'))
            fail=decided.filtered(lambda r:r.result=='fail')
            board={'name':label,'model':model,'records':len(records),'decided':len(decided),'failed':len(fail),
                   'quantity':sum(records.mapped(qty)), 'inspection_rate':100*len(decided)/len(records) if records else None,
                   'failed_lot_rate':100*len(fail)/len(decided) if decided else None}
            units = {(r.product_uom_id if model == 'iatf.incoming.inspection' and r.product_uom_id
                      else r.product_id.uom_id).id for r in records}
            if len(units) > 1:
                board['quantity'] = None
            if model=='iatf.incoming.inspection':
                received=sum(decided.mapped('quantity_received'));rejected=sum(decided.mapped('quantity_rejected'))
                board.update(sample_quantity=sum(decided.mapped('quantity_inspected')), rejected_quantity=rejected,
                             rejected_rate=100*rejected/received if received else None)
                decided_units = {(r.product_uom_id or r.product_id.uom_id).id for r in decided}
                if len(decided_units) > 1:
                    board.update(sample_quantity=None, rejected_quantity=None, rejected_rate=None)
            boards.append(board)
        return {'company':self.env.company.name,'date_from':str(start),'date_to':str(end),'sectors':sectors,'boards':boards,
                'receipts':self.get_receipt_coverage(str(start),str(end))}

    @api.model
    def open_records(self, model, date_from, date_to):
        dates={'iatf.incoming.inspection':'inspection_date','iatf.shipping.inspection':'shipping_date'}
        if model not in dates:
            raise UserError(_('지원하지 않는 조회입니다.'))
        self.get_dashboard_data(date_from,date_to)
        self.env[model].check_access('read')
        return {'type':'ir.actions.act_window','res_model':model,'view_mode':'list',
                'domain':[('company_id','=',self.env.company.id),(dates[model],'>=',date_from),(dates[model],'<=',date_to),('state','!=','cancelled')],
                'context':{'create':False,'edit':False,'delete':False}}
