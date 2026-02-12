from odoo import api, fields, models, _


class IatfAuditFinding(models.Model):
    _name = "iatf.audit.finding"
    _description = "Audit Finding"
    _order = "finding_type, id"

    audit_id = fields.Many2one(
        "iatf.audit", string="Audit", required=True, ondelete="cascade", index=True,
    )
    finding_type = fields.Selection(
        [
            ("major", "Major Nonconformity"),
            ("minor", "Minor Nonconformity"),
            ("observation", "Observation / OFI"),
            ("positive", "Positive Finding"),
        ],
        string="Finding Type", required=True, default="minor",
    )
    clause_reference = fields.Char(string="Clause / Requirement")
    description = fields.Html(string="Finding Description", required=True)
    objective_evidence = fields.Html(string="Objective Evidence")
    responsible_id = fields.Many2one("res.users", string="Responsible")
    due_date = fields.Date(string="Due Date")

    # ── Corrective action link ──
    nonconformity_id = fields.Many2one(
        "iatf.nonconformity", string="Linked NC/CAPA",
        help="Link to a Nonconformity / 8D for corrective action tracking.",
    )

    state = fields.Selection(
        [
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("closed", "Closed"),
        ],
        string="Status", default="open",
    )
    closure_notes = fields.Text(string="Closure Notes")
    attachment_ids = fields.Many2many("ir.attachment", string="Evidence")

    def action_close(self):
        self.write({"state": "closed"})

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("Audit Finding: %s") % (self.clause_reference or self.audit_id.name),
            "nc_type": "audit",
            "severity": "major" if self.finding_type == "major" else "minor",
            "problem_description": self.description,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }
