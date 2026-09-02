from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# 계층 단계. 값이 작을수록 상위다. 부모보다 반드시 아래 단계여야 한다
# (예외: 장치→장치 는 수리성 어셈블리 분해를 위해 허용).
NODE_RANK = {"plant": 0, "line": 1, "equipment": 2, "device": 3}

# 부모에게서 물려받을 위치/담당 필드. 장치를 새로 달 때 비어 있으면 부모 값을 채운다.
INHERITED_FROM_PARENT = ("workcenter_id", "department_id", "responsible_id", "location")


class IatfEquipment(models.Model):
    _name = "iatf.equipment"
    _description = "설비 대장 (IATF 16949 §8.5.1.5)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _parent_name = "parent_id"
    _parent_store = True
    _order = "complete_name, name"
    _rec_names_search = ["complete_name", "code", "serial_number"]

    name = fields.Char(string="설비명", required=True, tracking=True)
    code = fields.Char(
        string="설비 코드", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )

    # ── 계층 (공장 → 라인 → 설비 → 장치) ──
    node_type = fields.Selection(
        [
            ("plant", "공장"),
            ("line", "라인"),
            ("equipment", "설비"),
            ("device", "장치"),
        ],
        string="계층 구분", required=True, default="equipment", tracking=True,
        help="계층 깊이는 데이터가 정한다. 설비만 등록해도 되고 공장→라인→설비→장치까지 내려가도 된다.",
    )
    parent_id = fields.Many2one(
        "iatf.equipment", string="상위 설비", index=True, ondelete="restrict", tracking=True,
    )
    parent_path = fields.Char(index=True, unaccent=False)
    child_ids = fields.One2many("iatf.equipment", "parent_id", string="하위 장치")
    child_count = fields.Integer(string="하위 장치 수", compute="_compute_child_count")
    complete_name = fields.Char(
        string="전체 경로", compute="_compute_complete_name", recursive=True, store=True,
    )
    root_equipment_id = fields.Many2one(
        "iatf.equipment", string="소속 설비", compute="_compute_root_equipment",
        recursive=True, store=True, index=True,
        help="자기 자신 또는 가장 가까운 상위 중 계층 구분이 '설비'인 것. "
             "장치에서 발생한 고장·부품 출고를 설비 단위로 집계할 때 쓴다.",
    )

    equipment_type = fields.Selection(
        [
            ("production", "생산 설비"),
            ("assembly", "조립 설비"),
            ("test", "시험/검사 설비"),
            ("utility", "유틸리티"),
            ("transport", "운반 설비"),
            ("other", "기타"),
        ],
        string="설비 유형", required=True, default="production", tracking=True,
    )

    # ── 사양 ──
    manufacturer = fields.Char(string="제조사")
    model_name = fields.Char(string="모델명")
    serial_number = fields.Char(string="시리얼 번호")
    manufacture_year = fields.Char(string="제조 연도")
    purchase_date = fields.Date(string="구입일")
    install_date = fields.Date(string="설치일")
    capacity = fields.Char(string="능력/용량", help="예: 200톤, 1500rpm")
    specification = fields.Html(string="주요 사양")

    # ── 위치/담당 ──
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    location = fields.Char(string="설치 위치")
    department_id = fields.Many2one("hr.department", string="관리 부서")
    responsible_id = fields.Many2one("res.users", string="담당자", tracking=True)

    # ── TPM / 보전 ──
    pm_cycle_days = fields.Integer(string="PM 주기 (일)", default=90)
    last_pm_date = fields.Date(string="최근 PM 일자")
    next_pm_date = fields.Date(string="다음 PM 예정일", compute="_compute_next_pm", store=True)
    is_pm_overdue = fields.Boolean(string="PM 기한 초과", compute="_compute_next_pm", store=True)

    # ── 가동 이력 ──
    # 신뢰성 지표(MTBF/MTTR/가동률)의 정본은 이 모델이다. 표준 maintenance.mixin 도 같은 이름의
    # MTBF/MTTR 을 갖지만 (1) 단위가 '일'이고 (2) 달력 경과일 기준이라 TPM 지표가 아니다.
    # 표준 값은 maintenance.equipment 폼에서 숨기고 여기 값을 related 로 보여준다.
    total_runtime_hours = fields.Float(
        string="누적 가동 시간 (수기)",
        help="작업장 실적이 없을 때만 쓰는 보정값. 작업장이 연결돼 있으면 실적이 우선한다.",
    )
    runtime_hours_wc = fields.Float(
        string="작업장 실적 가동시간", compute="_compute_runtime",
        help="연결된 작업장의 생산(productive) 기록 합계 — mrp.workcenter.productivity",
    )
    runtime_hours = fields.Float(
        string="적용 가동시간", compute="_compute_runtime",
        help="작업장 실적 우선, 없으면 수기 입력값. 둘 다 없으면 신뢰성 지표를 산출하지 않는다.",
    )
    runtime_source = fields.Selection(
        [("workcenter", "작업장 실적"), ("manual", "수기"), ("none", "미집계")],
        string="가동시간 출처", compute="_compute_runtime",
    )

    breakdown_count = fields.Integer(string="고장 건수", compute="_compute_breakdown_stats", store=True)
    total_downtime_hours = fields.Float(string="누적 정지 시간", compute="_compute_breakdown_stats", store=True)
    mttr = fields.Float(string="MTTR (시간)", compute="_compute_breakdown_stats", store=True,
                         help="평균 수리 시간 = 누적 정지시간 / 완료된 고장 건수")
    # 가동시간은 외부 모델(작업장 실적)에서 오므로 저장하지 않는다.
    # 저장하면 실적이 쌓여도 갱신 트리거가 없어 옛 값이 남는다.
    # 주의: 아래 두 값의 0.0 은 '0%' 가 아니라 '산출 불가' 일 수 있다. Float 이라 두 경우를
    # 구분할 표현이 없으므로, 이 값을 읽는 쪽(리포트·엑셀·API·후속 코드)은 반드시
    # runtime_source 를 함께 확인해야 한다. runtime_source == 'none' 이면 0.0 은 미집계다.
    mtbf = fields.Float(
        string="MTBF (시간)", compute="_compute_reliability",
        help="평균 고장 간격 = 적용 가동시간 / 완료된 고장 건수.\n"
             "가동시간이 없으면(runtime_source='none') 산출하지 않고 0.0 을 반환한다 — "
             "이 0.0 은 '0시간' 이 아니라 '미집계' 다.",
    )
    availability_rate = fields.Float(
        string="가동률 (%)", compute="_compute_reliability",
        help="적용 가동시간 / (적용 가동시간 + 누적 정지시간) × 100.\n"
             "가동시간이 없으면(runtime_source='none') 산출하지 않고 0.0 을 반환한다 — "
             "이 0.0 은 '가동률 0%' 가 아니라 '미집계' 다.",
    )

    # ── 관련 기록 ──
    pm_schedule_ids = fields.One2many("iatf.pm.schedule", "equipment_id", string="PM 계획/실적")
    breakdown_ids = fields.One2many("iatf.equipment.breakdown", "equipment_id", string="고장 이력")
    daily_check_ids = fields.One2many("iatf.daily.check", "equipment_id", string="일상점검")
    spare_part_ids = fields.One2many("iatf.equipment.spare", "equipment_id", string="예비부품")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")
    image = fields.Binary(string="설비 사진")

    state = fields.Selection(
        [
            ("draft", "등록"),
            ("active", "가동 중"),
            ("maintenance", "보전 중"),
            ("breakdown", "고장"),
            ("inactive", "비가동"),
            ("disposed", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    # ── 계층 ──
    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for rec in self:
            if rec.parent_id:
                rec.complete_name = "%s / %s" % (rec.parent_id.complete_name, rec.name)
            else:
                rec.complete_name = rec.name

    @api.depends("node_type", "parent_id.root_equipment_id")
    def _compute_root_equipment(self):
        for rec in self:
            if rec.node_type == "equipment":
                rec.root_equipment_id = rec
            elif rec.parent_id:
                rec.root_equipment_id = rec.parent_id.root_equipment_id
            else:
                rec.root_equipment_id = False

    @api.depends("child_ids")
    def _compute_child_count(self):
        counts = {
            parent.id: count
            for parent, count in self.env["iatf.equipment"]._read_group(
                [("parent_id", "in", self.ids)], ["parent_id"], ["__count"]
            )
        }
        for rec in self:
            rec.child_count = counts.get(rec.id, 0)

    @api.constrains("parent_id")
    def _check_equipment_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("설비 계층이 순환됩니다. 자기 자신을 상위로 둘 수 없습니다."))

    @api.constrains("parent_id", "node_type")
    def _check_node_type_rank(self):
        for rec in self:
            if not rec.parent_id:
                continue
            child_rank = NODE_RANK[rec.node_type]
            parent_rank = NODE_RANK[rec.parent_id.node_type]
            # 장치 밑의 장치만 같은 단계 허용 (수리성 어셈블리 분해).
            allowed = child_rank > parent_rank or (
                child_rank == parent_rank and rec.node_type == "device"
            )
            if not allowed:
                raise ValidationError(_(
                    "'%(child)s'(%(child_type)s) 을 '%(parent)s'(%(parent_type)s) 아래에 둘 수 없습니다.\n"
                    "계층은 공장 → 라인 → 설비 → 장치 순서로만 내려갑니다."
                ) % {
                    "child": rec.name,
                    "child_type": dict(self._fields["node_type"].selection)[rec.node_type],
                    "parent": rec.parent_id.name,
                    "parent_type": dict(self._fields["node_type"].selection)[rec.parent_id.node_type],
                })

    @api.onchange("parent_id")
    def _onchange_parent_id(self):
        """장치를 새로 달 때 상위의 위치·담당을 미리 채운다. 이미 값이 있으면 건드리지 않는다."""
        for rec in self:
            parent = rec.parent_id
            if not parent:
                continue
            if not rec._origin.id and NODE_RANK[rec.node_type] <= NODE_RANK[parent.node_type]:
                rec.node_type = "device"
            for fname in INHERITED_FROM_PARENT:
                if not rec[fname]:
                    rec[fname] = parent[fname]

    def action_view_children(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("하위 장치"),
            "res_model": "iatf.equipment",
            "view_mode": "list,form",
            "domain": [("parent_id", "=", self.id)],
            "context": {"default_parent_id": self.id, "default_node_type": "device"},
        }

    @api.depends("last_pm_date", "pm_cycle_days")
    def _compute_next_pm(self):
        today = fields.Date.today()
        for rec in self:
            if rec.last_pm_date and rec.pm_cycle_days:
                from datetime import timedelta
                rec.next_pm_date = rec.last_pm_date + timedelta(days=rec.pm_cycle_days)
                rec.is_pm_overdue = rec.next_pm_date < today
            else:
                rec.next_pm_date = False
                rec.is_pm_overdue = False

    @api.depends("workcenter_id", "root_equipment_id.workcenter_id", "total_runtime_hours")
    def _compute_runtime(self):
        """가동시간은 작업장 실적을 우선한다. 없으면 수기 입력값, 그것도 없으면 미집계."""
        Productivity = self.env.get("mrp.workcenter.productivity")
        # 장치는 자기 작업장이 없으면 소속 설비의 작업장 실적을 함께 쓴다.
        wc_of = {
            rec.id: (rec.workcenter_id or rec.root_equipment_id.workcenter_id)
            for rec in self
        }
        totals = {}
        wc_ids = [wc.id for wc in wc_of.values() if wc]
        if Productivity is not None and wc_ids:
            totals = {
                wc.id: minutes
                for wc, minutes in Productivity.sudo()._read_group(
                    [("workcenter_id", "in", wc_ids), ("loss_type", "=", "productive")],
                    ["workcenter_id"],
                    ["duration:sum"],
                )
            }
        for rec in self:
            wc = wc_of.get(rec.id)
            # productivity.duration 은 '분' 단위다.
            rec.runtime_hours_wc = (totals.get(wc.id, 0.0) / 60.0) if wc else 0.0
            if rec.runtime_hours_wc:
                rec.runtime_hours = rec.runtime_hours_wc
                rec.runtime_source = "workcenter"
            elif rec.total_runtime_hours:
                rec.runtime_hours = rec.total_runtime_hours
                rec.runtime_source = "manual"
            else:
                rec.runtime_hours = 0.0
                rec.runtime_source = "none"

    @api.depends("breakdown_ids.state", "breakdown_ids.downtime_hours")
    def _compute_breakdown_stats(self):
        for rec in self:
            breakdowns = rec.breakdown_ids.filtered(lambda b: b.state == "closed")
            rec.breakdown_count = len(breakdowns)
            rec.total_downtime_hours = sum(breakdowns.mapped("downtime_hours"))
            rec.mttr = (rec.total_downtime_hours / rec.breakdown_count) if rec.breakdown_count else 0.0

    @api.depends("runtime_hours", "breakdown_count", "total_downtime_hours")
    def _compute_reliability(self):
        for rec in self:
            # 가동시간을 모르면 MTBF·가동률은 '0' 도 '100%' 도 아니고 산출 불가다.
            # 예전 구현은 이 경우 가동률을 100.0 으로 채워 데이터가 없는 설비를 완벽가동으로 보이게 했다.
            if not rec.runtime_hours:
                rec.mtbf = 0.0
                rec.availability_rate = 0.0
                continue
            rec.mtbf = (rec.runtime_hours / rec.breakdown_count) if rec.breakdown_count else 0.0
            denominator = rec.runtime_hours + rec.total_downtime_hours
            rec.availability_rate = (rec.runtime_hours / denominator) * 100.0 if denominator else 0.0

    @api.depends("complete_name")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.complete_name or rec.name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                # 장치는 DV-, 그 외(공장/라인/설비)는 EQ- 로 눈에 띄게 구분한다.
                seq_code = ("iatf.equipment.device"
                            if vals.get("node_type") == "device" else "iatf.equipment")
                vals["code"] = self.env["ir.sequence"].next_by_code(seq_code) or _("New")
        return super().create(vals_list)

    def action_activate(self):
        self.write({"state": "active"})

    def action_maintenance(self):
        self.write({"state": "maintenance"})

    def action_breakdown(self):
        self.write({"state": "breakdown"})

    def action_inactive(self):
        self.write({"state": "inactive"})

    def action_dispose(self):
        self.write({"state": "disposed"})

    @api.model
    def _cron_pm_overdue_alert(self):
        """매일 실행: PM 기한 초과/임박 설비에 activity 알림 생성"""
        from datetime import timedelta
        today = fields.Date.today()
        soon = today + timedelta(days=7)

        # PM 기한 초과
        overdue = self.search([
            ("is_pm_overdue", "=", True),
            ("state", "=", "active"),
        ])
        for eq in overdue:
            eq.activity_schedule(
                "mail.mail_activity_data_todo",
                summary=_("PM 기한 초과: %s (예정일: %s)") % (eq.name, eq.next_pm_date),
                user_id=eq.responsible_id.id or self.env.ref("base.user_admin").id,
                date_deadline=today,
            )

        # PM 기한 7일 이내
        upcoming = self.search([
            ("next_pm_date", "<=", soon),
            ("next_pm_date", ">=", today),
            ("state", "=", "active"),
        ])
        for eq in upcoming:
            existing = self.env["mail.activity"].search([
                ("res_model", "=", "iatf.equipment"),
                ("res_id", "=", eq.id),
                ("summary", "like", "PM 기한 임박"),
            ], limit=1)
            if not existing:
                eq.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("PM 기한 임박: %s (예정일: %s)") % (eq.name, eq.next_pm_date),
                    user_id=eq.responsible_id.id or self.env.ref("base.user_admin").id,
                    date_deadline=eq.next_pm_date,
                )


class IatfEquipmentSpare(models.Model):
    _name = "iatf.equipment.spare"
    _description = "설비 예비부품"
    _order = "equipment_id, name"

    equipment_id = fields.Many2one("iatf.equipment", string="설비", required=True, ondelete="cascade")
    name = fields.Char(string="부품명", required=True)
    part_number = fields.Char(string="부품 번호")
    quantity_required = fields.Float(string="필요 수량", default=1)
    quantity_on_hand = fields.Float(string="보유 수량")
    supplier = fields.Char(string="공급처")
    lead_time_days = fields.Integer(string="리드타임 (일)")
    notes = fields.Char(string="비고")
