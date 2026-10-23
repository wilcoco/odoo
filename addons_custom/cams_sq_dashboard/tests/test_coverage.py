from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged
from odoo.addons.iatf_incoming_inspection.models.iqc_service import service
from odoo.addons.iatf_incoming_inspection.tests import test_iqc_gate as iqc_workflow


@tagged('post_install', '-at_install')
class TestSqCoverage(TransactionCase):
    # Reuse the actual stock/quality workflow helpers, not synthetic decision flags.
    _receipt = iqc_workflow.TestIqcGate._receipt
    _approve = iqc_workflow.TestIqcGate._approve

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.wh = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.supplier = cls.env['res.partner'].create({'name': '[TEST] receipt coverage', 'supplier_rank': 1})
        cls.sloc = cls.env.ref('stock.stock_location_suppliers')
        cls.unit = cls.env.ref('uom.product_uom_unit')
        cls.product = cls.env['product.product'].create({'name': '[TEST] coverage product', 'is_storable': True})
        cls.stock = new_test_user(cls.env, login='sq.coverage.stock', groups='stock.group_stock_user')
        cls.quality = new_test_user(cls.env, login='sq.coverage.quality', groups='iatf_incoming_inspection.group_incoming_inspection_user')
        cls.quality_approver = new_test_user(cls.env, login='sq.coverage.approver',
            groups='iatf_incoming_inspection.group_incoming_inspection_user,iatf_document_control.group_document_user')
        cls.reader = new_test_user(cls.env, login='sq.coverage.reader', groups='cams_sq.group_sq_manager,cams_quality_access.group_sq_source_reader')
        cls.dash = cls.env['iatf.sq.dashboard']
        cls.today = fields.Date.context_today(cls.env.user)

    def status(self, iqc):
        iqc.receipt_move_line_id.invalidate_recordset(['sq_iqc_status'])
        return iqc.receipt_move_line_id.sq_iqc_status

    def test_receipt_decision_approval_and_rejection_are_distinct(self):
        iqc = self._receipt()
        self.assertEqual(self.status(iqc), 'pending')
        original = type(iqc).action_submit_approval
        def check_pending_approval(record):
            self.assertEqual(self.status(record), 'approval')
            return original(record)
        with patch.object(type(iqc), 'action_submit_approval', autospec=True, side_effect=check_pending_approval):
            self._approve(iqc)
        self.assertEqual(self.status(iqc), 'decided')
        # Approval is an independent requirement, even when a decision exists.
        rejected = self._approve(self._receipt(), accepted=0, rejected=10)
        self.assertEqual(self.status(rejected), 'decided')
        self.assertEqual(rejected.result, 'fail')
        self.assertEqual(iqc.quantity_released, 0)  # Dashboard does not release inventory.

    def test_partial_receipt_is_not_completed_coverage(self):
        iqc = self._approve(self._receipt(), accepted=4)
        self.assertEqual(self.status(iqc), 'partial')

    def test_hidden_inspection_not_reported_as_proven_absence(self):
        iqc = self._receipt()
        model = type(self.env['iatf.incoming.inspection'])
        with patch.object(model, 'search', return_value=self.env['iatf.incoming.inspection']):
            self.assertEqual(self.status(iqc), 'missing')
        self.assertEqual(dict(iqc.receipt_move_line_id._fields['sq_iqc_status'].selection)['missing'], '검사 연결 미확인')

    def test_legacy_and_mismatched_receipts_are_not_silently_passed(self):
        iqc = self._receipt()
        service(iqc.receipt_move_line_id).write({'iqc_receipt_managed': False})
        self.assertEqual(self.status(iqc), 'legacy')
        service(iqc.receipt_move_line_id).write({'iqc_receipt_managed': True})
        service(iqc).write({'receipt_snapshot': {'invalid': 'fixture of legacy corruption'}})
        self.assertEqual(self.status(iqc), 'mismatch')

    def test_company_date_scope_and_no_data_not_zero_percent(self):
        self.assertIsNone(self.dash.get_receipt_coverage('2099-01-01', '2099-01-31')['decision_rate'])
        domain = self.dash.with_context(tz='Asia/Seoul')._receipt_domain('2026-10-21', '2026-10-21')
        self.assertIn(('date', '>=', '2026-10-20 15:00:00'), domain)
        self.assertIn(('date', '<', '2026-10-21 15:00:00'), domain)
        self.assertIn(('company_id', '=', self.company.id), domain)
        for start, end in [('2026-12-01', '2026-01-01'), ('2020-01-01', '2026-01-01')]:
            with self.assertRaises(UserError): self.dash.get_receipt_coverage(start, end)

    def test_read_only_source_and_role_permissions(self):
        iqc = self._receipt()
        before = iqc.read(['state', 'quantity_received', 'quantity_released', 'write_date'])
        reader = self.dash.with_user(self.reader)
        write_before = iqc.receipt_move_line_id.with_user(self.reader).has_access('write')
        result = reader.get_receipt_coverage(str(self.today), str(self.today))
        self.assertFalse(result['restricted'])
        self.assertGreater(result['counts']['pending'], 0)
        action = reader.open_receipt_coverage(str(self.today), str(self.today))
        self.assertFalse(action['context']['edit'])
        linked = iqc.receipt_move_line_id.with_user(self.reader).action_sq_open_inspection()
        self.assertEqual(linked['res_id'], iqc.id)
        self.assertFalse(linked['context']['edit'])
        self.assertEqual(before, iqc.read(['state', 'quantity_received', 'quantity_released', 'write_date']))
        # This database has legacy internal-user ACLs. The reader grant is additive;
        # the new projection must not change pre-existing permissions.
        self.assertEqual(write_before, iqc.receipt_move_line_id.with_user(self.reader).has_access('write'))
        with self.assertRaises(UserError):
            iqc.receipt_move_line_id.with_user(self.reader).write({'quantity': 12})
        with self.assertRaises(AccessError):
            self.dash.with_user(self.stock).get_receipt_coverage(str(self.today), str(self.today))

    def test_mixed_units_do_not_generate_invalid_quantity_rate(self):
        self._approve(self._receipt())
        kg = self.env.ref('uom.product_uom_kgm')
        resin = self.env['product.product'].create({'name': '[TEST] kg resin', 'is_storable': True,
                                                  'uom_id': kg.id, 'uom_po_id': kg.id})
        self._approve(self._receipt(product=resin, uom=kg))
        data = self.dash.get_dashboard_data(str(self.today), str(self.today))
        board = next(b for b in data['boards'] if b['model'] == 'iatf.incoming.inspection')
        self.assertIsNone(board['quantity'])
        self.assertIsNone(board['rejected_rate'])

    def test_missing_source_permission_shows_restricted_not_zero(self):
        user = new_test_user(self.env, login='sq.coverage.no.sources', groups='cams_sq.group_sq_user')
        data = self.dash.with_user(user).get_receipt_coverage(str(self.today), str(self.today))
        self.assertTrue(data['restricted'])
        self.assertNotIn('total', data)


