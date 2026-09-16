from odoo import api, models


class ApprovalRequest(models.Model):
    _inherit = 'iatf.approval.request'

    @api.model
    def _approval_management_roles(self):
        return dict(super()._approval_management_roles(), **{
            'iatf.process.inspection': 'iatf_process_inspection.group_process_inspection_user',
        })


class ProcessInspection(models.Model):
    _inherit = 'iatf.process.inspection'

    def _approval_snapshot(self):
        self.ensure_one()
        snapshot = super()._approval_snapshot()
        snapshot.update({
            'company_id': self.company_id.id, 'product_id': self.product_id.id,
            'lot_id': self.lot_id.id, 'result': self.result, 'disposition': self.disposition,
            'quantity_inspected': self.quantity_inspected,
            'lines': self.line_ids.read(['sequence', 'characteristic_name', 'specification',
                                        'measurement_method', 'measured_value', 'result', 'notes']),
        })
        return snapshot

    def _invalidate_inspection_approval(self):
        for inspection in self.filtered(lambda r: r.approval_state in ('approved', 'in_progress')):
            inspection.action_reset_approval()
            inspection.message_post(body='검사 항목이 변경되어 새 결재 버전을 만들었습니다. 재상신해 주세요.')


class ProcessInspectionLine(models.Model):
    _inherit = 'iatf.process.inspection.line'

    def _lock_inspections(self, inspections):
        inspections.check_access('write')
        inspections._approval_lock()

    @api.model_create_multi
    def create(self, vals_list):
        default_parent = self.default_get(['inspection_id']).get('inspection_id')
        inspections = self.env['iatf.process.inspection'].browse([
            v.get('inspection_id', default_parent) for v in vals_list if v.get('inspection_id', default_parent)])
        self._lock_inspections(inspections)
        lines = super().create(vals_list)
        lines.inspection_id._invalidate_inspection_approval()
        return lines

    def write(self, vals):
        inspections = self.inspection_id | self.env['iatf.process.inspection'].browse(vals.get('inspection_id', []))
        self._lock_inspections(inspections)
        result = super().write(vals)
        if vals:
            inspections._invalidate_inspection_approval()
        return result

    def unlink(self):
        inspections = self.inspection_id
        self._lock_inspections(inspections)
        result = super().unlink()
        inspections._invalidate_inspection_approval()
        return result
