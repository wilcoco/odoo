import base64
import io
from odoo import api, fields, models, _
from odoo.exceptions import UserError

try:
    import openpyxl
except ImportError:
    openpyxl = None


class IatfExcelImport(models.TransientModel):
    _name = "iatf.excel.import"
    _description = "IATF Excel Data Import Wizard"

    import_type = fields.Selection(
        [
            ("fmea", "FMEA Worksheet"),
            ("control_plan", "Control Plan"),
            ("risk", "Risk Register"),
            ("equipment", "Measurement Equipment"),
            ("competence", "Competence Matrix"),
            ("nc", "Nonconformity Log"),
        ],
        string="Import Type", required=True, default="fmea",
    )
    file = fields.Binary(string="Excel File (.xlsx)", required=True)
    filename = fields.Char(string="Filename")

    # Parent record for FMEA / CP
    fmea_id = fields.Many2one("iatf.fmea", string="Target FMEA")
    control_plan_id = fields.Many2one("iatf.control.plan", string="Target Control Plan")

    result_message = fields.Text(string="Import Result", readonly=True)

    def action_import(self):
        self.ensure_one()
        if not openpyxl:
            raise UserError(_("Python library 'openpyxl' is required. Install it with: pip install openpyxl"))
        if not self.file:
            raise UserError(_("Please upload an Excel file."))

        data = base64.b64decode(self.file)
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        ws = wb.active

        handler = {
            "fmea": self._import_fmea,
            "control_plan": self._import_control_plan,
            "risk": self._import_risk,
            "equipment": self._import_equipment,
            "competence": self._import_competence,
            "nc": self._import_nc,
        }

        func = handler.get(self.import_type)
        if not func:
            raise UserError(_("Unknown import type."))

        count = func(ws)
        self.result_message = _("Successfully imported %d record(s) for '%s'.") % (
            count, dict(self._fields["import_type"].selection).get(self.import_type, ""))

        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }

    def _get_rows(self, ws):
        rows = list(ws.iter_rows(min_row=2, values_only=True))
        return [r for r in rows if any(c is not None for c in r)]

    def _import_fmea(self, ws):
        if not self.fmea_id:
            raise UserError(_("Please select a target FMEA document."))
        count = 0
        for row in self._get_rows(ws):
            vals = {
                "fmea_id": self.fmea_id.id,
                "process_step": str(row[0] or ""),
                "failure_mode": str(row[1] or ""),
                "failure_effect": str(row[2] or ""),
                "failure_cause": str(row[3] or ""),
                "current_prevention": str(row[4] or ""),
                "current_detection": str(row[5] or ""),
                "severity": int(row[6] or 1),
                "occurrence": int(row[7] or 1),
                "detection": int(row[8] or 1),
                "recommended_action": str(row[9] or "") if len(row) > 9 else "",
            }
            if row[10] if len(row) > 10 else None:
                sc_map = {"CC": "cc", "SC": "sc", "HI": "hi"}
                vals["special_characteristic"] = sc_map.get(str(row[10]).upper(), "none")
            self.env["iatf.fmea.line"].create(vals)
            count += 1
        return count

    def _import_control_plan(self, ws):
        if not self.control_plan_id:
            raise UserError(_("Please select a target Control Plan."))
        count = 0
        for i, row in enumerate(self._get_rows(ws)):
            vals = {
                "control_plan_id": self.control_plan_id.id,
                "sequence": (i + 1) * 10,
                "process_step_number": str(row[0] or ""),
                "process_name": str(row[1] or ""),
                "machine_device": str(row[2] or ""),
                "characteristic_number": str(row[3] or ""),
                "characteristic_name": str(row[4] or ""),
                "specification": str(row[5] or ""),
                "evaluation_method": str(row[6] or ""),
                "sample_size": str(row[7] or ""),
                "sample_frequency": str(row[8] or ""),
                "control_method": str(row[9] or "") if len(row) > 9 else "",
                "reaction_plan": str(row[10] or "") if len(row) > 10 else "",
            }
            self.env["iatf.control.plan.line"].create(vals)
            count += 1
        return count

    def _import_risk(self, ws):
        count = 0
        for row in self._get_rows(ws):
            type_map = {"risk": "risk", "opportunity": "opportunity"}
            cat_map = {"strategic": "strategic", "operational": "operational",
                       "quality": "quality", "supply_chain": "supply_chain",
                       "regulatory": "regulatory", "financial": "financial"}
            vals = {
                "title": str(row[0] or ""),
                "entry_type": type_map.get(str(row[1] or "").lower(), "risk"),
                "category": cat_map.get(str(row[2] or "").lower(), "quality"),
                "description": str(row[3] or ""),
                "likelihood": str(int(row[4] or 3)),
                "impact": str(int(row[5] or 3)),
                "treatment_strategy": str(row[6] or "mitigate").lower(),
                "current_controls": str(row[7] or "") if len(row) > 7 else "",
                "planned_actions": str(row[8] or "") if len(row) > 8 else "",
            }
            self.env["iatf.risk.register"].create(vals)
            count += 1
        return count

    def _import_equipment(self, ws):
        count = 0
        for row in self._get_rows(ws):
            type_map = {"caliper": "caliper", "micrometer": "micrometer", "gauge": "gauge",
                        "cmm": "cmm", "scale": "scale", "torque": "torque", "other": "other"}
            vals = {
                "name": str(row[0] or ""),
                "equipment_id_number": str(row[1] or ""),
                "equipment_type": type_map.get(str(row[2] or "").lower(), "other"),
                "manufacturer": str(row[3] or "") if len(row) > 3 else "",
                "serial_number": str(row[4] or "") if len(row) > 4 else "",
                "location": str(row[5] or "") if len(row) > 5 else "",
                "calibration_frequency_days": int(row[6] or 365) if len(row) > 6 else 365,
            }
            self.env["iatf.measurement.equipment"].create(vals)
            count += 1
        return count

    def _import_competence(self, ws):
        count = 0
        for row in self._get_rows(ws):
            emp_name = str(row[0] or "")
            employee = self.env["hr.employee"].search([("name", "ilike", emp_name)], limit=1)
            if not employee:
                continue
            vals = {
                "employee_id": employee.id,
                "skill_name": str(row[1] or ""),
                "skill_category": str(row[2] or "process").lower() if len(row) > 2 else "process",
                "required_level": str(int(row[3] or 3)) if len(row) > 3 else "3",
                "current_level": str(int(row[4] or 0)) if len(row) > 4 else "0",
            }
            self.env["iatf.competence.matrix"].create(vals)
            count += 1
        return count

    def _import_nc(self, ws):
        count = 0
        for row in self._get_rows(ws):
            type_map = {"internal": "internal", "supplier": "supplier",
                        "customer": "customer", "audit": "audit", "process": "process"}
            sev_map = {"critical": "critical", "major": "major", "minor": "minor"}
            vals = {
                "title": str(row[0] or ""),
                "nc_type": type_map.get(str(row[1] or "").lower(), "internal"),
                "severity": sev_map.get(str(row[2] or "").lower(), "minor"),
                "problem_description": str(row[3] or ""),
            }
            self.env["iatf.nonconformity"].create(vals)
            count += 1
        return count
