from odoo import api, fields, models, _
from odoo.addons.iatf_document_control.models.quality_guards import is_blank, policy_enabled
from odoo.exceptions import UserError, ValidationError


class IatfLayoutInspection(models.Model):
    _name = "iatf.layout.inspection"
    _description = "레이아웃 검사 (IATF 16949 §8.6.2)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    inspection_date = fields.Date(string="검사일", default=fields.Date.today, required=True)

    # ── 제품 정보 ──
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    customer_id = fields.Many2one("res.partner", string="고객", tracking=True)
    drawing_number = fields.Char(string="도면 번호")
    drawing_revision = fields.Char(string="도면 개정")

    # ── 검사 유형 ──
    inspection_type = fields.Selection(
        [
            ("layout", "레이아웃 검사 (전 치수)"),
            ("functional", "기능 시험"),
            ("both", "레이아웃 + 기능 시험"),
        ],
        string="검사 유형", required=True, default="layout",
    )
    frequency = fields.Char(string="검사 주기", help="예: 연 1회, 고객 요구 시")
    last_inspection_date = fields.Date(string="이전 검사일")

    # ── 샘플 ──
    sample_size = fields.Integer(string="샘플 수량", default=1)
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")

    # ── 검사 항목 ──
    line_ids = fields.One2many("iatf.layout.inspection.line", "inspection_id", string="검사 항목")
    total_characteristics = fields.Integer(string="총 항목 수", compute="_compute_stats", store=True)
    pass_count = fields.Integer(string="합격 수", compute="_compute_stats", store=True)
    fail_count = fields.Integer(string="불합격 수", compute="_compute_stats", store=True)
    pending_count = fields.Integer(string="미판정 수", compute="_compute_stats", store=True)

    # ── 판정 ──
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("conditional", "조건부 합격")],
        string="판정 결과", tracking=True,
    )

    # ── 담당자 ──
    inspector_id = fields.Many2one("res.users", string="검사원",
                                    default=lambda self: self.env.user, tracking=True)
    approved_by = fields.Many2one("res.users", string="승인자")

    # ── 연결 ──
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("inspecting", "검사 중"),
            ("decided", "판정 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    @api.depends("line_ids.result", "line_ids.measured_value")
    def _compute_stats(self):
        # 측정값이 없는 항목은 합격으로 세지 않는다. 미판정은 따로 센다(478 #30).
        for rec in self:
            lines = rec.line_ids
            rec.total_characteristics = len(lines)
            rec.pass_count = len(lines.filtered(
                lambda l: l.result == "pass" and not is_blank(l.measured_value)))
            rec.fail_count = len(lines.filtered(lambda l: l.result == "fail"))
            rec.pending_count = len(lines.filtered(
                lambda l: l.result in (False, "pending")
                or (l.result == "pass" and is_blank(l.measured_value))))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.layout.inspection") or _("New")
        return super().create(vals_list)

    def action_start(self):
        """검사를 시작한다. 판정 완료·종료에서 되돌리는 길이 아니다.

        전에는 상태 검사가 없어 판정 완료 기록을 '검사 중' 으로 되돌릴 수
        있었고, 그러면 잠금이 풀려 사유 없이 결과를 고칠 수 있었다
        (아스트라 A-01).
        """
        for rec in self:
            if rec.state in ("decided", "closed"):
                raise UserError(_(
                    "판정 완료·종료된 검사는 '검사 시작' 으로 되돌릴 수 없습니다. "
                    "사유를 남기는 재검토를 쓰십시오. (%s)", rec.name))
        self.write({"state": "inspecting"})
        return True

    def action_decide(self):
        blocks_pending = policy_enabled(self.env, "quality.layout_pending_blocks_decide", True)
        for rec in self:
            if rec.state not in ("draft", "inspecting"):
                raise UserError(_("검사 중 상태에서만 판정할 수 있습니다. (%s)", rec.name))
            if not rec.line_ids:
                raise UserError(_("검사 항목이 없습니다. 항목을 입력한 뒤 판정하십시오. (%s)", rec.name))
            if not rec.result:
                raise UserError(_("판정 결과를 입력해 주세요."))
            if blocks_pending and rec.pending_count:
                raise UserError(_(
                    "미판정 항목이 %(count)d건 있습니다. 측정값과 항목 판정을 입력한 뒤 판정하십시오. (%(name)s)",
                    count=rec.pending_count, name=rec.name))
            for line in rec.line_ids:
                if line.result == "pass" and is_blank(line.measured_value):
                    raise UserError(_(
                        "측정값 없이 합격으로 둘 수 없습니다: %(item)s (%(name)s)",
                        item=line.characteristic_name, name=rec.name))
                if line.result == "na" and is_blank(line.notes):
                    raise UserError(_(
                        "해당없음 항목에는 사유가 필요합니다: %(item)s (%(name)s)",
                        item=line.characteristic_name, name=rec.name))
            if rec.result == "pass" and rec.fail_count:
                raise UserError(_(
                    "불합격 항목이 %(count)d건 있어 전체 합격으로 판정할 수 없습니다. "
                    "불합격 또는 조건부 합격으로 판정하십시오. (%(name)s)",
                    count=rec.fail_count, name=rec.name))
        self.write({"state": "decided"})

    def action_close(self):
        for rec in self:
            if rec.state != "decided":
                raise UserError(_("판정 완료 상태에서만 종료할 수 있습니다. (%s)", rec.name))
        self.write({"state": "closed"})

    def action_reopen(self, reason=False):
        """판정 뒤 정정은 사유를 남기고 검사 중으로 되돌린 뒤에만 한다(478 #30)."""
        reason = reason or self.env.context.get("layout_reopen_reason")
        if is_blank(reason):
            raise UserError(_("재검토 사유를 입력하십시오."))
        for rec in self:
            if rec.state not in ("decided", "closed"):
                raise UserError(_("판정 완료·종료 상태에서만 재검토할 수 있습니다. (%s)", rec.name))
            rec.message_post(body=_("재검토 시작 — 사유: %s", reason))
        self.with_context(layout_reopen=True).write({"state": "inspecting"})
        return True

    _LOCKED_AFTER_DECIDE = ("result", "line_ids")
    # 판정 완료·종료에서 **직접 쓰기로** 나갈 수 있는 상태.
    # 'inspecting' 은 없다 — 되돌리려면 사유를 남기는 재검토를 써야 한다.
    _ALLOWED_EXITS = {"decided": ("closed",), "closed": ()}

    def write(self, vals):
        """판정 뒤에는 판정값·항목을 직접 고치지 못한다. 정정은 재검토 경유.

        전에는 `vals.get("state") is None` 일 때만 잠금을 봤다. 그래서 상태를
        **같은 값으로** 함께 쓰면(`{"state": "decided", "result": "fail"}`)
        검사가 건너뛰어졌고, 판정 완료 상태 그대로 결과만 바뀌었다
        (아스트라 A-01, 분리 함수 실행으로 재현). 상태 키가 있는지가 아니라
        **지금 상태**로 판단한다.
        """
        if policy_enabled(self.env, "quality.layout_lock_after_decide", True) \
                and not self.env.context.get("layout_reopen"):
            touched = set(vals) & set(self._LOCKED_AFTER_DECIDE)
            # **키가 있는지**와 **값이 참인지**를 따로 본다.
            # 전에는 `if target and ...` 이라 `write({"state": False})` 가 검사를
            # 지나갔고, 그러면 상태가 빈값이 되어 다음 write 의 잠금 검사도
            # 지나갔다(아스트라 A-01-R1 잔여).
            changes_state = "state" in vals
            target = vals.get("state")
            for rec in self:
                if rec.state not in ("decided", "closed"):
                    continue
                if touched:
                    raise UserError(_(
                        "판정 완료 뒤에는 판정·항목을 직접 고칠 수 없습니다. "
                        "재검토(사유 입력)를 거치십시오. (%s)", rec.name))
                # 상태만 되돌리는 길도 막는다. 전에는 touched 가 비어 통과했고,
                # 일단 'inspecting' 이 되면 그다음 결과 수정이 자유로웠다
                # (아스트라 A-01-R1). 판정 완료에서 나가는 길은 종료와
                # 재검토뿐이다.
                if changes_state and target != rec.state \
                        and target not in self._ALLOWED_EXITS.get(rec.state, ()):
                    raise UserError(_(
                        "판정 완료·종료 상태에서 '%(target)s' 로 직접 바꿀 수 없습니다. "
                        "사유를 남기는 재검토를 쓰십시오. (%(name)s)",
                        target=target or _("빈값"), name=rec.name))
        return super().write(vals)

    @api.model
    def _cron_layout_inspection_reminder(self):
        """월간 실행: 연간 레이아웃 검사 미수행 제품 알림"""
        from datetime import timedelta
        one_year_ago = fields.Date.today() - timedelta(days=365)
        # 최근 1년간 검사 완료된 제품
        recent = self.search([
            ("state", "in", ("decided", "closed")),
            ("inspection_date", ">=", one_year_ago),
        ])
        done_products = set(recent.mapped("product_id").ids)
        # 이전에 검사한 적 있지만 1년 초과된 제품
        old = self.search([
            ("state", "in", ("decided", "closed")),
            ("inspection_date", "<", one_year_ago),
        ])
        overdue_products = set(old.mapped("product_id").ids) - done_products
        for pid in overdue_products:
            last = self.search([
                ("product_id", "=", pid),
                ("state", "in", ("decided", "closed")),
            ], order="inspection_date desc", limit=1)
            if last:
                last.activity_schedule(
                    "mail.mail_activity_data_todo",
                    summary=_("연간 레이아웃 검사 미수행: %s (최근: %s)") % (
                        last.product_id.name, last.inspection_date),
                    user_id=last.inspector_id.id if last.inspector_id else self.env.ref("base.user_admin").id,
                )


class IatfLayoutInspectionLine(models.Model):
    _name = "iatf.layout.inspection.line"
    _description = "레이아웃 검사 항목"
    _order = "sequence, id"

    inspection_id = fields.Many2one(
        "iatf.layout.inspection", string="검사", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    balloon_number = fields.Char(string="풍선 번호")
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("geometric", "기하공차"), ("surface", "표면"),
         ("functional", "기능"), ("material", "재질"), ("visual", "외관")],
        string="항목 유형", default="dimensional",
    )
    special_characteristic = fields.Selection(
        [("none", "없음"), ("cc", "CC"), ("sc", "SC")],
        string="특별 특성", default="none",
    )
    nominal = fields.Char(string="규격 / 기준값")
    tolerance = fields.Char(string="공차")
    measured_value = fields.Char(string="측정값")
    deviation = fields.Char(string="편차")
    result = fields.Selection(
        [("pending", "미판정"), ("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="판정", default="pending",
    )
    measurement_tool = fields.Char(string="측정기")
    notes = fields.Char(string="비고")

    # 부모가 판정 완료·종료면 항목을 직접 고치지 못한다 (아스트라 A-01).
    #
    # 부모의 `line_ids` 잠금은 **부모를 거쳐 쓸 때만** 동작한다. 검사 사용자
    # ACL 에 자식 쓰기·생성이 있어서, 항목을 직접 수정하면 잠금을 지나친다.
    # 그래서 같은 규칙을 자식에도 둔다.

    def _assert_parent_open(self, action):
        for line in self:
            parent = line.inspection_id
            if not parent:
                continue
            if parent.env.context.get("layout_reopen"):
                continue
            if not policy_enabled(parent.env, "quality.layout_lock_after_decide", True):
                continue
            if parent.state in ("decided", "closed"):
                raise UserError(_(
                    "판정 완료된 검사(%(name)s)의 항목은 %(action)s 할 수 없습니다. "
                    "재검토(사유 입력)를 거치십시오.",
                    name=parent.name, action=action))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._assert_parent_open(_("추가"))
        return records

    def write(self, vals):
        self._assert_parent_open(_("수정"))
        # 항목을 **판정 완료된 다른 검사로 옮기는** 길도 막는다. 전에는 원래
        # 부모만 봤기 때문에, 열린 검사의 항목을 판정 완료 검사로 옮겨 그
        # 검사의 근거 구성을 바꿀 수 있었다(아스트라 A-01-R2).
        target_id = (vals or {}).get("inspection_id")
        if target_id:
            target = self.env["iatf.layout.inspection"].browse(target_id).exists()
            if target and target.state in ("decided", "closed") \
                    and not self.env.context.get("layout_reopen") \
                    and policy_enabled(self.env, "quality.layout_lock_after_decide", True):
                raise UserError(_(
                    "판정 완료된 검사(%s)로 항목을 옮길 수 없습니다. "
                    "재검토(사유 입력)를 거치십시오.", target.name))
        return super().write(vals)

    def unlink(self):
        self._assert_parent_open(_("삭제"))
        return super().unlink()

    # 빈 측정값으로 '합격' 을 **저장하는 것 자체**를 막는다 (511 §2).
    #
    # 판정 완료 시점 검사는 넣었지만 **저장 거부**는 빼먹었습니다. 그래서
    # 측정하지 않은 행을 합격으로 저장해 두고 나중에 측정값을 지우는 길이
    # 남았습니다(아스트라 A-30-S01). 해당없음(`na`)은 측정값이 없어도 됩니다.
    @api.constrains("result", "measured_value")
    def _check_pass_has_measurement(self):
        if not policy_enabled(self.env, "quality.layout_pass_needs_measurement", True):
            return
        for line in self:
            if line.result == "pass" and is_blank(line.measured_value):
                raise ValidationError(_(
                    "측정값 없이 '합격' 으로 저장할 수 없습니다. 측정값을 적거나 "
                    "'해당없음' 으로 두십시오. (%s)",
                    line.characteristic_name or "-"))
