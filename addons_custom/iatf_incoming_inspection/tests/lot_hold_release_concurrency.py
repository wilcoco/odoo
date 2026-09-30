"""Own isolated DB only. Commit named synthetic fixtures to test real RR conflicts."""
import json
import base64
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4
from psycopg2.errors import SerializationFailure
from odoo import api, Command, SUPERUSER_ID
from odoo.exceptions import UserError
from odoo.tests.common import new_test_user
from odoo.addons.iatf_incoming_inspection.tests.hold_release_fixture import make_policy, request_values

assert env.cr.dbname == 'cams_night_materials_jit_gate'
key = uuid4().hex[:10]
company = env['res.company'].create({'name':'SYNTHETIC LOT hold concurrency '+key})
ctx = {'allowed_company_ids':company.ids, 'mail_notify_force_send':False,
       'mail_create_nosubscribe':True, 'mail_notrack':True}
setup = env['res.users'].with_company(company).with_context(ctx).env
policy, quality, production = make_policy(setup, key)
stock = new_test_user(setup,login='hold_race_stock_'+key,groups='stock.group_stock_user',
    company_id=company.id,company_ids=[Command.set(company.ids)])
nc_user = new_test_user(setup,login='hold_race_nc_'+key,groups='iatf_nonconformity.group_nc_user',
    company_id=company.id,company_ids=[Command.set(company.ids)])
product = setup['product.product'].create({'name':'SYNTHETIC hold race material '+key,
    'company_id':company.id,'is_storable':True,'tracking':'lot'})
registry = env.registry
company_id, stock_uid, production_uid, nc_uid = company.id, stock.id, production.id, nc_user.id


def prepared(suffix):
    lot = setup['stock.lot'].create({'name':key+'-'+suffix,'company_id':company_id,'product_id':product.id,
        'quality_hold':True,'hold_reason':'SYNTHETIC initial hold'})
    attachment_id = False
    if suffix == 'nc_file_wins':
        pqc = setup['iatf.process.inspection'].create({'company_id':company_id,'product_id':product.id,
            'lot_id':lot.id,'inspection_stage':'final','result':'fail','quantity_produced':1,
            'quantity_inspected':1,'quantity_rejected':1,'line_ids':[Command.create({
                'characteristic_name':'Appearance','measured_value':'NG','result':'fail'})]})
        pqc.action_decide()
        nc = pqc.nonconformity_id
        attachment = setup['ir.attachment'].create({'name':'SYNTHETIC original source.txt',
            'res_model':nc._name,'res_id':nc.id,'company_id':company_id,
            'datas':base64.b64encode(b'SYNTHETIC original NC evidence')})
        nc.attachment_ids = [Command.link(attachment.id)]
        attachment_id = attachment.id
    rec = setup['iatf.lot.hold.release'].with_user(quality).create(request_values(lot))
    rec.action_submit_approval()
    rec.action_approve_approval()
    rec.with_user(production).action_approve_approval()
    return rec.id, lot.id, attachment_id, lot.hold_revision


cases = {name:prepared(name) for name in ('same_execution','new_hold_wins','nc_file_wins')}
env.cr.commit()


def run_case(name, rec_id, lot_id, attachment_id, initial_revision):
    barrier, changed = Barrier(2), Event()
    retries = []

    def worker(index):
        for attempt in range(3):
            with registry.cursor() as cr:
                actor = (stock_uid if name == 'new_hold_wins' and index == 0 else
                         nc_uid if name == 'nc_file_wins' and index == 0 else production_uid)
                e = api.Environment(cr, actor, dict(ctx))
                rec = e['iatf.lot.hold.release'].browse(rec_id)
                lot = e['stock.lot'].browse(lot_id)
                if name == 'nc_file_wins' and index == 0:
                    e['ir.attachment'].browse(attachment_id).read(['checksum'])
                else:
                    lot.read(['quality_hold','hold_revision'])
                    rec.read(['release_state'])
                if attempt == 0:
                    barrier.wait(timeout=10)
                try:
                    if name == 'new_hold_wins' and index == 0:
                        lot.write({'hold_reason':lot.hold_reason+'\nSYNTHETIC newly discovered reason'})
                        changed.set()
                        cr.commit()
                        return 'new_hold_recorded'
                    if name == 'nc_file_wins' and index == 0:
                        e['ir.attachment'].browse(attachment_id).write({'datas':base64.b64encode(b'SYNTHETIC modified NC evidence')})
                        changed.set()
                        cr.commit()
                        return 'nc_file_changed'
                    if name in ('new_hold_wins','nc_file_wins') and not changed.wait(10):
                        raise AssertionError('hold writer did not reach lock')
                    rec.action_release_hold()
                    cr.commit()
                    return 'executed_or_same_replay'
                except SerializationFailure:
                    retries.append(index)
                    cr.rollback()
                except UserError:
                    cr.rollback()
                    return 'stale_rejected'
        raise AssertionError('retry budget exhausted')

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker,index) for index in (0,1)]
        outcomes = [future.result(timeout=40) for future in futures]
    with registry.cursor() as cr:
        read = api.Environment(cr,SUPERUSER_ID,dict(ctx))
        rec = read['iatf.lot.hold.release'].browse(rec_id)
        lot = read['stock.lot'].browse(lot_id)
        result = {'outcomes':outcomes,'serialization_retries':len(retries),
            'release_id':rec_id,'lot_id':lot_id,'revision':lot.hold_revision,
            'held':lot.quality_hold,'release_state':rec.release_state,
            'executed_messages':len(rec.message_ids.filtered(lambda message:'명시 실행했습니다' in (message.body or '')))}
        assert retries, result
        assert lot.hold_revision == initial_revision + int(name != 'nc_file_wins'), result
        if name == 'same_execution':
            assert outcomes == ['executed_or_same_replay']*2, result
            assert rec.release_state == 'executed' and not lot.quality_hold, result
            assert result['executed_messages'] == 1, result
        elif name == 'new_hold_wins':
            assert outcomes == ['new_hold_recorded','stale_rejected'], result
            assert rec.release_state == 'draft' and lot.quality_hold and not rec.released_at, result
        else:
            assert outcomes == ['nc_file_changed','stale_rejected'], result
            assert rec.release_state == 'draft' and lot.quality_hold and not rec.released_at, result
        return result


results = {name:run_case(name,*ids) for name,ids in cases.items()}
env.cr.rollback()
print('LOT_HOLD_RELEASE_CONCURRENCY='+json.dumps({'company_id':company_id,'synthetic_key':key,
    'results':results,'fixture_policy':'Named synthetic approval records retained only in the isolated DB'},ensure_ascii=False))
