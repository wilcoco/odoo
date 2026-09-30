"""Run only through night_runtime shell on the assigned synthetic IQC database."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from psycopg2.errors import SerializationFailure
from odoo import api, Command
from odoo.exceptions import UserError
from odoo.tests.common import new_test_user

assert env.cr.dbname=='cams_night_tax_iqc_gate'
ctx=dict(env.context,no_reset_password=True,mail_notify_force_send=False,mail_create_nosubscribe=True)
e=env['res.users'].with_context(ctx).env
actor=new_test_user(e,login='iqc-concurrency-operator',groups='stock.group_stock_user,iatf_incoming_inspection.group_incoming_inspection_user')
company_id=env.company.id
warehouse=env['stock.warehouse'].search([('company_id','=',company_id)],limit=1)
supplier=env['res.partner'].create({'name':'SYNTHETIC IQC race supplier','supplier_rank':1})
product=env['product.product'].create({'name':'SYNTHETIC IQC concurrency component','is_storable':True})
source=env.ref('stock.stock_location_suppliers')
registry=env.registry


def approved_receipt():
    p=env['stock.picking'].with_context(ctx).with_user(actor).create({'picking_type_id':warehouse.in_type_id.id,
        'partner_id':supplier.id,'location_id':source.id,'location_dest_id':warehouse.lot_stock_id.id})
    m=env['stock.move'].with_context(ctx).with_user(actor).create({'name':'SYNTHETIC receipt','picking_id':p.id,
        'product_id':product.id,'product_uom':product.uom_id.id,'product_uom_qty':10,
        'location_id':source.id,'location_dest_id':warehouse.lot_stock_id.id})
    m._action_confirm()
    m.quantity=10
    m.picked=True
    p.with_context(skip_backorder=True).button_validate()
    iqc=p.iqc_inspection_ids
    iqc.action_start_inspection()
    iqc.write({'inspection_type':'full','quantity_inspected':10,'quantity_accepted':10,'result':'pass','disposition':'accept',
        'line_ids':[Command.create({'characteristic_name':'SYNTHETIC check','specification':'fixture only',
            'measured_value':'fixture verified','result':'pass'})]})
    iqc.action_decide()
    iqc.approval_request_id.write({'line_ids':[Command.create({'sequence':10,'user_id':actor.id})]})
    iqc.action_submit_approval()
    iqc.action_approve_approval()
    return iqc


def race(iqc,correction=False):
    inspection_id=iqc.id
    env.cr.commit()  # Synthetic fixture harness only, never business code.
    barrier=threading.Barrier(2)
    retries=[]
    def worker(index):
        for attempt in range(4):
            with registry.cursor() as cr:
                work=api.Environment(cr,actor.id,dict(ctx,allowed_company_ids=[company_id]))
                rec=work['iatf.incoming.inspection'].browse(inspection_id)
                rec.read(['state','approval_state'])
                if not attempt:
                    barrier.wait(timeout=10)
                try:
                    if correction and index:
                        rec.action_reset_inspection()
                        result='reopened'
                    else:
                        rec.action_prepare_release()
                        result='prepared'
                    cr.commit()
                    return result
                except SerializationFailure:
                    cr.rollback()
                    retries.append(index)
                except UserError:
                    cr.rollback()
                    return 'blocked'
        raise AssertionError('Retry budget exceeded')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,i) for i in (0,1)]
        outcomes=[f.result(timeout=30) for f in futures]
    env.cr.rollback()
    env.invalidate_all()
    rec=env['iatf.incoming.inspection'].browse(inspection_id)
    active=rec.movement_ids.filtered(lambda m:m.state not in ('done','cancel'))
    result={'outcomes':outcomes,'serialization_retries':len(retries),'active_moves':len(active),
            'planned':sum(active.mapped('product_uom_qty')),'approval_state':rec.approval_state}
    assert retries,result
    assert outcomes.count('blocked')==1,result
    if not correction:
        assert outcomes.count('prepared')==1 and len(active)==1 and result['planned']==10,result
    elif 'reopened' in outcomes:
        assert not active and rec.approval_state=='draft',result
    else:
        assert len(active)==1 and rec.approval_state=='approved',result
    return result

results={'duplicate_release_preparation':race(approved_receipt()),
         'release_preparation_vs_reinspection':race(approved_receipt(),correction=True)}
print('IQC_CONCURRENCY_RESULTS',json.dumps(results,ensure_ascii=False))
env.cr.rollback()
