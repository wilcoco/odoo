import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# 주기 → 일수. 'event'(발생시) 는 주기가 없다 — 기한 판정을 하지 않는다.
# 'shift'(교대) 는 하루 여러 번이지만 기한 판정은 일 단위로만 한다.
CYCLE_DAYS = {
    "shift": 1,
    "daily": 1,
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}


class IatfCheckSheet(models.Model):
    """범용 점검 시트 — 무엇을 어떤 주기로 점검하는가 (관리기준).

    전동공구 토크, 통전검사 마스터, 바코드 마스터, 원소재 건조기 필터,
    분쇄기·배합기, 냉각수·작동유 온도, 소화기 — 대상만 다르고 구조가 같은
    점검들을 **모델 하나**로 덮는다. 대상별 전용 모듈을 만들지 않는다.

    금형(`iatf.mold.check`)·설비 일상점검(`iatf.daily.check`)·작업환경 5S
    (`iatf.environment.check`) 는 각자 고유 구조(주기가 마스터에 있음, 5S 5개
    점수 등)가 있어 여기로 흡수하지 않는다. 경계는 addons_custom/CLAUDE.md 참조.
    """

    _name = "iatf.check.sheet"
    _description = "범용 점검 시트 (점검 마스터)"
    _inherit = ["mail.thread"]
    _order = "name"

    name = fields.Char(string="점검 시트명", required=True, tracking=True)
    code = fields.Char(string="코드", copy=False)
    target_type = fields.Selection(
        [
            ("tool", "공구"),
            ("master", "검사 마스터"),
            ("facility", "설비/시설"),
            ("area", "구역"),
            ("etc", "기타"),
        ],
        string="대상 구분", required=True, default="facility", tracking=True,
    )
    # 안전점검(소화기·비상구·방호장치)도 주기·미실시 판정 구조가 일반 점검과 똑같다.
    # 네 번째 점검 원장을 만들지 않고 이 플래그로 구분만 한다.
    is_safety = fields.Boolean(
        string="안전점검", tracking=True,
        help="산업안전 목적의 점검(소화기·비상구·방호장치·보호구 등). "
             "체크하면 안전관리 메뉴의 '안전점검 시트'에 함께 나온다.",
    )

    # ── 대상 연결 (전부 선택) ──
    # 점검 대상이 설비 대장에 없는 경우가 많다(소화기·바코드리더·전동공구).
    # 그래서 어느 것도 필수로 두지 않고, 자유 기재 위치를 함께 둔다.
    equipment_id = fields.Many2one("iatf.equipment", string="설비", ondelete="set null")
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장", ondelete="set null")
    work_area_id = fields.Many2one("iatf.work.area", string="작업 구역", ondelete="set null")
    location_name = fields.Char(string="설치 위치", help="설비 대장에 없는 대상의 위치를 적는다. 예: 창고 A동 출입구 소화기 3호")

    # ── 주기 ──
    cycle = fields.Selection(
        [
            ("shift", "교대"),
            ("daily", "일"),
            ("weekly", "주"),
            ("monthly", "월"),
            ("quarterly", "분기"),
            ("yearly", "연"),
            ("event", "발생시"),
        ],
        string="점검 주기", required=True, default="daily", tracking=True,
    )
    start_date = fields.Date(
        string="운용 시작일", default=fields.Date.context_today, tracking=True,
        help="이 날부터 주기를 센다. 한 번도 점검하지 않은 시트도 시작일 + 주기가 지나면 "
             "미실시로 잡힌다. 비우면 기한 판정을 하지 않는다.",
    )
    responsible_id = fields.Many2one("res.users", string="점검 책임자",
                                     default=lambda self: self.env.user, tracking=True)
    department_id = fields.Many2one("hr.department", string="관리 부서")

    item_ids = fields.One2many("iatf.check.sheet.item", "sheet_id", string="점검 항목")
    item_count = fields.Integer(string="항목 수", compute="_compute_item_count")
    overdue_item_count = fields.Integer(string="미실시 항목 수", compute="_compute_overdue_items")

    # ── 개정 ──
    revision = fields.Integer(string="개정 차수", default=1, readonly=True, copy=False,
                              tracking=True)
    revision_ids = fields.One2many("iatf.check.sheet.revision", "sheet_id",
                                   string="개정 이력", readonly=True)
    record_ids = fields.One2many("iatf.check.record", "sheet_id", string="점검 실적")
    record_count = fields.Integer(string="실적 건수", compute="_compute_record_count")

    last_record_date = fields.Date(
        string="최근 점검일", compute="_compute_due", store=True,
        help="완료(done) 된 점검만 센다. 작성 중인 점검표는 실적이 아니다.",
    )
    next_due = fields.Date(string="차기 점검 예정", compute="_compute_due", store=True)
    # 오늘 날짜에 의존하므로 저장하지 않는다. 저장하면 값이 굳어 기한이 지나도 '정상'으로 보인다.
    is_overdue = fields.Boolean(string="미실시(기한 경과)", compute="_compute_overdue",
                                search="_search_is_overdue")

    active = fields.Boolean(default=True)
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    _sql_constraints = [
        ("uniq_check_sheet_code", "unique(code)", "점검 시트 코드가 중복됩니다."),
    ]

    @api.depends("item_ids")
    def _compute_item_count(self):
        for rec in self:
            rec.item_count = len(rec.item_ids)

    @api.depends("item_ids.is_overdue")
    def _compute_overdue_items(self):
        for rec in self:
            rec.overdue_item_count = len(rec.item_ids.filtered("is_overdue"))

    def _log_revision(self, summary, reason=None):
        """개정 차수를 올리고 무엇이 바뀌었는지 남긴다.

        시트를 만들 때(항목 최초 등록)도 이 경로를 탄다. 1차 개정이 곧 제정 기록이
        되므로 따로 구분하지 않는다. `sudo` 로 쓰는 이유는 개정 이력이 점검자
        권한으로도 반드시 남아야 하기 때문이다 — 이력이 남지 않는 편집 경로가
        하나라도 있으면 표준류 관리로 인정받지 못한다.
        """
        for sheet in self:
            if not sheet.id:
                continue
            sheet.sudo().write({"revision": (sheet.revision or 0) + 1})
            self.env["iatf.check.sheet.revision"].sudo().create({
                "sheet_id": sheet.id,
                "revision": sheet.revision,
                "summary": summary,
                "reason": reason,
            })

    @api.depends("record_ids")
    def _compute_record_count(self):
        for rec in self:
            rec.record_count = len(rec.record_ids)

    @api.depends("cycle", "start_date", "record_ids.check_date", "record_ids.state")
    def _compute_due(self):
        for rec in self:
            done = rec.record_ids.filtered(lambda r: r.state == "done" and r.check_date)
            last = max(done.mapped("check_date")) if done else False
            rec.last_record_date = last
            days = CYCLE_DAYS.get(rec.cycle)
            # 한 번도 점검하지 않았으면 운용 시작일부터 센다. 이게 없으면 시트를
            # 만들어 놓고 한 번도 실행하지 않은 대상이 미실시 목록에 영영 안 뜬다.
            base = last or rec.start_date
            rec.next_due = fields.Date.add(base, days=days) if (days and base) else False

    @api.depends("next_due")
    def _compute_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.next_due) and rec.next_due < today

    def _search_is_overdue(self, operator, value):
        """'예정일이 오늘보다 이전' 을 저장 필드 기준 SQL 도메인으로 바꿔 넘긴다."""
        if operator not in ("=", "!="):
            raise ValidationError(_("'미실시(기한 경과)' 는 = 또는 != 로만 검색할 수 있습니다."))
        today = fields.Date.context_today(self)
        want_overdue = (operator == "=") == bool(value)
        if want_overdue:
            return [("next_due", "!=", False), ("next_due", "<", today)]
        return ["|", ("next_due", "=", False), ("next_due", ">=", today)]

    def _prepare_record_lines(self):
        """실적 라인을 시트 항목에서 만든다.

        기준(항목명·판정기준·상하한)을 **복사**해 둔다. 나중에 시트 기준이 바뀌어도
        과거 실적은 그때 적용된 기준을 그대로 보존해야 심사 증빙이 된다.
        """
        self.ensure_one()
        return [
            (0, 0, {
                "item_id": item.id,
                "sequence": item.sequence,
                "item_name": item.name,
                "standard": item.standard,
                "check_method": item.check_method,
                "entry_type": item.entry_type,
                "spec_mode": item.spec_mode,
                "target_value": item.target_value,
                "tolerance": item.tolerance,
                "spec_min": item.spec_min,
                "spec_max": item.spec_max,
                "uom_name": item.uom_name,
                "is_key_item": item.is_key_item,
            })
            for item in self.item_ids
        ]

    def action_view_records(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("점검 실적"),
            "res_model": "iatf.check.record",
            "view_mode": "list,form",
            "domain": [("sheet_id", "=", self.id)],
            "context": {"default_sheet_id": self.id},
        }

    def action_new_record(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("점검 실적"),
            "res_model": "iatf.check.record",
            "view_mode": "form",
            "context": {"default_sheet_id": self.id},
        }


