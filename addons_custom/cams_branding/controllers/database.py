import re

from lxml import html

import odoo
from odoo import http
from odoo.addons.base.models.ir_qweb import render as qweb_render
from odoo.http import request
from odoo.tools.misc import file_open

from odoo.addons.web.controllers.database import DBNAME_PATTERN
from odoo.addons.web.controllers.database import Database as WebDatabase


class Database(WebDatabase):

    def _patch_database_manager_template(self, template):
        template = re.sub(r"<title>[^<]*</title>", "<title>ESCON ERP</title>", template, count=1)
        template = template.replace("/web/static/img/favicon.ico", "/cams_branding/static/src/img/favicon.svg")
        template = template.replace('type="image/x-icon"', 'type="image/svg+xml"')
        template = template.replace("/web/static/img/logo2.png", "/cams_branding/static/src/img/logo.svg")
        return template

    def _render_template(self, **d):
        d.setdefault("manage", True)
        d["insecure"] = odoo.tools.config.verify_admin_password("admin")
        d["list_db"] = odoo.tools.config["list_db"]
        d["langs"] = odoo.service.db.exp_list_lang()
        d["countries"] = odoo.service.db.exp_list_countries()
        d["pattern"] = DBNAME_PATTERN
        try:
            d["databases"] = http.db_list()
            d["incompatible_databases"] = odoo.service.db.list_db_incompatible(d["databases"])
        except odoo.exceptions.AccessDenied:
            d["databases"] = [request.db] if request.db else []

        templates = {}

        with file_open("web/static/src/public/database_manager.qweb.html", "r") as fd:
            templates["database_manager"] = self._patch_database_manager_template(fd.read())
        with file_open("web/static/src/public/database_manager.master_input.qweb.html", "r") as fd:
            templates["master_input"] = fd.read()
        with file_open("web/static/src/public/database_manager.create_form.qweb.html", "r") as fd:
            templates["create_form"] = fd.read()

        def load(template_name):
            fromstring = (
                html.document_fromstring
                if template_name == "database_manager"
                else html.fragment_fromstring
            )
            return (fromstring(templates[template_name]), template_name)

        return qweb_render("database_manager", d, load)
