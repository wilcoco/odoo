from datetime import timedelta
from odoo import Command, fields
from odoo.exceptions import AccessError,UserError
from odoo.tests import TransactionCase,tagged
from odoo.tests.common import new_test_user


@tagged('post_install','-at_install')
class TestMaterialEvidence(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.author=new_test_user(cls.env,login='p1-material-author',groups='cams_material_control.group_material_user,iatf_document_control.group_document_user')
        cls.reviewer=new_test_user(cls.env,login='p1-material-reviewer',groups='cams_material_control.group_material_manager,iatf_document_control.group_document_manager')
        change_group=cls.env.ref('iatf_change_management.group_change_management_user',raise_if_not_found=False)
        if change_group:cls.reviewer.write({'groups_id':[Command.link(change_group.id)]})
        cls.today=fields.Date.today()
        kg=cls.env.ref('uom.product_uom_kgm')
        cls.product=cls.env['product.product'].create({'name':'SYNTHETIC P1 resin','is_storable':True,'uom_id':kg.id,'uom_po_id':kg.id,'tracking':'lot'})
        cls.lot=cls.env['stock.lot'].create({'name':'SYNTHETIC P1 resin LOT','product_id':cls.product.id,'company_id':cls.env.company.id})
        cls.workcenter=cls.env['mrp.workcenter'].create({'name':'SYNTHETIC P1 material workcenter','company_id':cls.env.company.id})
        cls.equipment=cls.env['iatf.equipment'].create({'name':'SYNTHETIC material machine','workcenter_id':cls.workcenter.id,'company_id':cls.env.company.id})
        cls.category=cls.env['iatf.document.category'].create({'name':'SYNTHETIC material criteria','code':'P1-MATERIAL'})

    def _standard(self,process='dryer',approve=True):
        doc=self.env['iatf.document'].with_user(self.author).create({
            'name':'SYNTHETIC '+process+' criterion','category_id':self.category.id,
            'reviewer_id':self.reviewer.id,'approver_id':self.reviewer.id,
            'quality_evidence_kind':'equipment_standard','quality_product_ids':[Command.set(self.product.ids)],
            'quality_material_process':process,'quality_limits_confirmed':True,
            'quality_limit_source':'SYNTHETIC test values only; not plant standards',
            'quality_dry_temp_min':70,'quality_dry_temp_max':90,'quality_dry_hours':3,'quality_prestart_hours':3,
            'quality_moisture_in_ppm':1500,'quality_moisture_before_ppm':1100,'quality_moisture_method':'SYNTHETIC hopper sample',
            'quality_grind_good_mm':30,'quality_grind_reject_mm':40,'quality_grind_sample_ml':500,
            'quality_blade_gap_mm':1.5,'quality_blade_change_kg':12000})
        if approve:
            doc.action_submit_review();doc.with_user(self.reviewer).action_approve()
        return doc

    def _check(self,**values):
        start=fields.Datetime.now()-timedelta(hours=1)
        vals={'name':'SYNTHETIC dryer check','standard_document_id':self._standard().id,'equipment_id':self.equipment.id,
            'product_id':self.product.id,'lot_id':self.lot.id,'workcenter_id':self.workcenter.id,'shift':'day',
            'temperature':80,'remaining_kg':60,'capacity_kg':100,'hourly_usage_kg':20,
            'shot_weight_g':100,'cycle_seconds':18,'dryer_started_at':start-timedelta(hours=3),
            'production_started_at':start,'moisture_in_ppm':1400,'moisture_1h_ppm':1300,'moisture_2h_ppm':1200,
            'moisture_3h_ppm':1000,'moisture_before_ppm':1000,'measurement_method':'SYNTHETIC measured hopper sample',
            'measurements_confirmed':True,'filter_result':'ok',
            'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]}
        vals.update(values)
        return self.env['cams.dryer.check'].with_user(self.author).create(vals)

    def _complete(self,record):
        record.action_submit_approval();record.with_user(self.reviewer).action_approve_approval();record.action_complete_evidence()

    def test_real_standard_confirmation_required(self):
        doc=self._standard(approve=False)
        doc.quality_limits_confirmed=False
        doc.action_submit_review()
        with self.assertRaises(UserError):doc.with_user(self.reviewer).action_approve()
        record=self._check(standard_document_id=doc.id)
        with self.assertRaises(UserError):record.action_submit_approval()

    def test_capacity_prestart_moisture_and_immutable_derived_result(self):
        record=self._check()
        self.assertEqual(record.lower_level_kg,60)
        self.assertAlmostEqual(record.calculated_usage_kg,20)
        self.assertEqual(record.result,'ok')
        self._complete(record)
        snapshot=record.completion_snapshot
        doc=record.standard_document_id.with_user(self.reviewer)
        doc.action_new_revision();doc.write({'quality_dry_hours':4,'quality_moisture_before_ppm':800})
        self.assertEqual(record.result,'ok')
        self.assertEqual(record.lower_level_kg,60)
        self.assertEqual(record.completion_snapshot,snapshot)
        with self.assertRaises(UserError):record.write({'result':'ng'})

    def test_dryer_ng_requires_action_never_becomes_pass(self):
        record=self._check(remaining_kg=59,moisture_before_ppm=1200)
        self.assertEqual(record.result,'ng')
        with self.assertRaises(UserError):record.action_submit_approval()
        record.action_note='SYNTHETIC isolate material and continue drying'
        self._complete(record)
        self.assertEqual(record.result,'ng')
        self.assertEqual(record.completion_snapshot['derived']['result'],'ng')

    def test_unmeasured_zero_and_short_prestart(self):
        record=self._check(measurements_confirmed=False)
        self.assertEqual(record.result,'pending')
        with self.assertRaises(UserError):record.action_submit_approval()
        record.write({'measurements_confirmed':True,'dryer_started_at':record.production_started_at-timedelta(hours=2)})
        self.assertEqual(record.result,'ng')

    def test_equipment_and_workcenter_mismatch_rejected(self):
        other=self.env['mrp.workcenter'].create({'name':'SYNTHETIC other machine','company_id':self.env.company.id})
        record=self._check(workcenter_id=other.id)
        with self.assertRaises(UserError):record.action_submit_approval()

    def test_grind_boundaries_and_output_lot(self):
        standard=self._standard('grinder')
        regrind=self.env['iatf.regrind.log'].with_user(self.author).create({'source_product_id':self.product.id,
            'input_qty':10,'output_qty':9,'output_lot_id':self.lot.id,'foreign_check':'ok'})
        for mm,result in [(30,'usable'),(30.1,'inspect'),(39.9,'inspect'),(40,'reject')]:
            record=self.env['cams.grind.sample'].with_user(self.author).create({'name':'SYNTHETIC particle '+str(mm),
                'standard_document_id':standard.id,'equipment_id':self.equipment.id,'workcenter_id':self.workcenter.id,
                'product_id':self.product.id,'lot_id':self.lot.id,'shift':'day','regrind_log_id':regrind.id,
                'sample_volume_ml':500,'maximum_particle_mm':mm,'measurements_confirmed':True,
                'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]})
            self.assertEqual(record.result,result)
            if result!='usable':
                with self.assertRaises(UserError):record.action_submit_approval()
                record.action_note='SYNTHETIC isolate and review particle size'
            self._complete(record)

    def test_grinder_limit_exceeded_requires_disposition(self):
        record=self.env['cams.grinder.check'].with_user(self.author).create({'name':'SYNTHETIC grinder check',
            'standard_document_id':self._standard('grinder').id,'equipment_id':self.equipment.id,'workcenter_id':self.workcenter.id,
            'product_id':self.product.id,'lot_id':self.lot.id,'shift':'night','blade_gap_mm':1.6,'ground_since_change_kg':12000,
            'measurements_confirmed':True,'cleanliness':'ok','foreign_material':'ok','gear_oil':'ok',
            'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]})
        self.assertEqual(record.result,'ng')
        with self.assertRaises(UserError):record.action_submit_approval()
        record.action_note='SYNTHETIC blade replacement and gap adjustment'
        self._complete(record)

    def test_filter_history_needs_future_schedule_and_approval(self):
        record=self.env['cams.dryer.filter.log'].with_user(self.author).create({'name':'SYNTHETIC filter clean',
            'standard_document_id':self._standard().id,'equipment_id':self.equipment.id,'workcenter_id':self.workcenter.id,
            'product_id':self.product.id,'shift':'day','trace_exception':'SYNTHETIC between lot maintenance',
            'operation':'clean','completed_detail':'SYNTHETIC removed contamination','next_due_date':self.today,
            'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]})
        with self.assertRaises(UserError):record.action_submit_approval()
        record.next_due_date=self.today+timedelta(days=7)
        self._complete(record)
        with self.assertRaises(UserError):record.write({'operation':'replace'})

    def _regrind(self):
        output_lot=self.env['stock.lot'].create({'name':'SYNTHETIC P1 output','product_id':self.product.id,'company_id':self.env.company.id})
        source=self.env['stock.location'].create({'name':'SYNTHETIC Regrind production','usage':'production','company_id':self.env.company.id})
        destination=self.env['stock.warehouse'].search([('company_id','=',self.env.company.id)],limit=1).lot_stock_id
        move=self.env['stock.move'].create({'name':'SYNTHETIC regrind output','product_id':self.product.id,
            'product_uom':self.product.uom_id.id,'product_uom_qty':9,'company_id':self.env.company.id,
            'location_id':source.id,'location_dest_id':destination.id})
        move._action_confirm()
        values={'move_id':move.id,'product_id':self.product.id,
            'product_uom_id':self.product.uom_id.id,'quantity':9,'lot_id':output_lot.id,
            'location_id':source.id,'location_dest_id':destination.id,'company_id':self.env.company.id}
        if move.move_line_ids:
            self.assertEqual(len(move.move_line_ids),1)
            move.move_line_ids.write({'quantity':9,'lot_id':output_lot.id})
        else:self.env['stock.move.line'].create(values)
        move.picked=True
        move._action_done()
        return self.env['iatf.regrind.log'].with_user(self.author).create({'source_product_id':self.product.id,
            'input_qty':10,'output_qty':9,'output_lot_id':output_lot.id,'output_move_id':move.id,
            'lot_id':self.lot.id,'equipment_id':self.equipment.id,'workcenter_id':self.workcenter.id,'foreign_check':'ok',
            'approval_line_ids':[Command.create({'user_id':self.reviewer.id})]})

    def test_regrind_real_receipt_matches_and_does_not_create_stock_twice(self):
        record=self._regrind()
        quants=self.env['stock.quant'].search([('lot_id','=',record.output_lot_id.id)])
        before=quants.read(['quantity','reserved_quantity'])
        record.output_qty=8
        with self.assertRaises(UserError):record.action_submit_approval()
        record.output_qty=9
        self._complete(record)
        self.assertEqual(record.state,'done')
        record.action_done()
        self.assertEqual(quants.read(['quantity','reserved_quantity']),before)
        with self.assertRaises(UserError):record.action_draft()
        with self.assertRaises(UserError):record.write({'output_qty':10})
        new=self.env[record._name].with_user(self.author).browse(record.action_new_evidence_revision()['res_id'])
        self.assertEqual(new.state,'draft')
        self.assertEqual(new.evidence_revision,2)
        self.assertEqual(record.completion_snapshot['output_move']['quantity'],9)

    def test_blend_lot_provenance_limits_and_child_mutation(self):
        source=self._regrind();self._complete(source)
        self.env['iatf.blend.standard'].create({'product_id':self.product.id,'max_regrind_ratio':30,'effective_date':self.today})
        values={'product_id':self.product.id,'lot_id':self.lot.id,'equipment_id':self.equipment.id,
            'workcenter_id':self.workcenter.id,'approval_line_ids':[Command.create({'user_id':self.reviewer.id})],
            'line_ids':[Command.create({'material_type':'virgin','product_id':self.product.id,'lot_id':self.lot.id,'qty':7}),
                        Command.create({'material_type':'regrind','product_id':self.product.id,'lot_id':source.output_lot_id.id,'regrind_log_id':source.id,'qty':3})]}
        record=self.env['iatf.blend.log'].with_user(self.author).create(values)
        self.assertEqual(record.result,'ok')
        record.action_submit_approval()
        with self.assertRaises(UserError):record.line_ids[0].write({'qty':8})
        with self.assertRaises(UserError):record.line_ids[0].unlink()
        record.with_user(self.reviewer).action_approve_approval();record.action_complete_evidence()
        self.assertEqual(record.state,'done')
        self.assertEqual(record.completion_snapshot['ratio']['regrind_ratio'],30)
        new=self.env[record._name].with_user(self.author).browse(record.action_new_evidence_revision()['res_id'])
        self.assertEqual(len(new.line_ids),2)
        new.line_ids[0].qty=8
        self.assertEqual(record.line_ids[0].qty,7)
        with self.assertRaises(UserError):record.write({'limit_ratio':100})
