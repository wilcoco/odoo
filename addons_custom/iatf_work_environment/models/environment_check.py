from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.iatf_document_control.models.quality_guards import (
    is_blank, policy_enabled, internal_call, is_internal_call,
)


class IatfEnvironmentCheck(models.Model):
    _name = "iatf.environment.check"
    _description = "작업환경 점검 기록"
    _inherit = ["mail.thread"]
    _order = "check_date desc"

    name = fields.Char(
        string="점검 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    work_area_id = fields.Many2one("iatf.work.area", string="작업 구역", required=True, tracking=True)
    check_type = fields.Selection(
        [
            ("environment", "환경 모니터링"),
            ("fiveS", "5S 점검"),
            ("safety", "안전 점검"),
        ],
        string="점검 유형", required=True, default="environment",
    )
    check_date = fields.Datetime(string="점검 일시", default=fields.Datetime.now, required=True)
    checker_id = fields.Many2one("res.users", string="점검자",
                                  default=lambda self: self.env.user)

    # ── 환경 측정값 ──
    temperature = fields.Float(string="온도 (°C)")
    humidity = fields.Float(string="습도 (%)")
    lighting = fields.Float(string="조도 (Lux)")
    noise = fields.Float(string="소음 (dB)")
    dust = fields.Char(string="분진")

    # ── 5S 점검 ──
    score_seiri = fields.Integer(string="정리 (1S)", help="0~10")
    score_seiton = fields.Integer(string="정돈 (2S)", help="0~10")
    score_seiso = fields.Integer(string="청소 (3S)", help="0~10")
    score_seiketsu = fields.Integer(string="청결 (4S)", help="0~10")
    score_shitsuke = fields.Integer(string="습관화 (5S)", help="0~10")
    fiveS_total = fields.Integer(string="5S 합계", compute="_compute_5s_total", store=True)

    # ── 판정 ──
    line_ids = fields.One2many("iatf.environment.check.line", "check_id", string="세부 점검 항목")
    result = fields.Selection(
        [("pass", "적합"), ("fail", "부적합"), ("action", "조치 필요")],
        string="판정", tracking=True,
    )
    corrective_action = fields.Text(string="시정 조치")
    ng_count = fields.Integer(string="부적합 항목 수", compute="_compute_line_stats", store=True)
    pending_count = fields.Integer(string="미판정 항목 수", compute="_compute_line_stats", store=True)

    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [("draft", "초안"), ("done", "완료")],
        string="상태", default="draft", tracking=True,
    )

    @api.depends("score_seiri", "score_seiton", "score_seiso", "score_seiketsu", "score_shitsuke")
    def _compute_5s_total(self):
        for rec in self:
            rec.fiveS_total = (rec.score_seiri + rec.score_seiton + rec.score_seiso +
                               rec.score_seiketsu + rec.score_shitsuke)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.environment.check") or _("New")
        records = super().create(vals_list)
        # 처음부터 `done` 으로 **만드는** 길도 막는다 (아스트라 A-40-S02).
        # 완료 검사는 `action_done` 에만 있었고 생성에는 없었습니다.
        born_done = records.filtered(lambda r: r.state == "done")
        # **완료 '진입' 검증은 완료 후 '잠금' 과 다른 정책이다** (아스트라 A-40-S02).
        # 두 가드를 `quality.env_check_lock_after_done` 하나에 묶어 두면, 잠금을
        # 끈 회사에서는 완료 상태 직접 생성·직접 쓰기까지 열려 완료 버튼의
        # 판정 검사(미판정·해당없음 사유·모순)가 통째로 빠집니다.
        if born_done and not is_internal_call(self.env, "env_check_completing") \
                and policy_enabled(self.env, "quality.env_check_require_done_button", True):
            raise UserError(_(
                "완료 상태로 바로 만들 수 없습니다. 초안으로 만든 뒤 완료 버튼을 "
                "쓰십시오 — 판정 근거를 함께 확인합니다. (%s)",
                ", ".join(born_done.mapped("name"))))
        return records

    @api.depends("line_ids.result", "line_ids.measured_value")
    def _compute_line_stats(self):
        # 측정값 없는 "적합"은 미판정으로 센다(478 #40).
        for rec in self:
            lines = rec.line_ids
            rec.ng_count = len(lines.filtered(lambda l: l.result == "ng"))
            rec.pending_count = len(lines.filtered(
                lambda l: l.result in (False, "pending")
                or (l.result == "ok" and is_blank(l.measured_value))))

    def action_done(self):
        blocks_pending = policy_enabled(self.env, "quality.env_check_pending_blocks_done", True)
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("초안 상태에서만 완료할 수 있습니다. (%s)", rec.name))
            if not rec.result:
                raise UserError(_("전체 판정을 입력해 주세요. (%s)", rec.name))
            if blocks_pending and rec.pending_count:
                raise UserError(_(
                    "미판정 항목이 %(count)d건 있습니다. 측정값과 판정을 입력한 뒤 완료하십시오. (%(name)s)",
                    count=rec.pending_count, name=rec.name))
            for line in rec.line_ids:
                if line.result == "na" and is_blank(line.remark):
                    raise UserError(_(
                        "해당없음 항목에는 사유가 필요합니다: %(item)s (%(name)s)",
                        item=line.item_name, name=rec.name))
            if rec.result == "pass" and rec.ng_count:
                raise UserError(_(
                    "부적합 항목이 %(count)d건 있어 전체 적합으로 완료할 수 없습니다. "
                    "부적합 또는 조치 필요로 판정하십시오. (%(name)s)",
                    count=rec.ng_count, name=rec.name))
            if rec.result == "action" and is_blank(rec.corrective_action):
                raise UserError(_("조치 필요 판정에는 시정 조치 내용이 필요합니다. (%s)", rec.name))
        internal_call(self, "env_check_completing").write({"state": "done"})
        return True

    # ── 완료 뒤 보호와 사유 있는 재개 (533 §2) ────────────────────
    #
    # 완료 **전** 모순 차단만 넣고 **완료 뒤 보호**를 빼먹었습니다
    # (아스트라 A-40-S01). 그래서 정상 완료한 기록의 전체 판정만 '적합' 으로
    # 바꾸거나 세부 항목을 고쳐, 완료 상태에서 "부적합 항목이 있는데 전체
    # 적합" 이라는 모순을 만들 수 있었습니다. 완료 전 검사는 다시 돌지 않습니다.
    _LOCKED_AFTER_DONE = ("result", "line_ids", "corrective_action")
    _ALLOWED_EXITS = {"done": ()}

    def write(self, vals):
        vals = vals or {}
        # **초안 → 완료 직접 쓰기**를 막는다 (아스트라 A-40-S02).
        # 완료 버튼의 판정 검사(미판정 항목·해당없음 사유·모순)를 지나가지
        # 못하게 하는 **진입** 가드이므로, 완료 뒤 **잠금** 설정과 분리해
        # `quality.env_check_require_done_button` 로 둔다. 잠금을 끈 회사에서
        # 완료 진입 검증까지 사라지지 않게 한다.
        if vals.get("state") == "done" \
                and not is_internal_call(self.env, "env_check_completing") \
                and policy_enabled(self.env, "quality.env_check_require_done_button", True):
            for rec in self:
                if rec.state != "done":
                    raise UserError(_(
                        "'완료' 로 직접 바꿀 수 없습니다. 완료 버튼을 쓰십시오 "
                        "— 전체 판정·미판정 항목·해당없음 사유·모순을 함께 "
                        "확인합니다. (%s)", rec.name))
        if policy_enabled(self.env, "quality.env_check_lock_after_done", True) \
                and not is_internal_call(self.env, "env_check_completing") \
                and not is_internal_call(self.env, "env_check_reopen"):
            touched = set(vals) & set(self._LOCKED_AFTER_DONE)
            changes_state = "state" in vals
            target = vals.get("state")
            for rec in self:
                if rec.state != "done":
                    continue
                if touched:
                    raise UserError(_(
                        "완료된 점검의 판정·항목을 직접 고칠 수 없습니다. "
                        "사유를 남기는 재개를 쓰십시오. (%s)", rec.name))
                if changes_state and target != rec.state \
                        and target not in self._ALLOWED_EXITS.get(rec.state, ()):
                    raise UserError(_(
                        "완료 상태에서 '%(target)s' 로 직접 바꿀 수 없습니다. "
                        "사유를 남기는 재개를 쓰십시오. (%(name)s)",
                        target=target or _("빈값"), name=rec.name))
        return super().write(vals)

    def action_reopen(self, reason=False):
        """완료된 점검을 사유와 함께 초안으로 되돌린다 (533 §2)."""
        reason = reason or self.env.context.get("env_check_reopen_reason")
        if is_blank(reason):
            raise UserError(_("재개 사유를 입력하십시오."))
        for rec in self:
            if rec.state != "done":
                raise UserError(_("완료된 점검만 재개할 수 있습니다. (%s)", rec.name))
            rec.message_post(body=_("점검 재개 — 사유: %s", reason))
        internal_call(self, "env_check_reopen").write({"state": "draft"})
        return True