class IatfCheckSheetItem(models.Model):
    """점검 항목의 '정의' — 무엇을, 어떤 단위로, 어떤 기준으로, 얼마나 자주.

    양식을 코드에 박지 않는다. 회사 점검표는 공정·설비마다 다르고 해마다 바뀐다
    (실제 '24년도 설비 일상점검표는 시트 22장, 항목 구성이 전부 다르다).
    항목·단위·기준·주기를 전부 화면에서 고칠 수 있어야 설비가 하나 늘 때마다
    개발자를 부르지 않는다.
    """

    _name = "iatf.check.sheet.item"
    _description = "점검 항목 (기준)"
    _order = "sequence, id"

    sheet_id = fields.Many2one("iatf.check.sheet", string="점검 시트", required=True,
                               ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="판정 기준", help="정성 항목은 여기에 기준을 글로 적는다. 예: 균열·마모 없을 것")
    check_method = fields.Selection(
        [("visual", "육안"), ("measure", "측정"), ("function", "작동"), ("other", "기타")],
        string="점검 방법", default="visual",
    )
    # 회사 점검표의 '방법' 열(육안 / 수치기입 / 시연)이 곧 점검자가 무엇을 적느냐다.
    # check_method 는 '어떻게 보는가', entry_type 은 '무엇을 적는가' 로 나눈다.
    entry_type = fields.Selection(
        [("judge", "양호·불량"), ("numeric", "수치 기입"), ("text", "내용 기입")],
        string="입력 방식", default="judge", required=True,
        help="수치 기입 항목만 상·하한으로 자동 판정한다.",
    )
    spec_mode = fields.Selection(
        [
            ("qualitative", "정성(기준 글)"),
            ("range", "범위(하한~상한)"),
            ("min", "하한 이상"),
            ("max", "상한 이하"),
            ("target", "목표±공차"),
        ],
        string="기준 방식", default="qualitative", required=True,
        help="회사 양식 표기를 그대로 담는다. 예: 작동유 40℃±10℃ → 목표±공차, "
             "AIR 압력 0.4~0.6Mpa → 범위.",
    )
    target_value = fields.Float(string="목표값")
    tolerance = fields.Float(string="공차(±)")
    # spec_min/max 는 판정이 실제로 쓰는 값이다. '목표±공차' 로 적어도 여기로 환산해
    # 두어야 판정 로직이 한 갈래로 남는다. 화면 표기와 판정 근거를 분리하는 것이 요점.
    spec_min = fields.Float(string="하한", compute="_compute_spec_bounds",
                            store=True, readonly=False)
    spec_max = fields.Float(string="상한", compute="_compute_spec_bounds",
                            store=True, readonly=False)
    uom_name = fields.Char(string="단위",
                           help="Mpa·mmH₂O·㎐·㎏f/㎠ 처럼 회사 표기를 그대로 적는다.")
    is_key_item = fields.Boolean(
        string="중요 관리 항목",
        help="회사 점검표의 '※ 금월 중요 관리 항목'. 미실시 집계에서 먼저 보이게 한다.",
    )

    # ── 항목별 주기 ──
    # 시트 하나 안에서도 항목마다 주기가 다르다(도장 믹싱룸 시트에 항목별 주기 열이 있다).
    # 비우면 시트 주기를 따른다.
    cycle = fields.Selection(
        [
            ("shift", "교대"), ("daily", "일"), ("weekly", "주"), ("monthly", "월"),
            ("quarterly", "분기"), ("yearly", "연"), ("event", "발생시"),
        ],
        string="항목 주기", help="비우면 시트의 점검 주기를 따른다.",
    )
    record_line_ids = fields.One2many("iatf.check.record.line", "item_id",
                                      string="점검 이력")
    last_check_date = fields.Date(string="최근 점검일", compute="_compute_item_due", store=True)
    next_due = fields.Date(string="차기 예정", compute="_compute_item_due", store=True)
    is_overdue = fields.Boolean(string="미실시(기한 경과)", compute="_compute_item_overdue")

    active = fields.Boolean(default=True)

    @api.depends("spec_mode", "target_value", "tolerance")
    def _compute_spec_bounds(self):
        """'목표±공차' 일 때만 상·하한을 계산한다.

        다른 방식에서 어긋난 경계값을 여기서 **지우지 않는다.** 조용히 0 으로 만들면
        담당자는 기준을 넣었다고 믿는데 판정은 안 걸리는 상태가 된다. 기준이 있는 줄
        알고 넘어가는 게 기준이 없는 것보다 나쁘다. 그래서 지우는 대신
        `_check_bounds_match_mode` 로 막고 이유를 말해 준다.
        """
        for rec in self:
            if rec.spec_mode == "target":
                target = rec.target_value or 0.0
                tol = abs(rec.tolerance or 0.0)
                rec.spec_min = target - tol
                rec.spec_max = target + tol
            else:
                # 편집 가능한 계산 필드라 매 재계산마다 값을 명시해야 한다.
                rec.spec_min = rec.spec_min
                rec.spec_max = rec.spec_max

    @api.constrains("spec_mode", "spec_min", "spec_max")
    def _check_bounds_match_mode(self):
        labels = dict(self._fields["spec_mode"].selection)
        for rec in self:
            bad = None
            if rec.spec_mode == "qualitative" and (rec.spec_min or rec.spec_max):
                bad = _("정성 항목에는 상·하한을 넣지 않습니다. 수치로 판정하려면 기준 방식을 바꾸십시오.")
            elif rec.spec_mode == "min" and rec.spec_max:
                bad = _("'하한 이상' 방식에는 상한을 넣지 않습니다.")
            elif rec.spec_mode == "max" and rec.spec_min:
                bad = _("'상한 이하' 방식에는 하한을 넣지 않습니다.")
            if bad:
                raise ValidationError(_(
                    "'%(item)s' 의 기준 방식이 '%(mode)s' 입니다. %(why)s",
                    item=rec.name, mode=labels.get(rec.spec_mode), why=bad))

    @api.depends("cycle", "sheet_id.cycle", "sheet_id.start_date",
                 "record_line_ids.result", "record_line_ids.record_id.check_date",
                 "record_line_ids.record_id.state")
    def _compute_item_due(self):
        """항목 단위 기한. 시트가 아니라 **항목별로** 누락을 집계하기 위한 것이다.

        시트 주기로만 보면, 월 1회 항목과 매일 항목이 한 시트에 섞였을 때
        월 항목을 한 번 한 것으로 시트 전체가 '실시함' 이 된다. 그러면 매일 해야 할
        항목의 누락이 통째로 가려진다 — SQ 4_1·2항이 정확히 그 누락을 본다.
        """
        for rec in self:
            done = rec.record_line_ids.filtered(
                lambda l: l.result and l.record_id.state == "done" and l.record_id.check_date
            )
            last = max(done.mapped("record_id.check_date")) if done else False
            rec.last_check_date = last
            days = CYCLE_DAYS.get(rec.cycle or rec.sheet_id.cycle)
            base = last or rec.sheet_id.start_date
            rec.next_due = fields.Date.add(base, days=days) if (days and base) else False

    @api.depends("next_due")
    def _compute_item_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_overdue = bool(rec.next_due) and rec.next_due < today

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.name, low=rec.spec_min, high=rec.spec_max))

    @api.constrains("entry_type", "spec_mode")
    def _check_entry_matches_spec_mode(self):
        """수치 기준을 걸어 놓고 입력은 양호·불량만 받는 항목을 막는다.

        그렇게 두면 상·하한이 화면에 보이지만 측정값을 적을 칸이 없어, 점검자가
        눈대중으로 '양호' 를 고르고 기준은 장식이 된다. 기준이 있는데 실적이
        기준을 안 쓰는 상태가 곧 SQ 의 '보완(60%)' 판정 사유다.
        """
        labels = dict(self._fields["spec_mode"].selection)
        for rec in self:
            if rec.spec_mode != "qualitative" and rec.entry_type != "numeric":
                raise ValidationError(_(
                    "'%(item)s' 의 기준 방식이 '%(mode)s' 이면 입력 방식은 '수치 기입' 이어야 합니다.\n"
                    "수치 기준을 걸어 두고 양호·불량만 받으면 기준이 판정에 쓰이지 않습니다.",
                    item=rec.name, mode=labels.get(rec.spec_mode)))

    # ── 개정 이력 ──
    # 항목을 고치면 시트 개정이 올라간다. 실적은 몇 차 개정본으로 점검했는지를
    # 들고 있으므로, 나중에 기준이 바뀌어도 그때 판정 근거를 되짚을 수 있다.
    _REVISION_TRACKED = (
        "name", "standard", "check_method", "entry_type", "spec_mode",
        "target_value", "tolerance", "spec_min", "spec_max", "uom_name",
        "cycle", "is_key_item", "active",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # 상·하한만 주고 방식을 안 주는 경로(엑셀 가져오기·기존 코드·API)가 있다.
            # 그때 기본값 '정성' 을 그대로 두면 넣은 기준이 판정에 안 쓰인다.
            has_bounds = bool(vals.get("spec_min") or vals.get("spec_max"))
            if has_bounds and not vals.get("spec_mode"):
                vals["spec_mode"] = "range"
            if vals.get("spec_mode", "qualitative") != "qualitative" and not vals.get("entry_type"):
                vals["entry_type"] = "numeric"
        items = super().create(vals_list)
        for sheet in items.mapped("sheet_id"):
            names = items.filtered(lambda i: i.sheet_id == sheet).mapped("name")
            sheet._log_revision(_("항목 추가: %s", ", ".join(names)))
        return items

    def write(self, vals):
        if not any(f in vals for f in self._REVISION_TRACKED):
            return super().write(vals)
        before = {rec.id: {f: rec[f] for f in self._REVISION_TRACKED} for rec in self}
        res = super().write(vals)
        for rec in self:
            changed = [f for f in self._REVISION_TRACKED
                       if f in vals and before[rec.id][f] != rec[f]]
            if not changed:
                continue
            detail = ", ".join(
                "%s: %s → %s" % (self._fields[f].string, before[rec.id][f] or "-", rec[f] or "-")
                for f in changed
            )
            rec.sheet_id._log_revision(_("항목 '%(item)s' 수정 — %(detail)s",
                                         item=rec.name, detail=detail))
        return res

    def unlink(self):
        for rec in self:
            rec.sheet_id._log_revision(_("항목 삭제: %s", rec.name))
        return super().unlink()


class IatfCheckSheetRevision(models.Model):
    """점검 시트 개정 이력.

    기준을 화면에서 고칠 수 있게 만드는 순간, '언제 무엇이 왜 바뀌었는가' 를 남기지
    않으면 표준류 관리가 성립하지 않는다. 심사에서 묻는 것도 대개 그 지점이다
    (SQ 1_1 표준류 일치성 / IATF 문서관리). 실적 쪽 판정 근거는 실적 라인의
    기준 스냅샷이 따로 보존한다 — 이건 '정의가 언제 바뀌었나' 의 기록이다.
    """

    _name = "iatf.check.sheet.revision"
    _description = "점검 시트 개정 이력"
    _order = "revision desc, id desc"

    sheet_id = fields.Many2one("iatf.check.sheet", string="점검 시트", required=True,
                               ondelete="cascade", index=True)
    revision = fields.Integer(string="개정 차수", required=True)
    changed_on = fields.Datetime(string="개정 일시", required=True,
                                 default=fields.Datetime.now)
    changed_by = fields.Many2one("res.users", string="개정자", required=True,
                                 default=lambda self: self.env.user)
    summary = fields.Char(string="변경 내용", required=True)
    reason = fields.Char(string="개정 사유")


class IatfCheckRecord(models.Model):
    """점검 실적 — 언제 누가 무엇을 점검했는가.

    `iatf.mold.check` 와 같은 규칙을 쓴다.
    1. 항목이 비었거나 판정이 덜 된 점검표는 '양호' 가 아니라 '미완료' 다.
    2. 완료(done) 건만 실적으로 센다.
    """

    _name = "iatf.check.record"
    _description = "점검 실적"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "check_date desc, id desc"

    name = fields.Char(string="점검 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    sheet_id = fields.Many2one("iatf.check.sheet", string="점검 시트", required=True,
                               index=True, tracking=True, ondelete="restrict")
    target_type = fields.Selection(related="sheet_id.target_type", string="대상 구분", store=True)
    cycle = fields.Selection(related="sheet_id.cycle", string="점검 주기", store=True)
    # related 가 아니라 스냅샷이다. 시트가 개정돼도 이 실적이 몇 차로 점검됐는지는
    # 바뀌면 안 된다.
    sheet_revision = fields.Integer(string="시트 개정 차수", readonly=True, copy=False)
    check_date = fields.Date(string="점검일", required=True,
                             default=fields.Date.context_today, tracking=True)
    shift = fields.Selection([("day", "주간"), ("evening", "야간"), ("night", "심야")],
                             string="근무조", default="day")
    checker_id = fields.Many2one("res.users", string="점검자",
                                 default=lambda self: self.env.user, tracking=True)
    line_ids = fields.One2many("iatf.check.record.line", "record_id", string="점검 항목")
    snapshot_ids = fields.One2many(
        "iatf.check.record.snapshot", "record_id", string="완료 스냅샷", readonly=True,
        help="완료로 넘어갈 때마다 그 시점의 측정값 전문을 한 벌 남긴다.")
    snapshot_count = fields.Integer(
        string="완료 차수", compute="_compute_snapshot_count", store=True)
    overall_result = fields.Selection(
        [("ok", "양호"), ("issue", "이상 있음"), ("pending", "미완료")],
        string="종합 판정", compute="_compute_overall", store=True)
    ng_count = fields.Integer(string="이상 항목 수", compute="_compute_overall", store=True)
    na_count = fields.Integer(
        string="해당없음 항목 수", compute="_compute_overall", store=True,
        help="'해당없음' 으로 둔 항목 수. 기준이 있는 수치 항목을 사유 없이 "
             "'해당없음' 으로 두면 종합 판정이 '미완료' 로 남는다.")
    # 한 번이라도 완료된 적이 있는가. `state` 만 보면 '작성 중' 으로 되돌린 뒤 지울 수 있다.
    # 완료 기록의 삭제를 막는 것은 그 순간의 상태가 아니라 **완료된 적이 있다는 사실**이다.
    # (아스트라 재검토 2026-09-10 ②)
    was_done = fields.Boolean(string="완료 이력", default=False, copy=False, readonly=True,
                              help="한 번이라도 완료 처리된 기록. 되돌려도 삭제할 수 없다.")
    state = fields.Selection([("draft", "작성 중"), ("done", "완료"), ("cancelled", "취소")],
                             string="상태", default="draft", required=True, tracking=True)
    corrective_action = fields.Text(string="조치 내용")
    notes = fields.Text(string="비고")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)


    @staticmethod
    def _na_is_substantiated(line):
        """'해당없음' 이 판정으로 인정되는가.

        기준(상·하한)이 있는 수치 항목을 재지 않고 `na` 로 두면 그것은 판정이 아니라
        **미실시**다. 그런데 종합 판정은 `na` 를 판정으로 세어 '양호' 를 냈다.
        (제3자 재검토 R04)

        아스트라 지침에 따라 **새 승인 정책을 만들지 않고**, 전면 금지도 하지 않는다.
        제외 사유(비고)가 적혀 있으면 판정으로 인정하고, 없으면 **미판정으로 표시**한다.
        기준이 없는 정성 항목의 `na` 는 원래부터 사유 없이도 정상이다.
        """
        if line.result != "na":
            return True
        if not line._has_spec():
            return True          # 정성 항목 — 기준이 없으니 '해당없음' 이 자연스럽다
        return bool((line.remark or "").strip())

    def _derive_overall(self):
        """항목에서 종합 판정을 도출한다. (판정, 이상 수, 해당없음 수)

        저장된 `overall_result` 를 믿을 수 없기 때문에 순수 함수로 뽑아 둔다.
        편집 가능한 계산 필드라 `write({'state':'done','overall_result':'ok'})` 처럼
        의존 필드가 바뀌지 않는 write 에서는 재계산이 돌지 않는다.
        (아스트라 275 리뷰 Q275-02)
        """
        self.ensure_one()
        lines = self.line_ids
        ng = len(lines.filtered(lambda l: l.result == "ng"))
        na = len(lines.filtered(lambda l: l.result == "na"))
        unsubstantiated = lines.filtered(lambda l: not self._na_is_substantiated(l))
        if not lines or any(not l.result for l in lines) or unsubstantiated:
            # 점검하지 않은 것과 이상 없는 것은 다른 사실이다.
            return "pending", ng, na
        return ("issue" if ng else "ok"), ng, na

    @api.depends("line_ids.result", "line_ids.remark", "line_ids.spec_min", "line_ids.spec_max")
    def _compute_overall(self):
        for rec in self:
            rec.overall_result, rec.ng_count, rec.na_count = rec._derive_overall()

    @api.constrains("check_date")
    def _check_date_not_future(self):
        """미래 날짜 점검은 실적이 아니다.

        차기 예정일이 최근 점검일에서 계산되므로, 미래 날짜로 기록하면 미실시
        목록에서 사라진다. 즉 '아직 하지 않은 점검' 을 이행한 것처럼 만들 수 있는
        경로다 — 막는다.
        """
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.check_date and rec.check_date > today:
                raise ValidationError(_(
                    "점검일(%(date)s)을 미래로 지정할 수 없습니다. 오늘은 %(today)s 입니다.",
                    date=rec.check_date, today=today))

    @api.onchange("sheet_id")
    def _onchange_sheet_id(self):
        # 시트를 바꾸면 항목을 전부 갈아끼운다. 남겨 두면 다른 시트의 항목이
        # 섞인 점검표가 만들어진다.
        if self.sheet_id:
            self.line_ids = [(5, 0, 0)] + self.sheet_id._prepare_record_lines()
            self.sheet_revision = self.sheet_id.revision

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.check.record") or _("New")
            # onchange 는 화면에서만 돈다. API·테스트·가져오기 경로에서도 같은
            # 결과가 나오도록 서버에서 한 번 더 채운다.
            if vals.get("sheet_id"):
                sheet = self.env["iatf.check.sheet"].browse(vals["sheet_id"])
                if not vals.get("line_ids"):
                    vals["line_ids"] = sheet._prepare_record_lines()
                # 어느 개정본으로 점검했는지. 이게 없으면 나중에 기준이 바뀌었을 때
                # 그 실적이 어떤 기준으로 판정된 것인지 되짚을 수 없다.
                vals.setdefault("sheet_revision", sheet.revision)
            if vals.get("state") == "done":
                # 처음부터 완료로 만든 실적도 완료 이력이다. 이걸 빼면
                # create(done) → write(draft) → unlink 로 완료 증빙이 지워진다.
                vals["was_done"] = True
        return super().create(vals_list)

    # 완료 뒤에도 고칠 수 있는 것. 그 외 필드는 완료 실적에서 잠근다.
    _DONE_EDITABLE = {"state", "corrective_action", "notes", "message_main_attachment_id"}

    def write(self, vals):
        """완료된 실적의 사실(점검일·시트·근무조·점검자·항목)은 바꿀 수 없다.

        완료 후 점검일을 옮기면 미실시 판정이 바뀌고, 시트를 바꾸면 라인과 기준이
        갈린다. 고쳐야 하면 '작성 중' 으로 되돌리고 고친 뒤 다시 완료한다.
        (2026-09-10 제3자 검토 Q10)
        """
        if "was_done" in vals and not vals["was_done"]:
            # 완료 이력은 사실이지 설정값이 아니다. 이걸 지울 수 있으면 삭제 금지가
            # 통째로 무력해진다 — write({'was_done': False}) 뒤 unlink 가 통과한다.
            # (아스트라 독립재현 2026-09-10 ②)
            stamped = self.filtered("was_done")
            if stamped:
                raise ValidationError(_(
                    "완료 이력은 해제할 수 없습니다: %s",
                    ", ".join(stamped.mapped("name"))))
        locked = self.filtered(lambda r: r.state == "done" or r.was_done)
        touched = set(vals) - self._DONE_EDITABLE
        if locked and touched and vals.get("state", "done") == "done":
            raise ValidationError(_(
                "완료된 점검 실적은 수정할 수 없습니다: %(names)s\n"
                "고치려면 먼저 '작성 중' 으로 되돌리십시오. (변경 항목: %(fields)s)",
                names=", ".join(locked.mapped("name")), fields=", ".join(sorted(touched))))
        becoming_done = self.filtered(lambda r: r.state != "done") if (
            vals.get("state") == "done") else self.browse()
        if vals.get("state") == "done":
            # 완료로 넘어간 사실을 같은 write 에 실어 남긴다. 되돌려도 지워지지 않는다.
            # 따로 write 를 부르면 재진입·잠금 검사와 얽힌다. (아스트라 재검토 ②)
            vals = dict(vals, was_done=True)
        res = super().write(vals)
        becoming_done._snapshot_on_done()
        return res

    def _snapshot_line_payload(self, line):
        """한 항목의 완료 시점 사실. 판정 근거가 되는 값만 담는다."""
        return {
            "순서": line.sequence,
            "항목": line.item_name,
            "기준": line.standard or "",
            "기준방식": line.spec_mode or "",
            "하한": line.spec_min,
            "상한": line.spec_max,
            "측정값": line.value,
            "기입내용": line.text_value or "",
            "단위": line.uom_name or "",
            "판정": line.result or "",
            "비고": line.remark or "",
        }

    def _snapshot_values(self):
        """완료 시점의 사실 전부. **서버가 원본에서 직접 만든다.**

        호출자가 준 값은 쓰지 않는다(부모 id 만 받는다). 종합 판정도 저장값이 아니라
        항목에서 다시 도출한다. 완료 당시의 시트·개정 차수·점검일·근무조·점검자·회사도
        함께 얼려 둔다. (아스트라 275 리뷰 Q275-01·02·03)
        """
        self.ensure_one()
        labels = dict(self._fields["overall_result"].selection)
        derived, ng_count, _na = self._derive_overall()
        Snapshot = self.env["iatf.check.record.snapshot"].sudo()
        return {
            "record_id": self.id,
            "revision": Snapshot.search_count([("record_id", "=", self.id)]) + 1,
            "done_at": fields.Datetime.now(),
            "done_by_id": self.env.user.id,
            "overall_result": labels.get(derived, derived),
            "ng_count": ng_count,
            "line_count": len(self.line_ids),
            # ── 완료 당시의 원본 식별 정보 (현재 값이 아니라 그때 값) ──
            "sheet_id": self.sheet_id.id,
            "sheet_name": self.sheet_id.display_name or "",
            "sheet_revision": self.sheet_revision,
            "check_date": self.check_date,
            "shift": dict(self._fields["shift"].selection).get(self.shift, self.shift or ""),
            "checker_id": self.checker_id.id,
            "checker_name": self.checker_id.display_name or "",
            "company_id": self.company_id.id,
            "company_name": self.company_id.display_name or "",
            "content": json.dumps(
                [self._snapshot_line_payload(l) for l in self.line_ids],
                ensure_ascii=False, indent=2),
        }

    def _snapshot_on_done(self):
        """완료로 넘어간 실적의 측정값 전문을 한 벌 얼려 둔다."""
        if not self:
            return
        Snapshot = self.env["iatf.check.record.snapshot"].sudo()
        Snapshot.with_context(**{Snapshot._SERVICE_KEY: True}).create(
            [{"record_id": rec.id} for rec in self])

    @api.depends("snapshot_ids")
    def _compute_snapshot_count(self):
        for rec in self:
            rec.snapshot_count = len(rec.snapshot_ids)

    @api.constrains("state", "line_ids")
    def _check_done_is_complete(self):
        """완료 상태의 백스톱.

        `action_done` 의 검사는 버튼 경로에만 걸린다. `write({'state': 'done'})`
        으로 우회하면 판정이 비어 있는 점검표가 실적으로 집계된다. 실적 수는
        SQ 채점의 근거라 우회 경로를 열어 두면 안 된다.
        """
        for rec in self:
            if rec.state != "done":
                continue
            # 저장된 종합 판정을 믿지 않는다 — state 와 overall_result 를 같이 쓰면
            # 재계산이 돌지 않아 그대로 통과한다. 근거는 라인이다. (제3자 재검토 R02)
            lines = rec.line_ids
            derived, _ng, _na = rec._derive_overall()
            if rec.overall_result != derived:
                # 저장된 종합 판정이 항목과 다르다 — 집계만 손으로 바꾼 완료다.
                # 그대로 두면 NG 가 든 실적이 '양호' 로 집계된다. (275 리뷰 Q275-02)
                labels = dict(rec._fields["overall_result"].selection)
                raise ValidationError(_(
                    "종합 판정이 점검 항목과 맞지 않습니다: 저장값 '%(given)s' / "
                    "항목 기준 '%(derived)s'. 집계는 항목에서 정해집니다. (%(name)s)",
                    given=labels.get(rec.overall_result) or _("미지정"),
                    derived=labels.get(derived), name=rec.name))
            unsubstantiated = lines.filtered(lambda l: not self._na_is_substantiated(l))
            if not lines or any(not l.result for l in lines):
                raise ValidationError(_(
                    "판정이 비어 있는 항목이 있어 완료 상태로 둘 수 없습니다. (%s)", rec.name))
            if unsubstantiated:
                # 기준이 있는 항목을 사유 없이 '해당없음' 으로 둔 것 — 판정이 아니다. (R04)
                raise ValidationError(_(
                    "기준이 있는 항목을 사유 없이 '해당없음' 으로 둘 수 없습니다: %(items)s\n"
                    "측정했으면 값을 적고, 측정하지 않았다면 비고에 제외 사유를 남기십시오. (%(name)s)",
                    items=", ".join(unsubstantiated.mapped("item_name")), name=rec.name))

    def action_done(self):
        """완료 처리. 판정이 덜 된 점검표는 완료할 수 없다."""
        for rec in self:
            if rec.overall_result == "pending":
                raise UserError(_(
                    "점검 항목이 없거나 판정이 비어 있는 항목이 있습니다. "
                    "모든 항목의 결과를 기입한 뒤 완료하십시오. (%s)", rec.name))
            rec.state = "done"
            if rec.ng_count:
                rec.message_post(body=_(
                    "이상 항목 %s 건이 발견되었습니다. 조치 내용을 남기십시오.", rec.ng_count))


    def unlink(self):
        """완료된 점검 실적은 지울 수 없다 — 관리자도 마찬가지다. (제3자 재검토 R02)"""
        locked = self.filtered(lambda r: r.state == "done" or r.was_done)
        if locked:
            raise ValidationError(_(
                "완료된 적이 있는 점검 실적은 삭제할 수 없습니다: %s\n"
                "잘못된 기록이면 '작성 중' 으로 되돌린 뒤 '취소' 로 남기십시오.",
                ", ".join(locked.mapped("name"))))
        return super().unlink()

    def action_draft(self):
        self.write({"state": "draft"})

    def action_cancel(self):
        self.write({"state": "cancelled"})


