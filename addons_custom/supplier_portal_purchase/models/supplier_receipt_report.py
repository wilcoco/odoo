from odoo import api, models


class SupplierReceiptReport(models.AbstractModel):
    """납품 인수확인서 PDF — 입고 전표 기반, 수입검사(IQC) 결과 병기.

    iatf_incoming_inspection 미설치 환경에서도 동작하도록 registry 존재 검사로 가드.
    """
    _name = "report.supplier_portal_purchase.report_supplier_receipt"
    _description = "납품 인수확인서 리포트"

    @api.model
    def _get_report_values(self, docids, data=None):
        pickings = self.env["stock.picking"].browse(docids)
        iqc_map = {}
        if "iatf.incoming.inspection" in self.env:
            IQC = self.env["iatf.incoming.inspection"].sudo()
            lot_ids = pickings.move_line_ids.mapped("lot_id").ids
            if lot_ids:
                state_labels = dict(
                    IQC._fields["state"]._description_selection(self.env))
                result_labels = dict(
                    IQC._fields["result"]._description_selection(self.env)
                ) if "result" in IQC._fields else {}
                for insp in IQC.search([("lot_id", "in", lot_ids)]):
                    label = state_labels.get(insp.state, insp.state)
                    if insp.result and result_labels:
                        label = "%s(%s)" % (
                            label, result_labels.get(insp.result, insp.result))
                    iqc_map[insp.lot_id.id] = label
        return {
            "doc_ids": docids,
            "doc_model": "stock.picking",
            "docs": pickings,
            "iqc_map": iqc_map,
        }
