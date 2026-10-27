import json

from odoo import Command
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestTemplateScope(TransactionCase):
    def test_company_and_document_subtype_select_independently(self):
        approver = new_test_user(self.env, login='scope_approver', groups='base.group_user,base.group_partner_manager')
        model = self.env['ir.model']._get('res.partner')
        company2 = self.env['res.company'].create({'name': 'SYNTHETIC template company'})
        approver.write({'company_ids': [Command.link(company2.id)]})
        templates = self.env['iatf.approval.template']
        base = {'model_id': model.id, 'line_ids': [Command.create({'user_id': approver.id})]}
        ordinary = templates.create(dict(base, name='SYNTHETIC generic company rule'))
        scoped = templates.create(dict(base, name='SYNTHETIC company customer only',
            match_domain=json.dumps([['name', '=', 'SYNTHETIC scoped target']])))
        other = templates.create(dict(base, name='SYNTHETIC other company', company_id=company2.id))
        target = self.env['res.partner'].create({'name': 'SYNTHETIC scoped target', 'company_id': self.env.company.id})
        department = self.env['hr.department']
        self.assertEqual(templates._find_for(target, 0, department), scoped)
        target.name = 'SYNTHETIC ordinary target'
        self.assertEqual(templates._find_for(target, 0, department), ordinary)
        target.company_id = company2
        self.assertEqual(templates._find_for(target, 0, department), other)

    def test_invalid_domain_and_department_company_rejected(self):
        templates = self.env['iatf.approval.template']
        for domain in ['__import__("os")', '{}', '[["missing_field","=",1]]', '[["name","bogus",1]]']:
            with self.assertRaises(ValidationError), self.cr.savepoint():
                templates.create({'name': 'SYNTHETIC invalid', 'match_domain': domain,
                                  'model_id': self.env['ir.model']._get_id('res.partner')})
        company = self.env['res.company'].create({'name': 'SYNTHETIC other company'})
        dept = self.env['hr.department'].create({'name': 'SYNTHETIC other department', 'company_id': company.id})
        with self.assertRaises(ValidationError), self.cr.savepoint():
            templates.create({'name': 'SYNTHETIC mismatch', 'department_id': dept.id,
                              'company_id': self.env.company.id})

    def test_configuration_warning_does_not_elevate_approver(self):
        user = new_test_user(self.env, login='scope_readonly_approver', groups='base.group_user')
        before = user.groups_id
        values = {
            'name': 'SYNTHETIC missing write role', 'model_id': self.env['ir.model']._get_id('ir.module.module'),
            'line_ids': [Command.create({'user_id': user.id})]}
        templates = self.env['iatf.approval.template']
        if 'cams.ops.policy' in self.env:
            # P0 intentionally tightened the prior warning to a save guard.
            with self.assertRaises(ValidationError), self.cr.savepoint():
                templates.create(values)
        else:
            template = templates.create(values)
            self.assertIn('쓰기 권한', template.configuration_note)
        self.assertEqual(user.groups_id, before)
