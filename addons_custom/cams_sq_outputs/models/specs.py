"""Allowlisted source adapters. They read the original ledgers, never copy them.

Date=False denotes a CURRENT master, explicitly labelled in the export.
Fields absent in an installed version are shown as unavailable, not fabricated.
"""


def spec(date, columns, company='company_id', lines=None, scopes=None, grid=False):
    return dict(date=date, columns=columns.split(), company=company,
                lines=lines, scopes=scopes or {}, grid=grid)


SPECS = {
    'iatf.check.record': spec('check_date', 'name check_date shift checker_id sheet_revision state overall_result quality_purpose lot_id production_id',
        lines=('line_ids', 'item_name standard target_value tolerance spec_min spec_max value text_value uom_name result five_point_score stop_score five_point_definition remark'),
        scopes={'iatf.check.sheet': 'sheet_id'}, grid=True),
    'iatf.daily.check': spec('check_date', 'name equipment_id check_date shift checker_id overall_result notes',
        company='equipment_id.company_id', lines=('line_ids', 'item_name standard result remark'),
        scopes={'iatf.equipment': 'equipment_id'}, grid=True),
    'iatf.mold.check': spec('check_date', 'name mold_id check_date shift check_type checker_id production_id state overall_result',
        lines=('line_ids', 'item_name standard spec_min spec_max value result remark'),
        scopes={'injection.mold': 'mold_id'}, grid=True),
    'iatf.environment.check': spec('check_date', 'name work_area_id check_date checker_id temperature humidity lighting noise score_seiri score_seiton score_seiso score_seiketsu score_shitsuke fiveS_total result state notes',
        company='work_area_id.company_id', lines=('line_ids', 'item_name standard measured_value result remark'), scopes={'iatf.work.area': 'work_area_id'}),
    'iatf.mold.maintenance': spec('date', 'name mold_id date maintenance_type responsible_id work_description result state cleaning_method cleaning_agent duration_hours shots_at_maintenance parts_replaced',
        scopes={'injection.mold': 'mold_id'}),
    'iatf.mold.tryout': spec('tryout_date', 'name mold_id tryout_date tryout_no reason shot_count ok_qty ng_qty conclusion responsible_id state', scopes={'injection.mold': 'mold_id'}),
    'iatf.mold.temp.log': spec('measured_at', 'name mold_id measured_at measured_by_id temperature spec_min spec_max spec_result current_spec_result method point shift action_note evidence_state evidence_revision', scopes={'injection.mold': 'mold_id'}),
    'iatf.training.record': spec('training_date', 'name title training_date training_type department_id trainer_id employee_ids participant_count topics duration_hours evaluation_method pass_criteria effectiveness_verified effectiveness_notes state', scopes={'hr.department': 'department_id'}),
    'iatf.competence.matrix': spec(False, 'employee_id skill_name required_level current_level certification expiry_date last_training_date next_retraining_date', company='employee_id.company_id'),
    'iatf.qualification.preassessment': spec('record_date', 'name competence_id record_date theory_score practical_score assessed_level result observation followup evidence_state evidence_revision', scopes={'iatf.competence.matrix': 'competence_id'}),
    'iatf.calibration.record': spec('calibration_date', 'name equipment_id calibration_date calibration_type result certificate_number performed_by next_due_date', scopes={'iatf.measurement.equipment': 'equipment_id'}),
    'iatf.measurement.equipment': spec(False, 'name equipment_id_number serial_number manufacturer model_number location calibration_frequency_days next_calibration_date range_min range_max resolution accuracy unit state'),
    'iatf.msa.study': spec('study_date', 'name study_date product_id instrument_id study_type pct_grr grr_status ndc responsible_id state',
        lines=('measurement_ids', 'operator_id part_number trial_number measured_value reference_value'), scopes={'iatf.measurement.equipment': 'instrument_id'}),
    'iatf.incoming.inspection': spec('inspection_date', 'name inspection_date product_id lot_id supplier_id picking_id quantity_inspected quantity_accepted quantity_rejected result inspector_id state certificate_plant certificate_lot_name certificate_expiry_date',
        lines=('line_ids', 'characteristic_name specification measured_value result notes')),
    'iatf.process.inspection': spec('inspection_date', 'name inspection_date product_id lot_id production_id inspection_type inspector_id result state', lines=('line_ids', 'characteristic_name specification measured_value result notes')),
    'iatf.shipping.inspection': spec('shipping_date', 'name shipping_date product_id lot_id partner_id picking_id visual_result dimension_result packaging_result label_result result inspector_id approved_by state'),
    'iatf.blend.log': spec('blend_date', 'name blend_date product_id lot_id standard_id ratio_basis limit_ratio virgin_qty regrind_qty total_qty regrind_ratio additive_ratio result state', lines=('line_ids', 'material_type product_id lot_id qty regrind_log_id note')),
    'iatf.regrind.log': spec('regrind_date', 'name regrind_date source_product_id source_type output_lot_id input_qty output_qty loss_qty yield_ratio foreign_check foreign_action storage_location output_move_id state'),
    'iatf.blend.standard': spec(False, 'name product_id material_id ratio_basis max_regrind_ratio max_additive_ratio customer_approved effective_date evidence_state evidence_revision'),
    'iatf.packaging.spec': spec(False, 'name product_id inner_packaging_type inner_quantity inner_dimension outer_packaging_type outer_quantity outer_dimension pallet_stack total_per_pallet flow_direction t1_date automation_ready_date evidence_state evidence_revision'),
    'iatf.jig': spec(False, 'name code jig_type product_id process_name state use_blocked'),
    'iatf.jig.record': spec('record_date', 'name jig_id record_date responsible_id status remarks cleanliness seating shape surface bolts measured_1_mm measured_2_mm measured_3_mm measured_4_mm evidence_state evidence_revision', scopes={'iatf.jig': 'jig_id'}),
    'iatf.drawing.conformity.check': spec('record_date', 'name record_date agreement_document_id planned_date checked_date actual_drawing_number actual_revision actual_agreement_number product_id lot_id result action_note evidence_state evidence_revision'),
    'cams.limit.sample.check': spec('record_date', 'name record_date sample_document_id product_id lot_id responsible_id result evidence_state evidence_revision'),
    'cams.periodic.test': spec('record_date', 'name record_date plan_document_id planned_date actual_date product_id lot_id sample_count result result_note evidence_state evidence_revision'),
    'cams.dryer.check': spec('record_date', 'name record_date equipment_id standard_document_id product_id lot_id temperature remaining_kg hourly_usage_kg capacity_kg lower_level_kg dryer_started_at production_started_at moisture_before_ppm moisture_1h_ppm moisture_2h_ppm moisture_3h_ppm filter_result result evidence_state evidence_revision', scopes={'iatf.equipment': 'equipment_id'}, grid=True),
    'cams.dryer.filter.log': spec('record_date', 'name record_date equipment_id operation completed_detail next_due_date responsible_id note evidence_state evidence_revision', scopes={'iatf.equipment': 'equipment_id'}),
    'cams.grinder.check': spec('record_date', 'name record_date equipment_id blade_gap_mm ground_since_change_kg cleanliness foreign_material gear_oil result evidence_state evidence_revision', scopes={'iatf.equipment': 'equipment_id'}, grid=True),
    'cams.grind.sample': spec('record_date', 'name record_date product_id lot_id equipment_id sample_volume_ml maximum_particle_mm regrind_log_id result evidence_state evidence_revision', scopes={'iatf.equipment': 'equipment_id'}),
    'cams.container.clean': spec('record_date', 'name record_date spec_id product_id lot_id quarter cleanliness damage identification mixed_parts actual_container_type actual_quantity result evidence_state evidence_revision', scopes={'iatf.packaging.spec': 'spec_id'}),
    'cams.quality.activity': spec('record_date', 'name record_date plan_document_id department_id responsible_id training_ids result_note improvement_type improvement_note award_month evidence_state evidence_revision'),
    'iatf.document': spec(False, 'doc_number name doc_type current_revision revision_date owner_id reviewer_id review_date approver_id approval_date state'),
    'iatf.change.request': spec('request_date', 'name title request_date change_type reason affected_product_ids requested_by customer_approval actual_date verification_result state'),
    'iatf.audit': spec('actual_date', 'name title planned_date actual_date audit_type lead_auditor_id state', lines=('finding_ids', 'finding_type clause_reference description objective_evidence responsible_id state')),
    'iatf.nonconformity': spec('detection_date', 'name title detection_date product_id lot_id problem_description severity preventive_action verification_result disposition quantity_affected quantity_rejected state', lines=('corrective_action_ids', 'name description responsible_id due_date state')),
    'iatf.control.plan': spec(False, 'name product_id revision state', lines=('line_ids', 'process_step_number process_name characteristic_name specification special_characteristic control_method reaction_plan')),
    'iatf.fmea': spec(False, 'name product_id revision state', lines=('line_ids', 'process_step process_function failure_mode failure_effect severity occurrence detection rpn recommended_action')),
    'mrp.production': spec('date_start', 'name date_start date_finished product_id lot_producing_id product_qty qty_produced state', lines=('move_raw_ids', 'product_id product_uom_qty quantity state')),
    'iatf.safety.assessment': spec('assess_date', 'name title assess_date work_area_id leader_id state', lines=('line_ids', 'hazard likelihood severity risk_level measure action_state')),
    'iatf.equipment': spec(False, 'name code serial_number manufacturer model_name location state'),
    'injection.mold': spec(False, 'name code current_shots dev_shots dev_shots_in_counter storage_location grade next_pm_shots next_clean_due'),
}

BASE_COLUMNS = 'record_date product_id lot_id workcenter_id responsible_id evidence_revision evidence_state state approval_state'.split()
SOURCE_MODELS = sorted(set(SPECS) | {model for item in SPECS.values() for model in item['scopes']})
