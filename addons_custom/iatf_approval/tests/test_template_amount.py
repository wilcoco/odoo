"""결재선 템플릿 금액 매칭 — 하한 0 은 음수(환입·가감) 문서에도 적용된다 (2026-09-27 T7-b)."""
from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestTemplateAmount(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.approver = new_test_user(cls.env, login='tpl-amount-approver', groups='base.group_user')
        Template = cls.env['iatf.approval.template']
        line = [Command.create({'sequence': 10, 'approver_mode': 'user', 'user_id': cls.approver.id})]
        cls.any_amount = Template.create({'name': 'SYNTHETIC 금액 무관', 'min_amount': 0.0, 'line_ids': line})
        cls.over_1000 = Template.create({'name': 'SYNTHETIC 1000 이상', 'min_amount': 1000.0, 'line_ids': line})
        cls.record = cls.env['res.partner'].create({'name': 'SYNTHETIC template target'})
        cls.Template = Template.sudo()

    def _find(self, amount):
        found = self.Template._find_for(self.record, amount, self.env['hr.department'])
        return found & (self.any_amount | self.over_1000)

    def test_zero_threshold_matches_negative_refund_amount(self):
        self.assertEqual(self._find(-1500.0), self.any_amount)

    def test_positive_threshold_still_requires_amount(self):
        self.assertEqual(self._find(500.0), self.any_amount)
        self.assertEqual(self._find(2000.0), self.over_1000)
        self.assertEqual(self._find(-2000.0), self.any_amount)
