{
    'name': '품질·SQ 원천 조회 권한',
    'version': '18.0.1.0.0',
    'license': 'LGPL-3',
    # Integration profile for the installed factory stack. All source models must
    # be loaded before creating ACLs; cams_sq itself keeps its minimal dependency.
    'depends': [
        'cams_sq', 'iatf_process_inspection', 'iatf_work_environment',
        'iatf_control_plan', 'iatf_fmea', 'iatf_traceability',
        'iatf_incoming_inspection', 'iatf_document_control', 'iatf_calibration',
        'iatf_msa', 'iatf_shipping_inspection', 'iatf_equipment', 'iatf_mold',
        'iatf_packaging', 'iatf_change_management', 'iatf_management_review',
        'iatf_training', 'iatf_nonconformity', 'iatf_quality_objective',
        'injection_worksite', 'injection_costing', 'injection_rawmaterial',
        'injection_quality_standard', 'gh_total_mes', 'mrp_bom_scan_guard',
    ],
    'data': ['security/access.xml'],
    'installable': True,
    'application': False,
}
