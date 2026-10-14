def migrate(cr, version):
    """Undo the old bundled redirect when the optional redirect addon is absent."""
    cr.execute(
        """
        SELECT state
          FROM ir_module_module
         WHERE name = 'escon_mainmenu_do_redirect'
        """
    )
    redirect_module = cr.fetchone()
    if redirect_module and redirect_module[0] in {"installed", "to upgrade"}:
        return

    cr.execute(
        """
        UPDATE res_users
           SET action_id = NULL
         WHERE action_id = (
               SELECT res_id
                 FROM ir_model_data
                WHERE module = 'escon_mainmenu'
                  AND name = 'action_escon_mainmenu'
                  AND model = 'ir.actions.client'
                LIMIT 1
         )
        """
    )
