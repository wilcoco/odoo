from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    # ── IATF 연결 카운트 (스마트버튼용) ──
    iatf_fmea_count = fields.Integer(compute="_compute_iatf_counts", string="FMEA")
    iatf_control_plan_count = fields.Integer(compute="_compute_iatf_counts", string="CP")
    iatf_spc_count = fields.Integer(compute="_compute_iatf_counts", string="SPC")
    iatf_ppap_count = fields.Integer(compute="_compute_iatf_counts", string="PPAP")
    iatf_nc_count = fields.Integer(compute="_compute_iatf_counts", string="NC")
    iatf_inspection_count = fields.Integer(compute="_compute_iatf_counts", string="검사")
    iatf_complaint_count = fields.Integer(compute="_compute_iatf_counts", string="고객불만")
    iatf_msa_count = fields.Integer(compute="_compute_iatf_counts", string="MSA")

    def _get_product_variant_ids(self):
        return self.product_variant_ids.ids

    def _compute_iatf_counts(self):
        for tmpl in self:
            pids = tmpl._get_product_variant_ids()

            FMEA = self.env.get("iatf.fmea")
            tmpl.iatf_fmea_count = FMEA.search_count(
                [("product_id", "in", pids)]) if FMEA else 0

            CP = self.env.get("iatf.control.plan")
            tmpl.iatf_control_plan_count = CP.search_count(
                [("product_id", "in", pids)]) if CP else 0

            SPC = self.env.get("iatf.spc.study")
            tmpl.iatf_spc_count = SPC.search_count(
                [("product_id", "in", pids)]) if SPC else 0

            PPAP = self.env.get("iatf.ppap.submission")
            tmpl.iatf_ppap_count = PPAP.search_count(
                [("product_id", "in", pids)]) if PPAP else 0

            NC = self.env.get("iatf.nonconformity")
            tmpl.iatf_nc_count = NC.search_count(
                [("product_id", "in", pids)]) if NC else 0

            PQC = self.env.get("iatf.process.inspection")
            IQC = self.env.get("iatf.incoming.inspection")
            insp = 0
            if PQC is not None:
                insp += PQC.search_count([("product_id", "in", pids)])
            if IQC:
                insp += IQC.search_count([("product_id", "in", pids)])
            tmpl.iatf_inspection_count = insp

            CC = self.env.get("iatf.customer.complaint")
            tmpl.iatf_complaint_count = CC.search_count(
                [("product_id", "in", pids)]) if CC else 0

            MSA = self.env.get("iatf.msa.study")
            tmpl.iatf_msa_count = MSA.search_count(
                [("product_id", "in", pids)]) if MSA else 0

    # ── 스마트버튼 액션 ──
    def _iatf_action(self, res_model, name):
        pids = self._get_product_variant_ids()
        return {
            "type": "ir.actions.act_window",
            "res_model": res_model,
            "view_mode": "list,form",
            "domain": [("product_id", "in", pids)],
            "name": name,
            "context": {"default_product_id": pids[0] if pids else False},
        }

    def action_view_iatf_fmea(self):
        return self._iatf_action("iatf.fmea", _("FMEA"))

    def action_view_iatf_control_plan(self):
        return self._iatf_action("iatf.control.plan", _("관리계획서"))

    def action_view_iatf_spc(self):
        return self._iatf_action("iatf.spc.study", _("SPC"))

    def action_view_iatf_ppap(self):
        return self._iatf_action("iatf.ppap.submission", _("PPAP"))

    def action_view_iatf_nc(self):
        return self._iatf_action("iatf.nonconformity", _("부적합"))

    def action_view_iatf_inspection(self):
        pids = self._get_product_variant_ids()
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.process.inspection",
            "view_mode": "list,form",
            "domain": [("product_id", "in", pids)],
            "name": _("검사"),
        }

    def action_view_iatf_complaint(self):
        return self._iatf_action("iatf.customer.complaint", _("고객불만"))

    def action_view_iatf_msa(self):
        return self._iatf_action("iatf.msa.study", _("MSA"))
