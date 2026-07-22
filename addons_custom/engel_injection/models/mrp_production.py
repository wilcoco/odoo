from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    car_model_id = fields.Many2one(
        "engel.car.model", string="차종", tracking=True,
    )

    @api.onchange("product_id")
    def _onchange_product_set_injection_defaults(self):
        """품목 선택 시 차종 자동 입력 + 금형 필터링"""
        if not self.product_id:
            self.mold_id = False
            return
        # 차종 자동 입력: 제품 템플릿의 기본 차종
        if self.product_id.product_tmpl_id.default_car_model_id:
            self.car_model_id = self.product_id.product_tmpl_id.default_car_model_id.id
        # 금형: 기존 선택 초기화 (제품 바뀌면 금형도 리셋)
        self.mold_id = False
        # 금형 드롭다운을 해당 제품용 활성 금형만 필터링
        return {
            "domain": {
                "mold_id": [
                    ("product_id", "=", self.product_id.id),
                    ("state", "=", "active"),
                ]
            }
        }

    def _generate_lot_name(self):
        """LOT 번호 자동 생성: LOT-YYYYMM-NNNN"""
        seq = self.env["ir.sequence"].next_by_code("engel.production.lot")
        return seq or ("LOT-%s" % fields.Date.today().strftime("%Y%m%d"))

    def action_confirm(self):
        """MO 확정 시 LOT 자동 생성"""
        res = super().action_confirm()
        for production in self:
            # 사출 MO/사출품 제외 — lot·시리얼 발행은 escon_serial(14자리 규칙) 소관.
            # 여기서 임의 명명(LOT-YYYYMM)하면 규칙 밖 lot 이 생겨 스캔/추적 체계가 깨진다.
            # (2-tier: 계획 MO 는 실물 lot 을 갖지 않고 단위 MO 가 발행받는다)
            # Engel 사출 금형이 지정된 MO에만 이 모듈의 LOT 규칙을 적용한다.
            # 모듈이 설치되어 있다는 이유만으로 조립 등 일반 MO에 LOT을
            # 자동 부여하면 안 된다. (원도영 09a5d47 포팅 — 정본은 이 사본)
            if not production.mold_id or production.mold_id.mold_type != "injection":
                continue
            if getattr(production, "is_injection_mo", False) or \
                    getattr(production.product_id, "is_injection_part", False):
                continue
            if (
                production.product_id.tracking in ("lot", "serial")
                and not production.lot_producing_id
            ):
                lot = self.env["stock.lot"].create(
                    {
                        "name": production._generate_lot_name(),
                        "product_id": production.product_id.id,
                        "company_id": production.company_id.id,
                    }
                )
                production.lot_producing_id = lot.id
                _logger.info(
                    "Auto-created LOT %s for MO %s", lot.name, production.name
                )
        return res

    injection_serial_ids = fields.One2many(
        "engel.injection.serial", "production_id", string="사출 시리얼",
    )
    injection_serial_count = fields.Integer(
        string="시리얼 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_ok_count = fields.Integer(
        string="합격 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_ng_count = fields.Integer(
        string="불합격 수",
        compute="_compute_injection_stats",
        store=True,
    )
    injection_defect_rate = fields.Float(
        string="불량률 (%)",
        compute="_compute_injection_stats",
        store=True,
    )

    @api.depends("injection_serial_ids", "injection_serial_ids.qc_result")
    def _compute_injection_stats(self):
        for rec in self:
            serials = rec.injection_serial_ids
            total = len(serials)
            ok = len(serials.filtered(lambda s: s.qc_result == "ok"))
            ng = total - ok
            rec.injection_serial_count = total
            rec.injection_ok_count = ok
            rec.injection_ng_count = ng
            rec.injection_defect_rate = (ng / total * 100.0) if total else 0.0

    def action_view_injection_serials(self):
        """사출 시리얼 레코드 목록 열기"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "engel.injection.serial",
            "view_mode": "list,form",
            "domain": [("production_id", "=", self.id)],
            "name": _("사출 시리얼"),
            "context": {
                "default_production_id": self.id,
                "default_product_id": self.product_id.id,
                "default_car_model_id": self.car_model_id.id if self.car_model_id else False,
                "default_mold_id": self.mold_id.id if self.mold_id else False,
            },
        }

    def _update_mold_shots(self):
        """금형 샷카운트: 사출 시리얼이 이미 추적한 경우 중복 방지"""
        if self.injection_serial_ids:
            _logger.info(
                "Skipping bulk mold shot update for MO %s "
                "— shots already tracked via injection serials",
                self.name,
            )
            return
        return super()._update_mold_shots()
