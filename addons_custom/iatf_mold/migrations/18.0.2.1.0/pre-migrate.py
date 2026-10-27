"""Preserve existing mold ledgers while new related aliases are initialized."""
TABLES = ('iatf_mold_tryout', 'iatf_mold_maintenance', 'iatf_mold_temp_log')


def migrate(cr, version):
    cr.execute('CREATE TEMP TABLE sq_mold_pre_p1 (source_table text, record_id integer, before_row jsonb) ON COMMIT DROP')
    for table in TABLES:
        # Identifiers are fixed code constants, never user data.
        cr.execute('INSERT INTO sq_mold_pre_p1 SELECT %s, id, to_jsonb(t) FROM '+table+' t', [table])
