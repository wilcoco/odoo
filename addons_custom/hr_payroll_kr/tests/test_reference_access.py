from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestHrReferenceAccess(TransactionCase):
    def test_hr_reference_access_does_not_grant_payroll(self):
        user = new_test_user(self.env, login='hr_reference_only', groups='hr.group_hr_user', email='hr-reference@example.invalid')
        model = self.env['hr.payroll.structure.type'].with_user(user)
        self.assertTrue(model.check_access_rights('read', raise_exception=False))
        for operation in ('write', 'create', 'unlink'):
            self.assertFalse(model.check_access_rights(operation, raise_exception=False))
        self.assertFalse(self.env['hr.payslip'].with_user(user).check_access_rights('read', raise_exception=False))
