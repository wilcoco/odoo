from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class EngelInjectionSerial(models.Model):
    _name = "engel.injection.serial"
    _description = "사출 생산 시리얼 레코드"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "produced_at desc, id desc"
    _rec_name = "barcode"

    # ── 식별 ──
    barcode = fields.Char(
        string="바코드",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _("New"),
        index=True,
    )
    serial_no = fields.Char(string="시리얼 번호", index=True)

    # ── 생산 참조 ──
    production_id = fields.Many2one(
        "mrp.production", string="제조 오더", index=True, tracking=True,
    )
    product_id = fields.Many2one(
        "product.product", string="제품", required=True, tracking=True,
    )
    lot_id = fields.Many2one(
        "stock.lot", string="로트", index=True, tracking=True,
    )
    car_model_id = fields.Many2one(
        "engel.car.model", string="차종", tracking=True,
    )

    # ── 금형 ──
    mold_id = fields.Many2one("iatf.mold", string="금형", tracking=True)
    mold_cavity = fields.Integer(string="캐비티 번호")

    # ── 작업자 / 근무조 ──
    operator_id = fields.Many2one("hr.employee", string="작업자", tracking=True)
    shift = fields.Selection(
        [("A", "A조"), ("B", "B조"), ("C", "C조")],
        string="근무조",
    )

    # ── 사출 파라미터 ──
    weight = fields.Float(string="중량 (g)", digits=(16, 2))
    cycle_time = fields.Float(string="사이클 타임 (초)", digits=(16, 2))
    inject_pressure = fields.Float(string="사출 압력 (bar)", digits=(16, 1))
    hold_pressure = fields.Float(string="보압 (bar)", digits=(16, 1))
    barrel_temp = fields.Float(string="배럴 온도 (°C)", digits=(16, 1))
    mold_temp = fields.Float(string="금형 온도 (°C)", digits=(16, 1))
    cushion = fields.Float(string="쿠션 (mm)", digits=(16, 2))

    # ── 품질 ──
    qc_result = fields.Selection(
        [("ok", "합격"), ("ng", "불합격")],
        string="품질 판정",
        default="ok",
        tracking=True,
    )
    defect_type_id = fields.Many2one("engel.defect.type", string="불량 유형")

    # ── 시각 / 상태 ──
    produced_at = fields.Datetime(
        string="생산 시각", default=fields.Datetime.now, index=True,
    )
    status = fields.Selection(
        [
            ("produced", "생산"),
            ("inspected", "검사완료"),
            ("shipped", "출하"),
        ],
        string="상태",
        default="produced",
        tracking=True,
    )

    # ── 추적 연결 ──
    traceability_record_id = fields.Many2one(
        "iatf.traceability.record", string="추적 기록", readonly=True,
    )

    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company,
    )

    _sql_constraints = [
        ("barcode_uniq", "unique(barcode)", "바코드는 고유해야 합니다."),
    ]

    # ─────────────────────────────────────────────
    # CRUD
    # ─────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("barcode", _("New")) == _("New"):
                vals["barcode"] = (
                    self.env["ir.sequence"].next_by_code("engel.injection.serial")
                    or _("New")
                )
        records = super().create(vals_list)
        if not self.env.context.get("skip_injection_hooks"):
            for rec in records:
                rec._post_create_hooks()
        return records

    # ─────────────────────────────────────────────
    # 자동 처리 훅
    # ─────────────────────────────────────────────
    def _post_create_hooks(self):
        """시리얼 생성 후: 금형 샷카운트, 추적 기록, SPC 피드"""
        self._update_mold_shots()
        self._create_traceability_record()
        self._auto_feed_spc()

    def _update_mold_shots(self):
        """금형 샷카운트 +1 (캐비티 1번이거나 단일 캐비티일 때만)"""
        if not self.mold_id:
            return
        mold = self.mold_id
        if mold.cavity_count <= 1 or self.mold_cavity == 1:
            new_total = mold.current_shots + 1
            mold.sudo().write({"current_shots": new_total})
            _logger.info(
                "Mold %s shot +1 (total: %d) from injection serial %s",
                mold.code, new_total, self.barcode,
            )
            # 수명 90% 경고
            if mold.guaranteed_shots and new_total >= mold.guaranteed_shots * 0.9:
                mold.activity_schedule(
                    "mail.mail_activity_data_warning",
                    summary=_("금형 수명 90%% 도달: %s (%d/%d)")
                    % (mold.name, new_total, mold.guaranteed_shots),
                    user_id=mold.responsible_id.id or self.env.user.id,
                )

    def _create_traceability_record(self):
        """iatf.traceability.record 자동 생성 + 공정 파라미터"""
        TraceRecord = self.env.get("iatf.traceability.record")
        if TraceRecord is None:
            return
        operator_user_id = False
        if self.operator_id and self.operator_id.user_id:
            operator_user_id = self.operator_id.user_id.id
        vals = {
            "product_id": self.product_id.id,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "production_id": self.production_id.id if self.production_id else False,
            "process_step": _("사출 성형"),
            "operator_id": operator_user_id or self.env.user.id,
            "quantity": 1,
            "parameter_ids": self._prepare_trace_parameters(),
        }
        try:
            rec = TraceRecord.create(vals)
            self.traceability_record_id = rec.id
            _logger.info(
                "Traceability record %s auto-created from injection serial %s",
                rec.name, self.barcode,
            )
        except Exception:
            _logger.exception(
                "Failed to create traceability record for serial %s",
                self.barcode,
            )

    def _prepare_trace_parameters(self):
        """사출 공정 파라미터를 추적 파라미터 레코드로 변환"""
        params = []
        param_map = [
            ("중량", self.weight, "g"),
            ("사이클 타임", self.cycle_time, "sec"),
            ("사출 압력", self.inject_pressure, "bar"),
            ("보압", self.hold_pressure, "bar"),
            ("배럴 온도", self.barrel_temp, "°C"),
            ("금형 온도", self.mold_temp, "°C"),
            ("쿠션", self.cushion, "mm"),
        ]
        for name, value, unit in param_map:
            if value:
                params.append(
                    (0, 0, {"name": name, "actual_value": value, "unit": unit})
                )
        return params

    def _auto_feed_spc(self):
        """활성 SPC 연구에 중량 데이터 자동 투입"""
        SpcStudy = self.env.get("iatf.spc.study")
        if SpcStudy is None or not self.weight:
            return
        try:
            studies = SpcStudy.search([
                ("product_id", "=", self.product_id.id),
                ("characteristic_name", "=", "중량"),
                ("state", "=", "collecting"),
            ])
            for study in studies:
                next_seq = (
                    max(study.subgroup_ids.mapped("sequence"), default=0) + 1
                )
                self.env["iatf.spc.subgroup"].create({
                    "study_id": study.id,
                    "sequence": next_seq,
                    "sample_date": self.produced_at,
                    "x1": self.weight,
                })
        except Exception:
            _logger.exception(
                "Failed to feed SPC for serial %s", self.barcode,
            )
