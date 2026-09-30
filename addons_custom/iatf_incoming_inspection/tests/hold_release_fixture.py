"""Synthetic two-person approval helpers, never a production bypass."""
import base64
from odoo import Command
from odoo.tests.common import new_test_user


def make_policy(env, suffix):
    company = env.company
    quiet = env['res.users'].with_context(no_reset_password=True, mail_create_nosubscribe=True, mail_notrack=True).env
    users = []
    for role in ('quality', 'production'):
        users.append(new_test_user(quiet, login='hold_' + suffix + '_' + role,
            groups='iatf_incoming_inspection.group_lot_hold_' + role,
            company_id=company.id, company_ids=[Command.set(company.ids)]))
    values = {'company_id': company.id, 'quality_user_id': users[0].id,
              'production_user_id': users[1].id}
    policy = env['iatf.lot.hold.policy'].search([('company_id', '=', company.id)])
    # TransactionCase가 원 설정을 롤백한다. 기존 회사별 유일 정책을 중복 생성하지 않는다.
    if policy:
        policy.write(values)
    else:
        policy = env['iatf.lot.hold.policy'].create(values)
    return policy, users[0], users[1]


def request_values(lot):
    return {'company_id':lot.company_id.id, 'lot_id':lot.id,
        'reason':'합성 재검사에 따른 전체 LOT 일반 해제',
        'evidence_note':'합성 전수 재검사와 모든 보류 사유를 확인함. 고객/수량 한정 특채 아님.',
        'evidence_file':base64.b64encode(b'SYNTHETIC ONLY: whole LOT retest evidence'),
        'evidence_filename':'synthetic-retest.txt', 'all_causes_reviewed':True}


def approve_and_release(env, lot, quality, production):
    rec = env['iatf.lot.hold.release'].with_user(quality).create(request_values(lot))
    rec.action_submit_approval()
    rec.action_approve_approval()
    rec.with_user(production).action_approve_approval()
    rec.with_user(production).action_release_hold()
    return rec
