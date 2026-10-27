from odoo import Command,fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestJigEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-jig-author',groups='iatf_jig.group_jig_user,iatf_document_control.group_document_user')
        cls.manager=new_test_user(cls.env,login='p1-jig-manager',groups='iatf_jig.group_jig_manager,iatf_document_control.group_document_manager')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC jig part'})
        cls.jig=cls.env['iatf.jig'].with_user(cls.author).create({'name':'SYNTHETIC jig','code':'P1-JIG','product_id':cls.product.id})
        category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC jig standard','code':'P1-JIG'})
        cls.standard=cls.env['iatf.document'].with_user(cls.author).create({'name':'SYNTHETIC jig criterion',
            'category_id':category.id,'quality_evidence_kind':'jig_standard','quality_product_ids':[Command.set(cls.product.ids)],
            'quality_jig_method':'SYNTHETIC monthly visual five points','reviewer_id':cls.manager.id,'approver_id':cls.manager.id})
        cls.standard.action_submit_review();cls.standard.with_user(cls.manager).action_approve()

    def _check(self,**values):
        vals={'jig_id':self.jig.id,'record_type':'daily','status':'normal','standard_document_id':self.standard.id,
            'trace_exception':'SYNTHETIC monthly bench check between production LOTs',
            'cleanliness':'ok','seating':'ok','shape':'ok','surface':'ok','bolts':'ok',
            'approval_line_ids':[Command.create({'user_id':self.manager.id})]}
        vals.update(values)
        return self.env['iatf.jig.record'].with_user(self.author).create(vals)
    def _complete(self,check):
        check.action_submit_approval();check.with_user(self.manager).action_approve_approval();check.action_complete_evidence()

    def test_five_visual_checks_and_immutable_record(self):
        check=self._check(bolts=False)
        with self.assertRaises(UserError):check.action_submit_approval()
        check.bolts='ok';self._complete(check)
        with self.assertRaises(UserError):check.write({'bolts':'ng'})
        with self.assertRaises(UserError):check.with_user(self.manager).unlink()
        self.assertEqual(check.completion_snapshot['values']['bolts'],'ok')

    def test_ng_blocks_use_and_only_fresh_approved_verification_releases(self):
        old=self._check(record_type='verification');self._complete(old)
        check=self._check(bolts='ng',status='repair',remarks='SYNTHETIC replace loose bolt')
        self._complete(check)
        self.assertTrue(self.jig.use_blocked)
        self.assertEqual(self.jig.state,'inactive')
        with self.assertRaises(UserError):self.jig.action_activate()
        with self.assertRaises(UserError):self.jig.with_context(_iatf_jig_disposition=True).write({'use_blocked':False})
        self.jig.release_candidate_id=old
        with self.assertRaises(UserError):self.jig.with_user(self.manager).action_release_verified()
        fresh=self._check(record_type='verification');self._complete(fresh)
        self.jig.release_candidate_id=fresh
        self.jig.with_user(self.manager).action_release_verified()
        self.assertFalse(self.jig.use_blocked)
        self.assertEqual(self.jig.released_record_id,fresh)
        self.assertEqual(self.jig.blocked_record_id,check)

    def test_false_normal_and_wrong_product_rejected(self):
        check=self._check(surface='ng')
        with self.assertRaises(UserError):check.action_submit_approval()
        other=self.env['product.product'].create({'name':'SYNTHETIC other jig product'})
        check.write({'surface':'ok','product_id':other.id})
        with self.assertRaises(UserError):check.action_submit_approval()