class IatfCheckRecordLine(models.Model):
    _name = "iatf.check.record.line"
    _description = "점검 실적 항목"
    _order = "sequence, id"

    record_id = fields.Many2one("iatf.check.record", string="점검 실적", required=True,
                                ondelete="cascade", index=True)
    item_id = fields.Many2one("iatf.check.sheet.item", string="기준 항목", ondelete="set null")
    sequence = fields.Integer(default=10)
    # 기준을 복사해 둔다. 시트 기준이 바뀌어도 과거 실적의 판정 근거가 남아야 한다.
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="판정 기준")
    check_method = fields.Selection(
        [("visual", "육안"), ("measure", "측정"), ("function", "작동"), ("other", "기타")],
        string="점검 방법")
    # 정의 스냅샷 — 판정한 그 시점의 기준이다. 시트를 나중에 개정해도 여기는 안 바뀐다.
    entry_type = fields.Selection(
        [("judge", "양호·불량"), ("numeric", "수치 기입"), ("text", "내용 기입")],
        string="입력 방식", default="judge")
    spec_mode = fields.Selection(
        [
            ("qualitative", "정성(기준 글)"), ("range", "범위(하한~상한)"),
            ("min", "하한 이상"), ("max", "상한 이하"), ("target", "목표±공차"),
        ],
        string="기준 방식", default="qualitative")
    target_value = fields.Float(string="목표값")
    tolerance = fields.Float(string="공차(±)")
    spec_min = fields.Float(string="하한")
    spec_max = fields.Float(string="상한")
    value = fields.Float(string="측정값")
    text_value = fields.Char(string="기입 내용")
    uom_name = fields.Char(string="단위")
    is_key_item = fields.Boolean(string="중요 관리 항목")
    result = fields.Selection([("ok", "양호"), ("ng", "불량"), ("na", "해당없음")],
                              string="결과", compute="_compute_result", store=True, readonly=False)
    remark = fields.Char(string="비고")

    def _has_spec(self):
        self.ensure_one()
        return bool(self.spec_min) or bool(self.spec_max)

    def judge_value(self):
        """'ok' | 'ng' | 'no_spec' | 'no_value'.

        기준값 0 은 '미설정' 으로 읽는다. 측정값 0 도 '미기입' 으로 읽는다.
        0 을 기준·측정값으로 읽으면 기준을 넣은 적 없는 항목이 전부 부적합으로
        찍혀 없는 결함을 만들어낸다.
        """
        self.ensure_one()
        if not self._has_spec():
            return "no_spec"
        if not self.value:
            return "no_value"
        if self.spec_min and self.value < self.spec_min:
            return "ng"
        if self.spec_max and self.value > self.spec_max:
            return "ng"
        return "ok"

    @api.depends("value", "spec_min", "spec_max")
    def _compute_result(self):
        for rec in self:
            judged = rec.judge_value()
            if judged in ("ok", "ng"):
                rec.result = judged
            else:
                # 정성 항목·미기입은 사람이 고른다. 계산으로 덮지 않는다.
                rec.result = rec.result

    @api.constrains("result", "value", "spec_min", "spec_max")
    def _check_result_matches_spec(self):
        """기준이 판정한 결과와 다른 결과를 저장하지 못하게 막는다.

        `_compute_result` 만으로는 부족하다. 편집 가능한 계산 필드라 의존 필드가
        바뀌지 않는 write(예: result 만 'ok' 로 덮어쓰기)에서는 재계산이 돌지
        않고, 뷰의 readonly 도 서버에서 강제되지 않는다. 즉 여기서 막지 않으면
        상한 밖 측정값에 '양호' 를 적어 넣는 경로가 실제로 열려 있다 —
        그 경로가 곧 허위기재(SQ 다수미흡 25%)다.

        같은 규칙이 `iatf.mold.check.line._check_result_matches_spec` 에도 있다.
        둘 중 하나만 고치면 구멍이 생긴다. 하나로 합치는 작업은 PR #31 병합 후.
        """
        labels = dict(self._fields["result"].selection)
        for rec in self:
            judged = rec.judge_value()
            if judged in ("ok", "ng") and rec.result != judged:
                raise ValidationError(_(
                    "'%(item)s' 의 측정값 %(value)s 는 기준(%(low)s ~ %(high)s)상 "
                    "'%(judged)s' 입니다. '%(given)s' 으로 저장할 수 없습니다.",
                    item=rec.item_name, value=rec.value,
                    low=rec.spec_min or "-", high=rec.spec_max or "-",
                    judged=labels.get(judged), given=labels.get(rec.result) or _("미판정")))
            # 수치 기준이 있는 항목에 측정값 없이 '양호/불량' 을 넣는 경로를 막는다.
            # (제3자 검토 Q12 — 순수 함수 재현으로 실제 뚫림을 확인함)
            if judged == "no_value" and rec.result in ("ok", "ng"):
                raise ValidationError(_(
                    "'%(item)s' 은 기준(%(low)s ~ %(high)s)이 있는 항목입니다. 측정값 없이 "
                    "'%(given)s' 을 기록할 수 없습니다. 측정값을 적으면 자동 판정됩니다.",
                    item=rec.item_name, low=rec.spec_min or "-", high=rec.spec_max or "-",
                    given=labels.get(rec.result)))

    @api.constrains("spec_min", "spec_max")
    def _check_spec_range(self):
        for rec in self:
            if rec.spec_min and rec.spec_max and rec.spec_min > rec.spec_max:
                raise ValidationError(_(
                    "'%(item)s' 의 하한(%(low)s) 이 상한(%(high)s) 보다 큽니다.",
                    item=rec.item_name, low=rec.spec_min, high=rec.spec_max))

    @api.model_create_multi
    def create(self, vals_list):
        """완료된 실적에 항목을 새로 달 수 없다. (제3자 재검토 R01)"""
        records = super().create(vals_list)
        locked = records.filtered(lambda l: l.record_id.state == "done")
        if locked:
            raise ValidationError(_(
                "완료된 점검 실적(%s)에는 항목을 추가할 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                ", ".join(locked.mapped("record_id.name"))))
        return records

    def write(self, vals):
        """완료된 실적의 라인은 고칠 수 없다. 부모 이동도 막는다 (아스트라 재검토 ②).

        완료 실적은 '그때 그 기준으로 그렇게 판정했다' 는 증빙이다. 완료 후 측정값이나
        기준 스냅샷을 바꾸면 증빙이 아니라 편집물이 된다. 고쳐야 하면 '작성 중' 으로
        되돌린다(상태 변경은 chatter 에 남는다). (제3자 검토 Q10)
        """
        sources = self.record_id
        if "record_id" in vals:
            moving = self.filtered(lambda l: l.record_id.was_done or l.record_id.state == "done")
            if moving:
                raise ValidationError(_(
                    "완료된 적이 있는 점검 실적(%s)의 항목은 다른 실적으로 옮길 수 없습니다.",
                    ", ".join(moving.mapped("record_id.name"))))
            # 도착지도 봐야 한다. 미판정 라인을 완료된 실적으로 옮기면 그 실적은
            # '완료' 인 채 '미완료' 판정이 되고, 부모 write 잠금은 이 경로를 지나지
            # 않는다. (아스트라 독립재현 ②)
            target = self.env["iatf.check.record"].browse(vals["record_id"]).exists()
            if target and target.state == "done":
                raise ValidationError(_(
                    "완료된 점검 실적(%s)으로 항목을 옮길 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                    target.name))
        locked = self.filtered(lambda l: l.record_id.state == "done")
        if locked:
            raise ValidationError(_(
                "완료된 점검 실적(%s)의 항목은 수정할 수 없습니다. 먼저 '작성 중' 으로 되돌리십시오.",
                ", ".join(locked.mapped("record_id.name"))))
        res = super().write(vals)
        (sources | self.record_id).exists()._check_done_is_complete()
        return res

    def unlink(self):
        """완료된 실적의 라인은 지울 수 없다. 지운 뒤에는 부모를 다시 검사한다.

        자식 삭제는 부모의 `@api.constrains("line_ids")` 를 트리거하지 않는다.
        완료된 점검표의 라인을 전부 지우면 판정 내용이 없는 '완료' 실적이 남고,
        그 실적이 시트의 최근 점검일로 잡혀 미실시 목록에서 사라진다.
        """
        # 상태만 보면 '작성 중' 으로 되돌린 뒤 항목을 지워 증빙을 비울 수 있다.
        # 삭제를 막는 근거는 지금 상태가 아니라 **완료된 적이 있다는 사실**이다.
        # 값을 고치는 것은 되돌린 상태에서 여전히 가능하다. (아스트라 독립재현 ②)
        locked = self.filtered(
            lambda l: l.record_id.state == "done" or l.record_id.was_done)
        if locked:
            raise ValidationError(_(
                "완료된 적이 있는 점검 실적(%s)의 항목은 삭제할 수 없습니다.",
                ", ".join(locked.mapped("record_id.name"))))
        parents = self.record_id
        res = super().unlink()
        parents.exists()._check_done_is_complete()
        return res


class IatfCheckRecordSnapshot(models.Model):
    """점검 실적 완료 시점의 측정값 전문.

    완료 실적을 고치려면 '작성 중' 으로 되돌려야 한다(값 수정은 그때 열린다). 그런데
    되돌려 고치고 다시 완료하면 **처음 완료했을 때의 측정값이 사라진다.** 심사에서
    묻는 것은 '지금 값' 이 아니라 '그때 그렇게 판정했는가' 이므로, 완료로 넘어갈 때마다
    그 시점의 전문을 여기에 한 벌 얼려 둔다. 개정 차수가 1 씩 올라간다.
    (아스트라 후속 — 완료 전 측정 전체 snapshot 및 새 revision)

    이 원장은 **덧붙이기 전용**이다. 수정도 삭제도 되지 않는다.
    """

    _name = "iatf.check.record.snapshot"
    _description = "점검 실적 완료 스냅샷"
    _order = "record_id desc, revision desc"

    record_id = fields.Many2one(
        "iatf.check.record", string="점검 실적", required=True,
        ondelete="cascade", index=True, readonly=True,
    )
    revision = fields.Integer(string="완료 차수", required=True, readonly=True,
                              help="몇 번째 완료인가. 되돌려 고친 뒤 다시 완료하면 1 올라간다.")
    done_at = fields.Datetime(string="완료 시각", required=True, readonly=True)
    done_by_id = fields.Many2one("res.users", string="완료 처리자", readonly=True)
    overall_result = fields.Char(string="그때의 종합 판정", readonly=True)
    ng_count = fields.Integer(string="그때의 이상 항목 수", readonly=True)
    line_count = fields.Integer(string="항목 수", readonly=True)
    content = fields.Text(
        string="측정값 전문", readonly=True,
        help="완료 시점 각 항목의 기준·측정값·판정·비고. 이후 어떤 경로로도 바뀌지 않는다.",
    )
    # ── 완료 당시의 원본 식별 정보 (동결) ──
    sheet_id = fields.Many2one("iatf.check.sheet", string="그때의 점검 시트", readonly=True)
    sheet_name = fields.Char(string="그때의 점검 시트(문자)", readonly=True)
    sheet_revision = fields.Integer(string="그때의 시트 개정 차수", readonly=True)
    check_date = fields.Date(string="그때의 점검일", readonly=True)
    shift = fields.Char(string="그때의 근무조", readonly=True)
    checker_id = fields.Many2one("res.users", string="그때의 점검자", readonly=True)
    checker_name = fields.Char(string="그때의 점검자(문자)", readonly=True)
    company_id = fields.Many2one(
        "res.company", string="그때의 회사", readonly=True,
        help="완료 시점의 회사를 복사해 둔다. 부모의 회사가 바뀌어도 과거 증빙은 그대로다.",
    )
    company_name = fields.Char(string="그때의 회사(문자)", readonly=True)

    _sql_constraints = [
        ("record_revision_uniq", "unique(record_id, revision)",
         "같은 점검 실적에 같은 완료 차수가 두 번 있을 수 없습니다."),
        ("revision_positive", "CHECK(revision > 0)",
         "완료 차수는 1 이상이어야 합니다."),
    ]

    _SERVICE_KEY = "iatf_check_record_snapshot_service"

    @api.model_create_multi
    def create(self, vals_list):
        """완료 처리 과정에서만, 서버가 만든 값으로만 생성된다. (275 리뷰 Q275-01)"""
        if not self.env.context.get(self._SERVICE_KEY):
            raise ValidationError(_(
                "완료 스냅샷은 점검 실적을 완료할 때 자동으로 만들어집니다. "
                "직접 추가할 수 없습니다."))
        Record = self.env["iatf.check.record"]
        prepared = []
        for vals in vals_list:
            record = Record.browse(vals.get("record_id") or 0).exists()
            if not record:
                raise ValidationError(_("스냅샷의 대상 점검 실적을 찾을 수 없습니다."))
            if record.state != "done":
                raise ValidationError(_(
                    "완료되지 않은 점검 실적(%s)의 스냅샷은 만들 수 없습니다.", record.name))
            prepared.append(record._snapshot_values())
        return super().create(prepared)

    def write(self, vals):
        raise ValidationError(_("완료 스냅샷은 수정할 수 없습니다. 증빙 원본입니다."))

    def unlink(self):
        raise ValidationError(_("완료 스냅샷은 삭제할 수 없습니다. 증빙 원본입니다."))
