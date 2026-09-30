"""Execute via the isolated night_runtime shell; commits SYNTHETIC fixtures only."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from psycopg2.errors import SerializationFailure
from odoo import api, Command
from odoo.exceptions import UserError
from odoo.tests.common import new_test_user

assert env.cr.dbname == 'cams_night_tax_approval_guard', 'Only the assigned disposable DB'
ctx=dict(env.context, mail_notify_force_send=False, mail_create_nosubscribe=True)
group='base.group_user,iatf_shipping_inspection.group_shipping_inspection_user'
author=new_test_user(env, login='approval-concurrency-author', groups=group)
approver=new_test_user(env, login='approval-concurrency-approver', groups=group)
product=env['product.product'].create({'name':'SYNTHETIC approval concurrency'})
registry=env.registry
company_id=env.company.id


def new_document(repeated=False):
    lines=[Command.create({'sequence':10,'user_id':approver.id})]
    if repeated:
        lines.append(Command.create({'sequence':20,'user_id':approver.id}))
    doc=env['iatf.shipping.inspection'].with_context(ctx).with_user(author).create({
        'product_id':product.id, 'company_id':company_id, 'approval_line_ids':lines})
    doc.action_submit_approval()
    return doc


def race(doc, edit=False):
    request_id=doc.approval_request_id.id
    expected=doc.approval_current_line_id.id
    doc_id=doc.id
    env.cr.commit()  # Fixture harness only; business methods never commit.
    barrier=threading.Barrier(2)
    retries=[]

    def worker(index):
        for attempt in range(3):
            with registry.cursor() as cr:
                e=api.Environment(cr,author.id if edit and index else approver.id,
                    dict(ctx,allowed_company_ids=[company_id],approval_expected_line_id=expected))
                req=e['iatf.approval.request'].browse(request_id)
                req.read(['state','current_line_id'])  # Both use the pre-race snapshot.
                if attempt == 0:
                    barrier.wait(timeout=10)
                try:
                    if edit and index:
                        e['iatf.shipping.inspection'].browse(doc_id).write({'notes':'SYNTHETIC concurrent correction'})
                        outcome='edited'
                    else:
                        req.action_approve(expected_line_id=expected)
                        outcome='approved'
                    cr.commit()
                    return outcome
                except SerializationFailure:
                    cr.rollback()
                    retries.append(index)
                except UserError:
                    cr.rollback()
                    return 'stale_or_closed'
        raise AssertionError('Retry budget exceeded')

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,index) for index in (0,1)]
        outcomes=[future.result(timeout=30) for future in futures]
    env.cr.rollback()  # Fresh snapshot to inspect committed concurrent outcomes.
    env.invalidate_all()
    doc=env['iatf.shipping.inspection'].browse(doc_id)
    original=env['iatf.approval.request'].browse(request_id)
    result={'outcomes':outcomes,'serialization_retries':len(retries),
            'request_id':request_id,'target_id':doc_id,'document_state':doc.approval_state,
            'original_approved_lines':len(original.line_ids.filtered(lambda l:l.state=='approved'))}
    assert len(retries)>=1, result
    if edit:
        assert 'edited' in outcomes and doc.approval_state=='draft', result
        assert doc.approval_request_id.previous_request_id==original, result
    else:
        assert outcomes.count('approved')==1 and outcomes.count('stale_or_closed')==1, result
        assert result['original_approved_lines']==1, result
    return result

results={}
results['same_final_step']=race(new_document())
results['same_user_repeated_steps']=race(new_document(repeated=True))
assert results['same_user_repeated_steps']['document_state']=='in_progress', results
results['approval_vs_document_correction']=race(new_document(),edit=True)
print('APPROVAL_CONCURRENCY_RESULTS',json.dumps(results,ensure_ascii=False))
env.cr.rollback()