class IatfEnvironmentCheckLine(models.Model):
    _name = "iatf.environment.check.line"
    _description = "환경점검 세부 항목"
    _order = "sequence"

    check_id = fields.Many2one("iatf.environment.check", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    item_name = fields.Char(string="점검 항목", required=True)
    standard = fields.Char(string="기준")
    measured_value = fields.Char(string="측정값/확인 결과")
    result = fields.Selection(
        [("pending", "미판정"), ("ok", "적합"), ("ng", "부적합"), ("na", "해당없음")],
        string="판정", default="pending",
    )
    remark = fields.Char(string="비고")

    # 완료된 부모의 항목을 직접 고치지 못한다 (533 §2).
    def _assert_parent_open(self, action):
        for line in self:
            parent = line.check_id
            if not parent or parent.state != "done":
                continue
            if is_internal_call(parent.env, "env_check_reopen"):
                continue
            if not policy_enabled(parent.env, "quality.env_check_lock_after_done", True):
                continue
            raise UserError(_(
                "완료된 점검(%(name)s)의 항목은 %(action)s 할 수 없습니다. "
                "사유를 남기는 재개를 거치십시오.", name=parent.name, action=action))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assert_parent_open(_("추가"))
        return records

    def write(self, vals):
        self._assert_parent_open(_("수정"))
        target_id = (vals or {}).get("check_id")
        if target_id:
            target = self.env["iatf.environment.check"].browse(target_id).exists()
            if target and target.state == "done" \
                    and not is_internal_call(self.env, "env_check_reopen") \
                    and policy_enabled(self.env, "quality.env_check_lock_after_done", True):
                raise UserError(_(
                    "완료된 점검(%s)으로 항목을 옮길 수 없습니다.", target.name))
        return super().write(vals)

    def unlink(self):
        self._assert_parent_open(_("삭제"))
        return super().unlink()