@tagged('post_install', '-at_install')
class TestSqRequiredDocuments(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env['sq.standard'].action_load_catalog()
        cls.item = cls.env['sq.item'].search([('code', '=', 'INJ.2_3'), ('company_id', '=', cls.env.company.id)], limit=1)
        cls.today = fields.Date.context_today(cls.env.user)
        cls.role = cls.env['ops.role'].create({'name': '[TEST] master review'})
        cls.doc_approver = new_test_user(cls.env, login='sq.required.documents',
            groups='iatf_document_control.group_document_manager,cams_ops_process.group_ops_manager,cams_sq.group_sq_manager')
        cls.cat = cls.env['iatf.document.category'].create({'name': '[TEST] required docs', 'code': 'SQREQDOC'})

    def document(self, bound=True, approved=True, next_review=None):
        doc = self.env['iatf.document'].create({'name': '[TEST] master ledger', 'category_id': self.cat.id,
            'company_id': self.env.company.id, 'reviewer_id': self.doc_approver.id, 'approver_id': self.doc_approver.id})
        if next_review:
            doc.next_review_date = next_review
        if approved:
            doc.action_submit_review(); doc.with_user(self.doc_approver).action_approve()
        if bound:
            self.env['sq.evidence.binding'].create({'item_id': self.item.id, 'source_ref': 'iatf.document,%s' % doc.id,
                'purpose': '[TEST] actual master review source'})
        return doc

    def plan(self, doc):
        return self.env['ops.task.def'].create({'name': '[TEST] required document review', 'role_id': self.role.id,
            'periodicity': 'daily', 'sq_item_id': self.item.id, 'sq_start_date': self.today,
            'requires_approval': True, 'sq_required_document_ids': [(6, 0, doc.ids)]})

    def test_unbound_document_not_accepted_as_required(self):
        doc = self.document(bound=False)
        with self.assertRaises(UserError): self.plan(doc)

    def test_required_document_missing_and_plan_history_frozen(self):
        required, unrelated = self.document(), self.document(bound=False)
        plan = self.plan(required)
        task = plan._create_task(str(self.today), self.today)
        task.write({'sq_performed_date': self.today, 'sq_result': 'ok', 'done_note': '[TEST] checked ledger',
                    'sq_document_ids': [(6, 0, unrelated.ids)]})
        with self.assertRaises(UserError): task.action_mark_done()
        with self.assertRaises(UserError): plan.write({'sq_required_document_ids': [(5, 0, 0)]})
        task.sq_document_ids = required
        task.action_mark_done()
        task.with_user(self.doc_approver).action_approve()
        self.assertEqual(task.state, 'approved')

    def test_review_due_is_distinct_from_approval_or_expiration(self):
        approved = self.document(next_review=self.today - timedelta(days=1))
        # A review deadline is an alert; it is not a certificate's validity date.
        self.document(approved=False)
        data = self.item._document_snapshot()
        self.assertEqual(data['due'], 1)
        self.assertEqual(data['unapproved'], 1)
        self.assertEqual(approved.state, 'approved')
        self.assertEqual(self.item.action_daily_documents()['res_model'], 'iatf.document')

    def test_no_binding_and_read_permission_are_not_healthy_zero(self):
        self.assertEqual(self.item._document_snapshot()['status'], '연결 문서 없음')
        self.document()
        reader = new_test_user(self.env, login='sq.doc.restricted', groups='cams_ops_process.group_ops_user')
        with self.assertRaises(AccessError): self.item.with_user(reader)._document_snapshot()
