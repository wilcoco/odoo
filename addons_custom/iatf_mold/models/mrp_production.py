from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    mold_id = fields.Many2one("injection.mold", string="금형", tracking=True)

    def button_mark_done(self):
        res = super().button_mark_done()
        for production in self:
            if production.state == "done" and production.mold_id and not production._mold_shots_counted_elsewhere():
                production._update_mold_shots()
        return res

    def _mold_shots_counted_elsewhere(self):
        """사출 현장 MO(계획·단위)는 현장 실적 API 가 샷마다 같은 금형의 current_shots 를 올린다.

        금형 마스터가 하나(injection.mold)가 된 뒤에는 여기서 또 더하면 같은 샷이 두 번
        누적된다. 사출 현장 모듈이 없는 환경(필드 없음)에서는 기존대로 여기서 누적한다.
        """
        self.ensure_one()
        return bool(self._fields.get("is_injection_mo") and self.is_injection_mo)

    def _update_mold_shots(self):
        """MO 완료 시 금형 타수 자동 누적"""
        mold = self.mold_id
        shots = int(self.qty_produced) or 1
        new_total = mold.current_shots + shots
        mold.write({"current_shots": new_total})
        mold.message_post(
            body=_("MO %s 완료 → 타수 +%d (누적: %d)") % (self.name, shots, new_total)
        )
        _logger.info("Mold %s shots updated: +%d = %d (from MO %s)",
                     mold.code, shots, new_total, self.name)

        # 수명 경고 체크
        if mold.guaranteed_shots and new_total >= mold.guaranteed_shots * 0.9:
            mold.activity_schedule(
                "mail.mail_activity_data_warning",
                summary=_("금형 수명 90%% 도달: %s (%d/%d)") % (
                    mold.name, new_total, mold.guaranteed_shots),
                user_id=mold.responsible_id.id or self.env.user.id,
            )
