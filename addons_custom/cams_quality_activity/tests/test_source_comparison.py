from odoo import Command
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged('post_install', '-at_install')
class TestSourceComparison(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.reader = new_test_user(cls.env, login='p1-source-reader', groups='cams_quality_activity.group_activity_user,mrp.group_mrp_user,stock.group_stock_user,iatf_work_environment.group_work_environment_user')
        cls.limited = new_test_user(cls.env, login='p1-source-limited', groups='cams_quality_activity.group_activity_user,mrp.group_mrp_user')
        cls.product = cls.env['product.product'].create({'name': 'SYNTHETIC comparison part', 'is_storable': True})
        cls.mo = cls.env['mrp.production'].create({'product_id': cls.product.id, 'product_qty': 1, 'product_uom_id': cls.product.uom_id.id})
        cls.sheet = cls.env['iatf.check.sheet'].create({'name': 'SYNTHETIC linked checklist', 'code': 'P1-COMPARE', 'target_type': 'etc', 'cycle': 'daily'})

    def _wizard(self, user=None):
        return self.env['cams.manufacturing.source.comparison'].with_user(user or self.reader).create({'production_id': self.mo.id})

    def test_linked_source_only_and_read_has_no_quantity_effect(self):
        linked = self.env['iatf.check.record'].create({'sheet_id': self.sheet.id, 'production_id': self.mo.id})
        unrelated = self.env['iatf.check.record'].create({'sheet_id': self.sheet.id})
        before = self.mo.read(['state', 'qty_produced', 'product_qty'])
        stocks = self.env['stock.move'].search_count([])
        wizard = self._wizard()
        html = str(wizard.daily_html)
        self.assertIn('id=%s&amp;' % linked.id, html)
        self.assertNotIn('model=iatf.check.record&amp;id=%s&amp;' % unrelated.id, html)
        self.assertIn('자료 0건', str(wizard.material_html))
        self.assertNotIn('자동 합격', html)
        self.assertEqual(self.mo.read(['state', 'qty_produced', 'product_qty']), before)
        self.assertEqual(self.env['stock.move'].search_count([]), stocks)

    def test_integration_contract_and_escape_for_all_five_tables(self):
        wizard = self.env['cams.manufacturing.source.comparison'].create({'production_id': self.mo.id})
        html = ''.join(str(wizard[field]) for field in ('daily_html', 'material_html', 'mold_html', 'condition_html', 'shipping_html'))
        self.assertNotIn('원천 필드 연결 확인 필요', html)
        self.assertNotIn('원천 모듈 미설치', html)
        self.product.name = '<script>alert(1)</script>'
        table = str(wizard._source_table('품번', 'product.product', [('id', '=', self.product.id)], {'name': '이름'}))
        self.assertNotIn('<script>', table)
        self.assertIn('&lt;script&gt;', table)

    def test_acl_is_not_replaced_with_sudo(self):
        wizard = self._wizard(self.limited)
        self.assertIn('권한 없음', str(wizard.daily_html))
        other = self.env['res.company'].create({'name': 'SYNTHETIC source comparison other company'})
        foreign_mo = self.env['mrp.production'].with_company(other).create({'product_id': self.product.id, 'product_qty': 1, 'product_uom_id': self.product.uom_id.id, 'company_id': other.id})
        with self.assertRaises(UserError):
            with self.env.cr.savepoint():
                wizard.write({'production_id': foreign_mo.id})
                wizard._compute_comparison()
