from odoo import api, fields, models, _


class IatfAuditFinding(models.Model):
    _name = "iatf.audit.finding"
    _description = "Audit Finding"
    _order = "finding_type, id"

    audit_id = fields.Many2one(
        "iatf.audit", string="심사", required=True, ondelete="cascade", index=True,
    )
    finding_type = fields.Selection(
        [
            ("major", "중대 부적합"),
            ("minor", "경미 부적합"),
            ("observation", "관찰사항 / 개선기회"),
            ("positive", "우수사항"),
        ],
        string="지적 유형", required=True, default="minor",
    )
    clause_reference = fields.Char(string="조항 / 요구사항")
    description = fields.Html(string="지적 내용", required=True)
    objective_evidence = fields.Html(string="객관적 증거")
    responsible_id = fields.Many2one("res.users", string="담당자")
    due_date = fields.Date(string="기한")

    # ── Corrective action link ──
    nonconformity_id = fields.Many2one(
        "iatf.nonconformity", string="연결된 부적합/시정조치",
        help="Link to a Nonconformity / 8D for corrective action tracking.",
    )

    state = fields.Selection(
        [
            ("open", "미결"),
            ("in_progress", "진행 중"),
            ("closed", "종료"),
        ],
        string="상태", default="open",
    )
    closure_notes = fields.Text(string="종료 기록")
    attachment_ids = fields.Many2many("ir.attachment", string="증빙")

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
