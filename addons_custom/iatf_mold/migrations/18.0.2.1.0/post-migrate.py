"""Reject business changes; restore only audit metadata of pre-existing rows."""
TABLES = ('iatf_mold_tryout', 'iatf_mold_maintenance', 'iatf_mold_temp_log')


def migrate(cr, version):
    for table in TABLES:
        cr.execute('''SELECT b.record_id FROM sq_mold_pre_p1 b
            LEFT JOIN '''+table+''' t ON t.id=b.record_id
            WHERE b.source_table=%s AND (t.id IS NULL OR EXISTS (
                SELECT 1 FROM jsonb_each(b.before_row) old
                WHERE old.key NOT IN ('write_uid','write_date')
                AND old.value IS DISTINCT FROM (to_jsonb(t)->old.key))) LIMIT 1''', [table])
        if cr.fetchone():
            raise RuntimeError('P1 mold upgrade changed an existing business field: '+table)
        cr.execute('''UPDATE '''+table+''' t SET
            write_uid=(b.before_row->>'write_uid')::integer,
            write_date=(b.before_row->>'write_date')::timestamp
            FROM sq_mold_pre_p1 b WHERE b.source_table=%s AND b.record_id=t.id''', [table])
