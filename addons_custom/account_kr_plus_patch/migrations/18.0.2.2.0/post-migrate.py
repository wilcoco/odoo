def migrate(cr, version):
    """Preserve the compatible setting from the previous module version."""
    cr.execute("""
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'res_company'
           AND column_name IN (
               'kr_use_custom_move_sequence',
               'kr_move_sequence_format',
               'kr_move_sequence_rule'
           )
    """)
    columns = {row[0] for row in cr.fetchall()}
    if {
        "kr_use_custom_move_sequence",
        "kr_move_sequence_format",
        "kr_move_sequence_rule",
    } <= columns:
        cr.execute("""
            UPDATE res_company
               SET kr_move_sequence_rule = CASE
                   WHEN kr_use_custom_move_sequence IS TRUE
                    AND kr_move_sequence_format = 'legacy'
                   THEN 'date_number_type'
                   ELSE 'odoo'
               END
        """)
