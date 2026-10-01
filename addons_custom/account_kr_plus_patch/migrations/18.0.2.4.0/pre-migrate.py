def migrate(cr, version):
    """Discard all legacy transient rows before creating the global singleton."""
    cr.execute("SELECT to_regclass('public.account_kr_plus_settings')")
    if cr.fetchone()[0]:
        cr.execute("DELETE FROM account_kr_plus_settings")
