"""자기결재 금지 + 전결 규정(문서별 결재 체계) — 2026-10-19 사용자 결정."""
from unittest import SkipTest

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestApprovalAuthority(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if 'iatf.shipping.inspection' not in cls.env:
            raise SkipTest('Run with iatf_shipping_inspection for the real target ACL fixture')
        group = 'base.group_user,iatf_shipping_inspection.group_shipping_inspection_user'
        cls.author = new_test_user(cls.env, login='auth-author', groups=group, email='auth-author@example.com')
        cls.leader = new_test_user(cls.env, login='auth-leader', groups=group, email='auth-leader@example.com')
        cls.director = new_test_user(cls.env, login='auth-director', groups=group, email='auth-director@example.com')
        cls.ceo = new_test_user(cls.env, login='auth-ceo', groups=group, email='auth-ceo@example.com')
        Employee = cls.env['hr.employee']
        cls.e_director = Employee.create({'name': 'SYNTHETIC 본부장', 'user_id': cls.director.id})
        cls.e_leader = Employee.create({'name': 'SYNTHETIC 팀장', 'user_id': cls.leader.id})
        cls.division = cls.env['hr.department'].create({'name': 'SYNTHETIC 본부', 'manager_id': cls.e_director.id})
        cls.team = cls.env['hr.department'].create({'name': 'SYNTHETIC 품질팀', 'parent_id': cls.division.id,
                                                    'manager_id': cls.e_leader.id})
        cls.e_leader.department_id = cls.team
        Employee.create({'name': 'SYNTHETIC 담당', 'user_id': cls.author.id, 'department_id': cls.team.id})
        cls.product = cls.env['product.product'].create({'name': 'SYNTHETIC authority scope'})
        cls.Policy = cls.env['iatf.approval.policy']
        cls.Policy._sync_documents()
        cls.policy = cls.Policy.search([('model', '=', 'iatf.shipping.inspection')])
        # A restored user-test DB may already have matching global rules.
        # Isolate this transaction's fixtures; TransactionCase rolls it back.
        cls.env['iatf.approval.template'].search([
            '|', ('model_id', '=', False), ('model_id.model', '=', 'iatf.shipping.inspection')
        ]).write({'active': False})

    def _doc(self, user, lines=()):
        vals = {'product_id': self.product.id, 'company_id': self.env.company.id}
        if lines:
            vals['approval_line_ids'] = [Command.create({'sequence': (i + 1) * 10, 'user_id': u.id}) for i, u in enumerate(lines)]
        return self.env['iatf.shipping.inspection'].with_user(user).create(vals)

    def _rule(self, *lines, **vals):
        return self.env['iatf.approval.template'].create(dict({
            'name': 'SYNTHETIC 출하검사 전결', 'policy_id': self.policy.id,
            'line_ids': [Command.create(dict(sequence=(i + 1) * 10, **line)) for i, line in enumerate(lines)]}, **vals))

    # ── 자기결재 금지 ──
    def test_author_cannot_be_an_approver(self):
        doc = self._doc(self.author, [self.leader, self.author])
        with self.assertRaisesRegex(UserError, '자기결재'), self.env.cr.savepoint():
            doc.action_submit_approval()
        self.assertEqual(doc.approval_state, 'draft')

    def test_submitter_cannot_be_an_approver_even_if_someone_else_drafted(self):
        doc = self._doc(self.author, [self.leader])
        with self.assertRaisesRegex(UserError, '자기결재'), self.env.cr.savepoint():
            doc.with_user(self.leader).action_submit_approval()

    def test_normal_approval_still_works(self):
        doc = self._doc(self.author, [self.leader])
        doc.action_submit_approval()
        doc.with_user(self.leader).action_approve_approval()
        self.assertEqual(doc.approval_state, 'approved')

    # ── 전결 규정 ──
    def test_every_approval_document_is_listed(self):
        self.assertTrue(self.policy, '결재 mixin 문서가 전결 규정 목록에 있어야 한다')
        listed = set(self.Policy.search([]).mapped('model'))
        self.assertIn('iatf.shipping.inspection', listed)
        self.assertNotIn('iatf.approval.mixin', listed)
        self.assertFalse(self.Policy._sync_documents(), '두 번 갱신해도 중복 생성 없음')

    def test_manager_rule_escalates_when_author_is_the_manager(self):
        self._rule({'approver_mode': 'manager'}, {'approver_mode': 'user', 'user_id': self.ceo.id})
        mine = self._doc(self.author)
        mine.action_submit_approval()
        self.assertEqual(mine.approval_line_ids.sorted('sequence').user_id, self.leader | self.ceo)
        leaders = self._doc(self.leader)
        leaders.action_submit_approval()
        self.assertEqual(leaders.approval_line_ids.sorted('sequence').user_id, self.director | self.ceo,
                         '팀장이 올리면 상위 부서장(본부장)으로 올라가야 한다')

    def test_rule_step_resolving_to_submitter_is_dropped(self):
        self._rule({'approver_mode': 'user', 'user_id': self.leader.id}, {'approver_mode': 'user', 'user_id': self.ceo.id})
        doc = self._doc(self.leader)
        doc.action_submit_approval()
        self.assertEqual(doc.approval_line_ids.user_id, self.ceo)

    def test_locked_rule_replaces_manual_lines(self):
        self._rule({'approver_mode': 'user', 'user_id': self.ceo.id})
        self.policy.lock_lines = True
        doc = self._doc(self.author, [self.leader])
        doc.action_submit_approval()
        self.assertEqual(doc.approval_line_ids.user_id, self.ceo)
        self.assertEqual(doc.approval_current_approver_id, self.ceo)

    def test_required_rule_blocks_submission_without_rule(self):
        self.policy.require_rule = True
        doc = self._doc(self.author, [self.leader])
        with self.assertRaisesRegex(UserError, '전결 규정'), self.env.cr.savepoint():
            doc.action_submit_approval()
        self._rule({'approver_mode': 'user', 'user_id': self.ceo.id})
        doc.action_submit_approval()
        self.assertEqual(doc.approval_line_ids.user_id, self.leader, '규정 필수(고정 아님)는 작성자가 고른 결재선을 유지')

    def test_amount_and_rule_table(self):
        rule = self._rule({'approver_mode': 'manager'}, {'approver_mode': 'user', 'user_id': self.ceo.id}, min_amount=0.0)
        self.assertEqual(rule.model_id.model, 'iatf.shipping.inspection')
        self.assertIn('→', rule.line_summary)
        rows = self.env['iatf.approval.template.line'].search([('rule_policy_id', '=', self.policy.id)])
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(rows.mapped('approver_label')))
