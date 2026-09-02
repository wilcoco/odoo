from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# 예열·금형온도 기준이 '있어야 하는' 금형 유형. 지그·치공구·게이지는 예열 대상이
# 아니므로 온도 기준이 비어 있어도 기준 미비로 세지 않는다. 그렇게 하지 않으면
# 게이지 수십 건이 영구 미비로 잡혀 정작 진짜 미비 금형이 묻힌다.
TEMP_SPEC_TYPES = ("injection", "die_casting")


class IatfMold(models.Model):
    _name = "iatf.mold"
    _description = "금형/치공구 대장 (IATF 16949 §8.5.1.6)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "code"

    code = fields.Char(
        string="금형 코드", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    name = fields.Char(string="금형명", required=True, tracking=True)
    mold_type = fields.Selection(
        [
            ("injection", "사출 금형"),
            ("press", "프레스 금형"),
            ("die_casting", "다이캐스팅 금형"),
            ("forging", "단조 금형"),
            ("jig", "지그"),
            ("fixture", "치공구"),
            ("gauge", "게이지"),
            ("other", "기타"),
        ],
        string="유형", required=True, default="injection", tracking=True,
    )

    # ── 사양 ──
    product_id = fields.Many2one("product.product", string="생산 제품", tracking=True)
    part_number = fields.Char(string="부품 번호")
    cavity_count = fields.Integer(string="캐비티 수", default=1)
    material = fields.Char(string="금형 재질")
    weight_kg = fields.Float(string="중량 (kg)")
    dimensions = fields.Char(string="치수 (LxWxH)")
    manufacturer = fields.Char(string="금형 제작사")
    manufacture_date = fields.Date(string="제작일")
    receive_date = fields.Date(string="입고일")
    cost = fields.Float(string="제작 비용")

    # ── 소유권 (§8.5.3) ──
    ownership = fields.Selection(
        [("company", "자사 소유"), ("customer", "고객 소유"), ("supplier", "협력업체 소유")],
        string="소유 구분", required=True, default="company", tracking=True,
    )
    owner_id = fields.Many2one("res.partner", string="소유자 (고객/협력업체)")
    customer_mold_number = fields.Char(string="고객 금형 번호")

    # ── 수명 관리 ──
    guaranteed_shots = fields.Integer(string="보증 타수 (샷)")
    current_shots = fields.Integer(string="현재 타수", tracking=True)
    remaining_shots = fields.Integer(string="잔여 타수", compute="_compute_remaining", store=True)
    life_percentage = fields.Float(string="수명 사용률 (%)", compute="_compute_remaining", store=True)
    pm_cycle_shots = fields.Integer(string="PM 주기 (타수)", default=50000)
    last_pm_shots = fields.Integer(string="최근 PM 타수")
    next_pm_shots = fields.Integer(string="다음 PM 타수", compute="_compute_next_pm", store=True)

    # ── 관리기준 (SQ 4_1·4_2·4_6·4_7 의 "기준 수립" 증빙) ──
    # 여기 값이 비어 있으면 점검·세척·온도 판정이 전부 '판정 불가' 가 된다.
    # 가동 전 평가에서 평가자가 보는 것이 바로 이 기준의 존재 여부다.
    grade = fields.Selection(
        [("a", "A"), ("b", "B"), ("c", "C")],
        string="관리등급", tracking=True,
        help="관리 수준 구분. 주기·상하한은 등급에서 자동으로 끌어오지 않고 "
             "금형별로 직접 지정한다(사내 등급 체계가 확정되면 기본값 연결 검토).",
    )
    check_cycle_days = fields.Integer(
        string="일상점검 주기(일)", default=1,
        help="0 이면 주기 미설정 — 점검 기한 판정을 하지 않는다.",
    )
    clean_cycle_days = fields.Integer(
        string="세척 주기(일)",
        help="0 이면 주기 미설정 — 세척 기한 판정을 하지 않는다. (예: 180, 240)",
    )
    preheat_temp_min = fields.Float(string="예열 하한(℃)")
    preheat_temp_max = fields.Float(string="예열 상한(℃)")
    mold_temp_min = fields.Float(string="금형온도 하한(℃)")
    mold_temp_max = fields.Float(string="금형온도 상한(℃)")

    is_standard_ready = fields.Boolean(
        string="관리기준 수립", compute="_compute_standard_ready", store=True,
        help="관리등급·점검주기·세척주기(및 사출/다이캐스팅은 온도 상하한)가 "
             "모두 정해졌는지. 가동 전 SQ 평가의 '기준 수립' 증빙.",
    )
    standard_missing = fields.Char(
        string="미비 항목", compute="_compute_standard_ready", store=True,
        help="비어 있는 기준 항목. 무엇을 채워야 하는지 목록으로 보여준다.",
    )

    # ── 세척 계획 대비 실적 (SQ 4_2) ──
    last_clean_date = fields.Date(
        string="최근 세척일", compute="_compute_clean_due", store=True,
        help="보전/수리 이력 중 유형이 '세척' 이고 완료된 건의 최근 일자.",
    )
    next_clean_due = fields.Date(
        string="차기 세척 예정", compute="_compute_clean_due", store=True,
    )
    # 오늘 날짜에 의존하므로 저장하지 않는다. 저장하면 다음 재계산 전까지 값이 굳어
    # 기한이 지나도 계속 '정상' 으로 보인다.
    is_clean_overdue = fields.Boolean(
        string="세척 기한 경과", compute="_compute_clean_overdue",
        search="_search_is_clean_overdue",
    )

    # ── 시사출(T/O) (SQ 4_5) ──
    tryout_ids = fields.One2many("iatf.mold.tryout", "mold_id", string="시사출 보고서")
    tryout_count = fields.Integer(string="시사출 건수", compute="_compute_tryout")
    last_tryout_date = fields.Date(
        string="최근 시사출일", compute="_compute_tryout_summary", store=True,
    )
    is_tryout_missing = fields.Boolean(
        string="시사출 보고서 누락", compute="_compute_tryout_summary", store=True,
        help="사용 중인데 합격 판정된 시사출 보고서가 하나도 없는 금형. "
             "이관·신규 금형의 T/O 보고서 누락은 SQ 4_5 의 대표 감점 사유다.",
    )

    # ── 보관 ──
    storage_location = fields.Char(string="보관 위치")
    preservation_method = fields.Char(string="보존 방법", help="예: 방청유 도포, 건조 보관")

    # ── 담당 ──
    responsible_id = fields.Many2one("res.users", string="담당자", tracking=True)
    department_id = fields.Many2one("hr.department", string="관리 부서")

    # ── 관련 기록 ──
    maintenance_ids = fields.One2many("iatf.mold.maintenance", "mold_id", string="보전/수리 이력")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    image = fields.Binary(string="금형 사진")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "등록"),
            ("active", "사용 중"),
            ("maintenance", "보전 중"),
            ("inactive", "비사용"),
            ("disposed", "폐기"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("guaranteed_shots", "current_shots")
    def _compute_remaining(self):
        for rec in self:
            if rec.guaranteed_shots:
                rec.remaining_shots = max(rec.guaranteed_shots - rec.current_shots, 0)
                rec.life_percentage = (rec.current_shots / rec.guaranteed_shots) * 100.0
            else:
                rec.remaining_shots = 0
                rec.life_percentage = 0.0

    @api.depends("last_pm_shots", "pm_cycle_shots")
    def _compute_next_pm(self):
        for rec in self:
            rec.next_pm_shots = (rec.last_pm_shots or 0) + (rec.pm_cycle_shots or 0)

    # ─────────────────────────── 관리기준 ───────────────────────────

    @api.depends(
        "grade", "mold_type", "check_cycle_days", "clean_cycle_days",
        "preheat_temp_min", "preheat_temp_max", "mold_temp_min", "mold_temp_max",
    )
    def _compute_standard_ready(self):
        for rec in self:
            missing = []
            if not rec.grade:
                missing.append(_("관리등급"))
            if not rec.check_cycle_days:
                missing.append(_("일상점검 주기"))
            if not rec.clean_cycle_days:
                missing.append(_("세척 주기"))
            if rec.mold_type in TEMP_SPEC_TYPES:
                if not rec._has_temp_spec("preheat"):
                    missing.append(_("예열 온도 상하한"))
                if not rec._has_temp_spec("mold"):
                    missing.append(_("금형온도 상하한"))
            rec.standard_missing = ", ".join(missing)
            rec.is_standard_ready = not missing

    def _temp_spec(self, kind):
        """(하한, 상한) 반환. kind 는 'preheat' 또는 'mold'."""
        self.ensure_one()
        if kind == "preheat":
            return self.preheat_temp_min, self.preheat_temp_max
        if kind == "mold":
            return self.mold_temp_min, self.mold_temp_max
        raise ValueError("kind must be 'preheat' or 'mold'")

    def _has_temp_spec(self, kind):
        """상·하한 중 하나라도 설정돼 있으면 기준이 있는 것으로 본다.

        Float 은 '미설정' 과 '0℃' 를 구분하지 못한다. 금형 예열·금형온도에서
        0℃ 는 실무상 나오지 않는 값이므로 0 을 미설정으로 읽는다. 이렇게 하지
        않으면 기준을 한 번도 넣지 않은 금형이 '0℃ 상하한' 으로 해석돼 모든
        측정값이 상한 초과(NG) 로 찍힌다.
        """
        low, high = self._temp_spec(kind)
        return bool(low) or bool(high)

    def check_temp_in_spec(self, temperature, kind="preheat"):
        """측정 온도의 합·부를 이 금형의 상·하한과 대조해 판정한다.

        'ok' | 'ng' | 'no_spec' 을 돌려준다. 기준이 없으면 'ng' 가 아니라
        'no_spec' 이다 — 판정하지 않은 것과 불합격은 다른 사실이고, 섞으면
        없는 부적합을 만들어낸다.

        상한만 있거나 하한만 있는 경우도 허용한다(있는 쪽만 본다).
        """
        self.ensure_one()
        if not self._has_temp_spec(kind):
            return "no_spec"
        low, high = self._temp_spec(kind)
        if low and temperature < low:
            return "ng"
        if high and temperature > high:
            return "ng"
        return "ok"

    @api.model
    def _next_due(self, last_date, cycle_days):
        """최근 실시일 + 주기 = 차기 예정일. 둘 중 하나라도 없으면 False."""
        if not last_date or not cycle_days:
            return False
        return fields.Date.to_date(last_date) + relativedelta(days=cycle_days)

    @api.depends(
        "clean_cycle_days",
        "maintenance_ids.date", "maintenance_ids.maintenance_type", "maintenance_ids.state",
    )
    def _compute_clean_due(self):
        for rec in self:
            done = rec.maintenance_ids.filtered(
                lambda m: m.maintenance_type == "clean" and m.state == "done" and m.date
            )
            last = max(done.mapped("date")) if done else False
            rec.last_clean_date = last
            rec.next_clean_due = self._next_due(last, rec.clean_cycle_days)

    @api.depends("next_clean_due")
    def _compute_clean_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_clean_overdue = bool(rec.next_clean_due) and rec.next_clean_due < today

    def _search_is_clean_overdue(self, operator, value):
        """next_clean_due 가 저장 필드라 순수 SQL 도메인으로 바꿔 넘긴다."""
        if operator not in ("=", "!="):
            raise ValidationError(_("'세척 기한 경과' 는 = 또는 != 로만 검색할 수 있습니다."))
        today = fields.Date.context_today(self)
        want_overdue = (operator == "=") == bool(value)
        if want_overdue:
            return [("next_clean_due", "!=", False), ("next_clean_due", "<", today)]
        return ["|", ("next_clean_due", "=", False), ("next_clean_due", ">=", today)]

    # ─────────────────────────── 시사출(T/O) ───────────────────────────

    @api.depends("tryout_ids")
    def _compute_tryout(self):
        for rec in self:
            rec.tryout_count = len(rec.tryout_ids)

    @api.depends("state", "tryout_ids.tryout_date", "tryout_ids.conclusion", "tryout_ids.state")
    def _compute_tryout_summary(self):
        for rec in self:
            dates = rec.tryout_ids.filtered("tryout_date").mapped("tryout_date")
            rec.last_tryout_date = max(dates) if dates else False
            passed = rec.tryout_ids.filtered(
                lambda t: t.conclusion == "pass" and t.state == "done"
            )
            # 아직 사용에 들어가지 않은 금형(등록·폐기 등)은 누락으로 세지 않는다.
            # 감점 사유는 '양산에 쓰는데 T/O 보고서가 없는 것' 이지 미사용 금형이 아니다.
            rec.is_tryout_missing = rec.state == "active" and not passed

    def action_view_tryouts(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("시사출 보고서"),
            "res_model": "iatf.mold.tryout",
            "view_mode": "list,form",
            "domain": [("mold_id", "=", self.id)],
            "context": {"default_mold_id": self.id},
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("code", _("New")) == _("New"):
                vals["code"] = self.env["ir.sequence"].next_by_code("iatf.mold") or _("New")
        return super().create(vals_list)

    def action_activate(self):
        """양산 투입. 막지는 않되, T/O 보고서가 없으면 그 사실을 기록으로 남긴다.

        막으면 급할 때 상태만 우회로 바꿔버리고 기록은 여전히 안 남는다.
        경고를 chatter 에 남기면 '알고도 넣었다' 가 증빙에 남고, 목록 필터
        '시사출 누락' 으로 나중에 회수할 수 있다.
        """
        self.write({"state": "active"})
        for rec in self:
            if rec.is_tryout_missing:
                rec.message_post(body=_(
                    "합격 판정된 시사출(T/O) 보고서 없이 사용 상태로 전환되었습니다. "
                    "SQ 4_5 증빙을 위해 시사출 보고서를 작성하십시오."
                ))

    def action_maintenance(self):
        self.write({"state": "maintenance"})

    def action_inactive(self):
        self.write({"state": "inactive"})

    def action_dispose(self):
        self.write({"state": "disposed"})

    def action_add_shots(self):
        """타수 추가 위저드 대신 간단히 처리"""
        return True
