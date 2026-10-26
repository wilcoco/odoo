"""E7: employee name prefetch must not request private approval/leave fields."""
from datetime import date

from odoo import Command
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'e7_employee_privacy')
class TestEmployeePrivacy(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.reader = Users.create({
            'name': 'E7 non-HR', 'login': 'e7_non_hr',
            'groups_id': [Command.set([cls.env.ref('base.group_user').id])],
        })
        cls.hr = Users.create({
            'name': 'E7 HR', 'login': 'e7_hr',
            'groups_id': [Command.set([cls.env.ref('hr.group_hr_user').id])],
        })
        cls.grade = cls.env['escon.job.grade'].create({'name': 'E7 grade'})
        cls.employee = cls.env['hr.employee'].create({
            'name': 'E7 private employee', 'job_grade_id': cls.grade.id,
            'eap_hire_date': date(2024, 1, 15),
        })

    def test_cold_employee_name_read_does_not_fetch_private_fields(self):
        self.assertFalse(self.reader.has_group('hr.group_hr_user'))
        self.env.invalidate_all()
        # Exactly the lazy Many2one name read used by planning completion tracking.
        self.assertEqual(self.employee.with_user(self.reader).name, 'E7 private employee')

    def test_private_fields_stay_private(self):
        for field in ('job_grade_id', 'eap_hire_date'):
            self.assertNotIn(field, self.env['hr.employee.public']._fields)
            with self.assertRaises(AccessError):
                self.employee.with_user(self.reader).read([field])

    def test_hr_values_and_access_are_preserved(self):
        self.env.invalidate_all()
        employee = self.employee.with_user(self.hr)
        self.assertEqual(employee.job_grade_id, self.grade)
        self.assertEqual(employee.eap_hire_date, date(2024, 1, 15))
