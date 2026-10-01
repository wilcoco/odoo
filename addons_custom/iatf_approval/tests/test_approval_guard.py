"""Ordinary-user approval attacks and real shipping-document happy paths."""
from unittest.mock import patch
from unittest import SkipTest
from psycopg2.errors import SerializationFailure
from odoo import Command, fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestApprovalGuard(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'iatf.shipping.inspection' not in cls.env:
            raise SkipTest('Run with iatf_shipping_inspection for the real target ACL fixture')
        group = 'base.group_user,iatf_shipping_inspection.group_shipping_inspection_user'
        cls.author = new_test_user(cls.env, login='guard-author', groups=group)
        cls.approver = new_test_user(cls.env, login='guard-approver', groups=group)
        cls.second = new_test_user(cls.env, login='guard-second', groups=group)
        cls.outsider = new_test_user(cls.env, login='guard-outsider', groups='base.group_user')
        cls.product = cls.env['product.product'].create({'name': 'SYNTHETIC approval scope'})
        cls.company_b = cls.env['res.company'].create({'name':'SYNTHETIC other approval company'})

    def _document(self, two=False, **vals):
        values = {'product_id': self.product.id, 'company_id': self.env.company.id,
                  'approval_line_ids': [Command.create({'sequence':10, 'user_id':self.approver.id})]}
        if two:
            values['approval_line_ids'].append(Command.create({'sequence':20, 'user_id':self.second.id}))
        values.update(vals)
        return self.env['iatf.shipping.inspection'].with_user(self.author).create(values)

    def _approve(self, doc):
        doc.action_submit_approval()
        doc.with_user(self.approver).action_approve_approval()
        return doc.approval_request_id

    def test_normal_sequential_approval_and_duplicate_completion(self):
        doc = self._document(two=True)
        doc.action_submit_approval()
        request = doc.approval_request_id
        with self.assertRaises(UserError):
            doc.with_user(self.second).action_approve_approval()
        doc.with_user(self.approver).action_approve_approval()
        self.assertEqual(doc.approval_state, 'in_progress')
        with self.assertRaises(UserError):
            doc.with_user(self.approver).action_approve_approval()
        doc.with_user(self.second).action_approve_approval()
        self.assertEqual(doc.approval_state, 'approved')
        self.assertTrue(request.approved_date)
        before = request.line_ids.mapped('action_date')
        with self.assertRaises(UserError):
            doc.with_user(self.second).action_approve_approval()
        self.assertEqual(before, request.line_ids.mapped('action_date'))
        doc._approval_check_approved()

    def test_direct_request_and_context_forgery_blocked(self):
        doc = self._document()
        req = doc.approval_request_id
        for vals in [{'state':'approved'}, {'approved_date':fields.Datetime.now()},
                     {'requester_id':self.approver.id}, {'res_id':doc.id+1},
                     {'current_line_id':req.line_ids.id}, {'guard_version':1}]:
            with self.assertRaises(UserError), self.cr.savepoint():
                req.with_context(_iatf_approval_service=True).write(vals)
        with self.assertRaises(UserError):
            self.env['iatf.approval.request'].with_user(self.author).with_context(
                default_state='approved').create({'res_model':doc._name,'res_id':doc.id})
        self.assertEqual(req.state, 'draft')

    def test_target_link_and_related_state_cannot_be_replaced(self):
        doc, other = self._document(), self._document()
        self._approve(other)
        for vals in [{'approval_request_id':other.approval_request_id.id}, {'approval_request_id':False},
                     {'approval_state':'approved'}, {'approval_current_approver_id':self.author.id}]:
            with self.assertRaises(UserError):
                doc.write(vals)
        for defaults in [{'default_approval_request_id':other.approval_request_id.id},
                         {'default_approval_state':'approved'}]:
            with self.assertRaises(UserError):
                self.env[doc._name].with_user(self.author).with_context(**defaults).create({'product_id':self.product.id})
        self.assertEqual(doc.approval_state, 'draft')

    def test_no_target_access_cannot_read_write_or_approve_request(self):
        doc = self._document()
        doc.action_submit_approval()
        request = doc.approval_request_id.with_user(self.outsider)
        self.assertFalse(doc.with_user(self.outsider).has_access('write'))
        self.assertFalse(request.has_access('read'))
        with self.assertRaises(AccessError):
            request.read(['state'])
        with self.assertRaises(AccessError):
            request.action_approve()
        self.assertFalse(request.search([('id','=',request.id)]))
        self.assertFalse(self.env['iatf.approval.line'].with_user(self.outsider).search([('request_id','=',request.id)]))

    def test_target_record_write_rule_is_enforced_even_for_current_approver(self):
        doc = self._document()
        doc.action_submit_approval()
        self.env['ir.rule'].create({'name':'SYNTHETIC deny target write',
            'model_id':self.env['ir.model']._get_id(doc._name), 'domain_force':str([('id','!=',doc.id)]),
            'perm_read':False, 'perm_write':True, 'perm_create':False, 'perm_unlink':False})
        with self.assertRaises(AccessError):
            doc.approval_request_id.with_user(self.approver).action_approve()
        self.assertEqual(doc.approval_state, 'in_progress')

    def test_other_company_requests_and_lines_hidden(self):
        doc = self.env['iatf.shipping.inspection'].with_company(self.company_b).create({
            'product_id':self.product.id, 'company_id':self.company_b.id})
        request = doc.approval_request_id.with_user(self.author).with_context(allowed_company_ids=[self.env.company.id])
        with self.assertRaises(AccessError):
            request.read(['state'])
        self.assertFalse(request.search([('id','=',request.id)]))
        with self.assertRaises(AccessError):
            request.action_submit()
        with self.assertRaises(AccessError):
            self._document(company_id=self.company_b.id)

    def test_approver_needs_target_write_and_company_membership(self):
        doc = self._document(approval_line_ids=[Command.create({'user_id':self.outsider.id})])
        with self.assertRaises(AccessError):
            doc.action_submit_approval()
        self.assertEqual(doc.approval_state, 'draft')
        other_user = new_test_user(self.env, login='guard-other-company',
            groups='base.group_user,iatf_shipping_inspection.group_shipping_inspection_user',
            company_id=self.company_b.id, company_ids=[Command.set(self.company_b.ids)])
        doc.approval_line_ids.write({'user_id':other_user.id})
        with self.assertRaises(UserError):
            doc.action_submit_approval()

    def test_lines_cannot_forge_result_by_create_defaults_or_commands(self):
        doc = self._document()
        line = doc.approval_line_ids
        for vals in [{'state':'approved'}, {'action_date':fields.Datetime.now()}, {'request_id':line.request_id.id}]:
            with self.assertRaises(UserError):
                line.write(vals)
        with self.assertRaises(UserError):
            self.env['iatf.approval.line'].with_user(self.author).with_context(
                default_state='approved', default_request_id=line.request_id.id).create({'user_id':self.approver.id})
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.write({'approval_line_ids':[Command.update(line.id, {'state':'approved'})]})
        with self.assertRaises(UserError), self.cr.savepoint():
            self._document(approval_line_ids=[Command.create({'user_id':self.approver.id,'state':'approved'})])
        self.assertEqual(line.state,'new')

    def test_submitted_lines_cannot_change_or_move_or_delete(self):
        doc = self._document()
        other = self._document()
        doc.action_submit_approval()
        for action in [lambda: doc.approval_line_ids.write({'user_id':self.author.id}),
                       lambda: doc.approval_line_ids.write({'sequence':999}),
                       doc.approval_line_ids.unlink,
                       lambda: doc.write({'approval_line_ids':[Command.clear()]}),
                       lambda: other.write({'approval_line_ids':[Command.link(doc.approval_line_ids.id)]})]:
            with self.assertRaises(UserError), self.cr.savepoint():
                action()
        self.assertEqual(doc.approval_state,'in_progress')

    def test_draft_line_editing_still_works(self):
        doc = self._document(two=True)
        doc.write({'approval_line_ids':[Command.delete(doc.approval_line_ids[-1].id)]})
        doc.approval_line_ids.write({'sequence':5, 'user_id':self.second.id})
        self.assertEqual(len(doc.approval_line_ids),1)
        doc.action_submit_approval()
        doc.with_user(self.second).action_approve_approval()
        self.assertEqual(doc.approval_state,'approved')

    def test_approved_edit_preserves_previous_evidence_and_resets_link(self):
        doc = self._document()
        previous = self._approve(doc)
        date = previous.approved_date
        doc.write({'notes':'corrected source facts'})
        self.assertNotEqual(doc.approval_request_id, previous)
        self.assertEqual(doc.approval_state,'draft')
        self.assertEqual(doc.approval_request_id.previous_request_id,previous)
        self.assertEqual(previous.state,'approved')
        self.assertEqual(previous.approved_date,date)
        self.assertEqual(previous.line_ids.state,'approved')
        with self.assertRaises(UserError):
            previous.action_submit()
        with self.assertRaises(UserError):
            previous.line_ids.write({'note':'rewrite history'})
        with self.assertRaises(UserError):
            previous.sudo().unlink()

    def test_in_progress_document_change_cannot_reuse_partial_approval(self):
        doc = self._document(two=True)
        doc.action_submit_approval()
        doc.with_user(self.approver).action_approve_approval()
        previous=doc.approval_request_id
        doc.write({'notes':'material correction during approval'})
        self.assertEqual(doc.approval_state,'draft')
        self.assertEqual(previous.line_ids[0].state,'approved')
        with self.assertRaises(UserError):
            previous.with_user(self.second).action_approve()

    def test_rejected_resubmission_keeps_reason_and_creates_new_request(self):
        doc = self._document()
        doc.action_submit_approval()
        previous=doc.approval_request_id
        previous.with_user(self.approver).action_reject(reason='SYNTHETIC rejection reason')
        doc.action_submit_approval()
        self.assertNotEqual(doc.approval_request_id,previous)
        self.assertEqual(previous.state,'rejected')
        self.assertEqual(previous.line_ids.note,'SYNTHETIC rejection reason')
        doc.with_user(self.approver).action_approve_approval()
        self.assertEqual(doc.approval_state,'approved')

    def test_legacy_approval_is_preserved_but_cannot_authorize_execution(self):
        doc = self._document()
        previous=self._approve(doc)
        # Simulate a pre-upgrade row; never an ordinary-user API path.
        self.cr.execute('UPDATE iatf_approval_request SET guard_version = 0 WHERE id = %s',[previous.id])
        previous.invalidate_recordset(['guard_version'])
        previous.modified(['guard_version'])
        self.assertEqual(previous.state,'approved')
        self.assertEqual(doc.approval_state,'draft')
        with self.assertRaises(UserError):
            doc._approval_check_approved()
        doc.action_submit_approval()
        self.assertNotEqual(doc.approval_request_id,previous)
        self.assertEqual(previous.state,'approved')
        self.assertEqual(doc.approval_state,'in_progress')

    def test_late_failure_rolls_back_approval_date_line_and_activity_changes(self):
        doc=self._document()
        doc.action_submit_approval()
        with self.assertRaises(UserError), self.cr.savepoint():
            doc.with_user(self.approver).action_approve_approval()
            raise UserError('failure after approval')
        self.assertEqual(doc.approval_state,'in_progress')
        self.assertFalse(doc.approval_request_id.approved_date)
        self.assertEqual(doc.approval_line_ids.state,'pending')

    def test_serialization_failure_propagates_for_full_request_retry(self):
        doc=self._document()
        doc.action_submit_approval()
        with self.assertRaises(SerializationFailure), self.cr.savepoint(), patch.object(
                type(doc.approval_request_id),'_lock_workflow',side_effect=SerializationFailure('40001')):
            doc.with_user(self.approver).action_approve_approval()
        self.assertEqual(doc.approval_state,'in_progress')

    def test_read_only_shipping_actor_can_verify_but_not_change_approval(self):
        doc=self._document()
        self._approve(doc)
        self.env['ir.model.access'].create({
            'name':'SYNTHETIC shipping evidence reader',
            'model_id':self.env['ir.model']._get_id(doc._name),
            'group_id':self.env.ref('base.group_user').id,
            'perm_read':True, 'perm_write':False, 'perm_create':False, 'perm_unlink':False})
        reader_doc=doc.with_user(self.outsider)
        self.assertTrue(reader_doc.has_access('read'))
        self.assertFalse(reader_doc.has_access('write'))
        reader_doc._approval_check_approved('customer shipment')
        with self.assertRaises(AccessError):
            reader_doc.action_reset_approval()

    def test_forged_defaults_cannot_enter_internal_reset_line_creation(self):
        doc=self._document()
        previous=self._approve(doc)
        doc.with_context(default_state='approved', default_action_date=fields.Datetime.now(),
                         default_previous_request_id=999999,
                         default_line_ids=[Command.create({'user_id':self.author.id,'state':'approved'})]).action_reset_approval()
        self.assertEqual(doc.approval_state,'draft')
        self.assertEqual(doc.approval_request_id.previous_request_id,previous)
        self.assertEqual(len(doc.approval_line_ids),1)
        self.assertEqual(doc.approval_line_ids.state,'new')
        self.assertFalse(doc.approval_line_ids.action_date)

    def test_same_approver_two_steps_requires_displayed_step_and_rejects_retry(self):
        doc=self._document(approval_line_ids=[
            Command.create({'sequence':10, 'user_id':self.approver.id}),
            Command.create({'sequence':20, 'user_id':self.approver.id})])
        doc.action_submit_approval()
        request=doc.approval_request_id.with_user(self.approver)
        displayed_step=request.current_line_id.id
        with self.assertRaises(UserError):
            request.action_approve()
        request.action_approve(expected_line_id=displayed_step)
        self.assertEqual(doc.approval_state,'in_progress')
        with self.assertRaises(UserError):
            request.action_approve(expected_line_id=displayed_step)
        request.action_approve(expected_line_id=request.current_line_id.id)
        self.assertEqual(doc.approval_state,'approved')

    def test_public_form_sends_browser_displayed_step_in_button_context(self):
        from lxml import etree
        doc=self._document()
        arch=etree.fromstring(doc.get_view(view_type='form')['arch'])
        buttons=arch.xpath("//button[@name='action_approve_approval']")
        self.assertTrue(buttons)
        self.assertTrue(arch.xpath("//field[@name='approval_current_line_id']"))
        self.assertEqual(buttons[0].get('context'),
                         "{'approval_expected_line_id': approval_current_line_id}")
        doc.action_submit_approval()
        displayed_step=doc.approval_current_line_id.id
        doc.with_user(self.approver).with_context(approval_expected_line_id=displayed_step).action_approve_approval()
        self.assertEqual(doc.approval_state,'approved')

    def test_settlement_rejected_revision_preserves_both_service_tokens(self):
        if 'vendor.mrp.accrual' not in self.env:
            self.skipTest('Run with gh_vendor_settlement for adjustment compatibility')
        # This tests rejection/revision compatibility, so isolate its period
        # from previously closed periods in the shared synthetic factory DB.
        company=self.env['res.company'].create({'name':'SYNTHETIC approval revision company'})
        accountant=new_test_user(self.env, login='guard-adjustment-accountant',
                                groups='base.group_user,account.group_account_user',
                                company_id=company.id, company_ids=[Command.set(company.ids)])
        approver=new_test_user(self.env, login='guard-adjustment-approver',
                              groups='base.group_user,account.group_account_user',
                              company_id=company.id, company_ids=[Command.set(company.ids)])
        mo=self.env['mrp.production'].with_company(company).create({'product_id':self.product.id, 'product_qty':1,
                                            'product_uom_id':self.product.uom_id.id})
        partner=self.env['res.partner'].create({'name':'SYNTHETIC adjustment vendor'})
        doc=self.env['vendor.mrp.accrual'].with_user(accountant).with_context(allowed_company_ids=company.ids).create({
            'date':'2026-09-10','production_id':mo.id,'product_id':self.product.id,
            'vendor_id':partner.id,'uom_id':self.product.uom_id.id,'qty':-1,'cost':10,
            'adjustment_reason':'scrap','reason':'SYNTHETIC correction',
            'approval_line_ids':[Command.create({'user_id':approver.id})]})
        doc.action_submit_approval()
        previous=doc.approval_request_id
        previous.with_user(approver).action_reject(reason='needs review')
        doc.action_submit_approval()
        self.assertNotEqual(doc.approval_request_id,previous)
        self.assertEqual(previous.state,'rejected')
        self.assertEqual(doc.approval_request_id.previous_request_id,previous)
        doc.with_user(approver).action_approve_approval()
        self.assertEqual(doc.approval_state,'approved')

    def test_migration_scopes_legacy_company_without_certifying_evidence(self):
        import importlib.util
        from pathlib import Path
        path=Path(__file__).parents[1] / 'migrations/18.0.1.2.0/post-migrate.py'
        spec=importlib.util.spec_from_file_location('approval_guard_migration',path)
        migration=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        doc=self._document()
        previous=self._approve(doc)
        approved_date=previous.approved_date
        self.cr.execute('UPDATE iatf_approval_request SET guard_version = 0, company_id = NULL WHERE id = %s',[previous.id])
        migration.migrate(self.cr,'18.0.1.1.0')
        previous.invalidate_recordset()
        self.assertEqual(previous.company_id,self.env.company)
        self.assertEqual(previous.guard_version,0)
        self.assertEqual(previous.state,'approved')
        self.assertEqual(previous.approved_date,approved_date)
        self.assertEqual(doc.approval_state,'draft')
