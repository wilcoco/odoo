import base64
from odoo import Command
from odoo.tests.common import TransactionCase, tagged, new_test_user
from odoo.exceptions import AccessError, UserError
from .hold_release_fixture import make_policy, request_values


@tagged('post_install', '-at_install')
class TestLotHoldRelease(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.policy, cls.quality, cls.production = make_policy(cls.env, 'release')
        cls.stock = new_test_user(cls.env, login='hold_release_stock', groups='stock.group_stock_user',
            company_id=cls.company.id, company_ids=[Command.set(cls.company.ids)])
        cls.product = cls.env['product.product'].create({'name':'Held ordinary test material', 'is_storable':True, 'tracking':'lot'})
        cls.location = cls.env['stock.warehouse'].search([('company_id','=',cls.company.id)], limit=1).lot_stock_id

    def setUp(self):
        super().setUp()
        self.lot = self.env['stock.lot'].create({'name':self._testMethodName, 'product_id':self.product.id,
            'company_id':self.company.id, 'quality_hold':True, 'hold_reason':'Original independent hold'})
        self.env['stock.quant']._update_available_quantity(self.product, self.location, 10, lot_id=self.lot)

    def _request(self):
        return self.env['iatf.lot.hold.release'].with_user(self.stock).create(request_values(self.lot))

    def _approved(self):
        rec = self._request()
        rec.action_submit_approval()
        rec.with_user(self.quality).action_approve_approval()
        rec.with_user(self.production).action_approve_approval()
        return rec

    def _deny(self, callback, exception=UserError):
        with self.assertRaises(exception), self.env.cr.savepoint():
            callback()

    def test_two_stages_then_explicit_release_only(self):
        rec = self._request()
        before = self.env['stock.quant'].search([('lot_id','=',self.lot.id)]).read(['quantity','reserved_quantity','location_id','owner_id','package_id'])
        rec.action_submit_approval()
        self._deny(lambda:rec.with_user(self.production).action_approve_approval())
        rec.with_user(self.quality).action_approve_approval()
        self.assertEqual(rec.approval_state, 'in_progress')
        self._deny(lambda:rec.with_user(self.production).action_release_hold())
        self.assertTrue(self.lot.quality_hold)
        rec.with_user(self.production).action_approve_approval()
        self.assertTrue(self.lot.quality_hold)
        self._deny(lambda:rec.with_user(self.quality).action_release_hold(), AccessError)
        rec.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)
        self.assertEqual(rec.release_state, 'executed')
        self.assertEqual(rec.released_by, self.production)
        self.assertEqual(before, self.env['stock.quant'].search([('lot_id','=',self.lot.id)]).read(['quantity','reserved_quantity','location_id','owner_id','package_id']))
        rec.with_user(self.production).action_release_hold()
        self.assertEqual(self.lot.hold_revision, 1)

    def test_direct_false_and_reason_bypass(self):
        for lot in (self.lot.with_user(self.stock), self.lot.sudo(), self.lot.with_context(_lot_hold_release_service=True)):
            self._deny(lambda:lot.write({'quality_hold':False}))
            self._deny(lambda:lot.write({'hold_reason':'fabricated replacement'}))
        self.assertTrue(self.lot.quality_hold)
        self.lot.with_user(self.stock).write({'hold_reason':self.lot.hold_reason+'\nAdditional safety hold'})
        self.assertEqual(self.lot.hold_revision, 1)

    def test_default_create_and_write_forgery(self):
        vals = request_values(self.lot)
        for field, value in [('release_state','executed'),('released_at','2026-09-11 01:00:00'),
                             ('released_by',self.stock.id),('release_snapshot',{'forged':True})]:
            self._deny(lambda:self.env['iatf.lot.hold.release'].create(dict(vals, **{field:value})))
            self._deny(lambda:self.env['iatf.lot.hold.release'].with_context(**{'default_'+field:value}).create(vals))
        rec = self._request()
        self._deny(lambda:rec.write({'release_state':'executed'}))
        self._deny(lambda:self.lot.write({'hold_revision':0}))
        self._deny(lambda:self.env['stock.lot'].with_context(default_hold_revision=0).create({
            'name':'forged lot','product_id':self.product.id,'company_id':self.company.id}))

    def test_direct_request_api_needs_snapshot(self):
        rec = self._request()
        rec.approval_request_id.write({'line_ids':[Command.create({'sequence':10,'user_id':self.stock.id})]})
        self._deny(lambda:rec.approval_request_id.action_submit())
        self._deny(lambda:rec.with_user(self.production).action_release_hold())

    def test_evidence_and_request_immutable_after_submit(self):
        rec = self._approved()
        for vals in ({'evidence_file':base64.b64encode(b'changed')}, {'evidence_filename':'changed.txt'},
                     {'evidence_note':'changed'}, {'all_causes_reviewed':False}, {'reason':'changed'}):
            self._deny(lambda:rec.write(vals))
        self._deny(lambda:rec.approval_line_ids[:1].write({'user_id':self.stock.id}))
        self._deny(lambda:rec.approval_request_id.write({'line_ids':[Command.clear()]}))
        self._deny(lambda:rec.copy())
        self.assertTrue(self.lot.quality_hold)

    def test_new_hold_reason_invalidates_previous_approval(self):
        rec = self._approved()
        self.lot.with_user(self.stock).write({'hold_reason':self.lot.hold_reason+'\nNew safety evidence'})
        self._deny(lambda:rec.with_user(self.production).action_release_hold())
        new = self._approved()
        new.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)
        self.lot.with_user(self.stock).write({'quality_hold':True,'hold_reason':'New hold after release'})
        self._deny(lambda:new.with_user(self.production).action_release_hold())
        self.assertTrue(self.lot.quality_hold)

    def test_two_requests_cannot_release_twice(self):
        first, second = self._approved(), self._approved()
        first.with_user(self.production).action_release_hold()
        self._deny(lambda:second.with_user(self.production).action_release_hold())
        self.assertFalse(second.released_at)

    def test_policy_scope_and_distinct_users(self):
        self._deny(lambda:self.policy.with_user(self.stock).write({'quality_user_id':self.stock.id}), AccessError)
        self._deny(lambda:self.policy.write({'production_user_id':self.quality.id}))
        rec = self._approved()
        other = new_test_user(self.env, login='hold_other_production',
            groups='iatf_incoming_inspection.group_lot_hold_production', company_id=self.company.id,
            company_ids=[Command.set(self.company.ids)])
        self.policy.write({'production_user_id':other.id})
        self._deny(lambda:rec.with_user(other).action_release_hold())

    def test_wrong_company_and_lot_identity(self):
        other = self.env['res.company'].create({'name':'Other hold company'})
        self._deny(lambda:self.env['iatf.lot.hold.release'].with_user(self.stock).create(
            dict(request_values(self.lot),company_id=other.id)), AccessError)
        for vals in ({'company_id':other.id},{'name':'relabelled held lot'},{'product_id':False}):
            self._deny(lambda:self.lot.write(vals))

    def test_multicompany_requester_does_not_expand_approver_companies(self):
        other = self.env['res.company'].create({'name':'Caller second company'})
        self.stock.company_ids = self.company | other
        model = self.env['iatf.lot.hold.release'].with_user(self.stock).with_context(allowed_company_ids=[other.id,self.company.id])
        original_context = dict(model.env.context)
        rec = model.create(request_values(self.lot))
        rec.action_submit_approval()
        self.assertEqual(dict(model.env.context), original_context)
        self.assertEqual(self.quality.company_ids, self.company)
        self.assertEqual(self.production.company_ids, self.company)
        rec.with_user(self.quality).with_context(allowed_company_ids=self.company.ids).approval_request_id.action_approve()
        rec.with_user(self.production).with_context(allowed_company_ids=self.company.ids).approval_request_id.action_approve()
        rec.with_user(self.production).with_context(allowed_company_ids=self.company.ids).action_release_hold()
        self.assertFalse(self.lot.quality_hold)

    def test_missing_file_and_legacy_hold_remain_blocked(self):
        self.assertEqual(self.lot.hold_revision,0)
        self.assertTrue(self.lot.quality_hold)
        vals = request_values(self.lot)
        vals['evidence_file'] = False
        rec = self.env['iatf.lot.hold.release'].create(vals)
        self._deny(lambda:rec.action_submit_approval())
        self.assertTrue(self.lot.quality_hold)
        self.assertFalse(rec.release_snapshot)

    def test_normal_false_lot_and_negative_unreserve(self):
        normal = self.env['stock.lot'].with_user(self.stock).create({'name':'ordinary new false',
            'product_id':self.product.id,'company_id':self.company.id})
        self.assertFalse(normal.quality_hold)
        normal.write({'name':'ordinary edited'})
        quant = self.env['stock.quant'].search([('lot_id','=',self.lot.id)])
        quant.reserved_quantity = 2
        self.env['stock.quant']._update_reserved_quantity(self.product,self.location,-2,lot_id=self.lot)
        self.assertFalse(quant.reserved_quantity)

    def test_executed_evidence_cannot_reset_or_relink(self):
        rec = self._approved()
        rec.with_user(self.production).action_release_hold()
        self._deny(lambda:rec.action_reset_approval())
        self._deny(lambda:rec.sudo().write({'evidence_note':'alter old result'}))
        self._deny(lambda:rec.sudo().unlink())

    def _automatic_hold(self, disposition='sort'):
        pqc = self.env['iatf.process.inspection'].create({
            'company_id':self.company.id, 'product_id':self.product.id, 'lot_id':self.lot.id,
            'inspection_stage':'final', 'quantity_produced':10, 'quantity_inspected':10,
            'quantity_accepted':0, 'quantity_rejected':10, 'result':'fail',
            'line_ids':[Command.create({'characteristic_name':'Appearance', 'measured_value':'NG', 'result':'fail'})]})
        pqc.action_decide()
        self.assertTrue(self.lot.hold_source_data)
        if disposition:
            # [아스트라 20260912 04:27] PQC 도 **미정 처분이면 해제 거부**가 되었다.
            # 증빙 결속을 보는 시험들은 처분을 **정상 절차대로 정해** 두고 본다.
            # 미정 거부 자체는 `test_an_undecided_pqc_disposition_blocks_release`
            # 가 따로 본다.
            pqc.nonconformity_id.write({'disposition': disposition})
        return pqc

    def test_an_undecided_pqc_disposition_blocks_release(self):
        """[아스트라 20260912 04:27] 「PQC 도 미정처분/폐기/반품/특채→전체가용
        해제 거부를 같은 절차에서 검증하도록 보완하십시오.」"""
        pqc = self._automatic_hold(disposition=False)
        self.assertFalse(pqc.nonconformity_id.disposition)
        rec = self._request()
        self._deny(lambda: rec.action_submit_approval())
        self.assertTrue(self.lot.quality_hold)
        self.assertFalse(rec.release_snapshot)

    def test_a_scrap_or_supplier_return_pqc_is_not_full_lot_release(self):
        """폐기·공급사 반품은 실물이 남지 않거나 넘어간다. 전체 가용 해제가 아니다."""
        for disposition in ('scrap', 'return'):
            with self.subTest(disposition=disposition), self.env.cr.savepoint():
                pqc = self._automatic_hold(disposition=disposition)
                rec = self._request()
                self._deny(lambda: rec.action_submit_approval())
                self.assertTrue(self.lot.quality_hold)

    def test_a_sorted_pqc_lot_still_releases_normally(self):
        """정상 재검사·선별 처분은 **그대로 해제된다** — 반례를 없애지 않는다."""
        self._automatic_hold(disposition='sort')
        rec = self._approved()
        rec.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)
        self.assertEqual(rec.release_state, 'executed')

    def test_known_customer_concession_is_not_full_lot_release(self):
        pqc = self._automatic_hold(disposition=False)
        pqc.nonconformity_id.write({'disposition':'concession'})
        rec = self._request()
        self._deny(lambda:rec.action_submit_approval())
        self.assertTrue(self.lot.quality_hold)
        self.assertFalse(rec.release_snapshot)

    def test_automatic_hold_source_changes_invalidate_approval(self):
        pqc = self._automatic_hold()
        rec = self._approved()
        pqc.nonconformity_id.write({'verification_result':'Changed after approval in the same transaction'})
        self._deny(lambda:rec.with_user(self.production).action_release_hold())
        self.assertTrue(self.lot.quality_hold)
        new = self._approved()
        new.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)

    def test_nc_attachment_contents_and_metadata_are_bound(self):
        pqc = self._automatic_hold()
        nc = pqc.nonconformity_id
        attachment = self.env['ir.attachment'].create({'name':'Synthetic NC retest.txt',
            'res_model':nc._name, 'res_id':nc.id, 'datas':base64.b64encode(b'original NC evidence'),
            'company_id':self.company.id})
        nc.attachment_ids = [Command.link(attachment.id)]
        rec = self._approved()
        old_nc_date = nc.write_date
        attachment.write({'datas':base64.b64encode(b'changed NC evidence')})
        self.assertEqual(nc.write_date,old_nc_date)
        self._deny(lambda:rec.with_user(self.production).action_release_hold())
        new = self._approved()
        attachment.write({'name':'changed filename.txt'})
        self._deny(lambda:new.with_user(self.production).action_release_hold())
        latest = self._approved()
        latest.with_user(self.production).action_release_hold()
        self.assertFalse(self.lot.quality_hold)
