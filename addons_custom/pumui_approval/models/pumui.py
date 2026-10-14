from odoo import api, fields, models, _
from odoo.exceptions import UserError

PAYMENT_STAGE = [
    ("normal", "일반"),
    ("down", "계약금"),
    ("interim", "중도금"),
    ("balance", "잔금"),
]


_INVOICE_LINK_TOKEN = object()   # 청구서 생성 경로 전용 내부 표식. RPC context 로는 만들 수 없는 객체 identity 로만 비교한다.


class PumuiRequest(models.Model):
    """품의서 — 지출/수금 내부 승인 문서. 결재 승인 후에만 청구서 생성·전기 가능.

    회계 사용 리포트 #6(품의서-청구서 연결)·#7(결재/승인/반려 흐름) 대응.
    결재선은 검증된 iatf.approval.mixin(다단계 승인·반려·이력)을 재사용."""

    _name = "pumui.request"
    _description = "품의서"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"

    name = fields.Char(string="품의 번호", required=True, copy=False, readonly=True,
                       default=lambda self: _("New"))
    title = fields.Char(string="제목", required=True, tracking=True)
    pumui_type = fields.Selection(
        [("purchase", "지출 품의 (공급업체 청구서)"), ("sale", "수금 품의 (고객 청구서)")],
        string="품의 구분", required=True, default="purchase", tracking=True)
    date = fields.Date(string="기안일", default=fields.Date.context_today, required=True)
    partner_id = fields.Many2one("res.partner", string="거래처", required=True, tracking=True)
    project_id = fields.Many2one("project.project", string="프로젝트")
    contract_name = fields.Char(string="계약명")
    requester_id = fields.Many2one("res.users", string="기안자",
                                   default=lambda self: self.env.user, readonly=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    currency_id = fields.Many2one(related="company_id.currency_id")

    line_ids = fields.One2many("pumui.request.line", "pumui_id", string="품의 항목")

    amount_untaxed = fields.Monetary(string="공급가액", compute="_compute_amounts", store=True)
    amount_tax = fields.Monetary(string="세액", compute="_compute_amounts", store=True)
    amount_total = fields.Monetary(string="합계금액", compute="_compute_amounts", store=True)

    # ── 청구/지급 현황 (리포트: 승인 금액 vs 청구서 금액 연동·잔액 관리) ──
    move_ids = fields.One2many("account.move", "pumui_id", string="연결 청구서")
    move_count = fields.Integer(compute="_compute_billing")
    invoiced_amount = fields.Monetary(string="청구 완료 금액", compute="_compute_billing")
    paid_amount = fields.Monetary(string="지급/수금 완료 금액", compute="_compute_billing")
    uninvoiced_amount = fields.Monetary(string="미청구 잔액", compute="_compute_billing")
    billing_status = fields.Selection(
        [("none", "미청구"), ("partial", "부분 청구"), ("invoiced", "청구 완료"), ("paid", "지급 완료")],
        string="청구/지급 상태", compute="_compute_billing")
    amount_diff = fields.Monetary(string="품의-청구 차이", compute="_compute_billing",
                                  help="승인 품의 총액 − 연결 청구서 총액. 0이 아니면 확인 필요")

    rejection_reason = fields.Text(string="반려 사유", tracking=True)

    @api.depends("line_ids.price_subtotal", "line_ids.price_tax")
    def _compute_amounts(self):
        for rec in self:
            rec.amount_untaxed = sum(rec.line_ids.mapped("price_subtotal"))
            rec.amount_tax = sum(rec.line_ids.mapped("price_tax"))
            rec.amount_total = rec.amount_untaxed + rec.amount_tax

    @api.depends(
        "move_ids.amount_total",
        "move_ids.amount_residual",
        "move_ids.state",
        "move_ids.move_type",
        "amount_total",
    )
    def _compute_billing(self):
        for rec in self:
            moves = rec.move_ids.filtered(lambda m: m.state != "cancel")
            rec.move_count = len(moves)
            rec.invoiced_amount = sum(
                move.amount_total
                * (-1 if move.move_type in ("out_refund", "in_refund") else 1)
                for move in moves
            )
            posted = moves.filtered(lambda m: m.state == "posted")
            rec.paid_amount = sum(
                (move.amount_total - move.amount_residual)
                * (-1 if move.move_type in ("out_refund", "in_refund") else 1)
                for move in posted
            )
            remaining = rec.amount_total - rec.invoiced_amount
            rec.uninvoiced_amount = max(remaining, 0.0)
            # 미청구분은 잔액으로 보여주고, 승인액을 초과한 경우만 차이로 경고한다.
            rec.amount_diff = min(remaining, 0.0)
            if not moves:
                rec.billing_status = "none"
            elif remaining > 0 and not rec.currency_id.is_zero(remaining):
                rec.billing_status = "partial"
            elif posted and all(
                    m.currency_id.is_zero(m.amount_residual) for m in posted) and len(posted) == len(moves):
                rec.billing_status = "paid"
            else:
                rec.billing_status = "invoiced"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("pumui.request") or _("New")
        return super().create(vals_list)

    def unlink(self):
        linked = self.filtered(lambda request: request.move_ids)
        if linked:
            raise UserError(_(
                "연결된 청구서가 있는 품의서는 삭제할 수 없습니다. 청구서와 품의서의 "
                "감사 이력을 유지해 주세요."
            ))
        return super().unlink()

    _POSTED_EVIDENCE_MESSAGE = "전기된 청구서가 있는 품의의 근거(거래처·회사·구분·청구된 항목·항목 추가/이동/삭제)는 수정할 수 없습니다. 미청구 잔여 항목만 정정할 수 있고, 그 외는 정정 절차(승인 가감·새 품의)를 사용하세요."

    def _has_posted_invoice(self):
        """전기된 청구서가 하나라도 연결된 품의(정산·일반 구분 없음, 보수적 기준 — 총괄 050 R3)."""
        if not self:
            return self.browse()
        posted = self.env["account.move"].sudo().search([("pumui_id", "in", self.ids), ("state", "=", "posted")])
        return posted.mapped("pumui_id") & self

    def _settlement_shared(self):
        """생산 정산 청구서(취소 제외)가 쓰는 품의. 정산 소비량은 청구서 라인↔예산으로 측정되며 라인의
        invoice_line_id 는 비어 있으므로, 전기 정산이 있으면 **라인 전체를 소비 근거로 고정**한다(053)."""
        Move = self.env["account.move"].sudo()
        if not self or "vendor_settlement_bill" not in Move._fields:
            return self.browse()
        return Move.search([("pumui_id", "in", self.ids), ("vendor_settlement_bill", "=", True),
                            ("state", "!=", "cancel")]).mapped("pumui_id") & self

    @staticmethod
    def _line_commands_touch_evidence(commands, lines, all_lines_locked=False):
        """line_ids 명령 중 '미청구 잔여 항목의 값 갱신' 이외(추가·삭제·연결·교체, 청구된 항목 갱신)가 있는가."""
        invoiced = {line.id for line in lines if line.invoice_line_id}
        for command in commands or []:
            op = command[0] if isinstance(command, (list, tuple)) else None
            if op == 1 and command[1] not in invoiced and not all_lines_locked:
                continue          # 미청구 항목 값 정정 → 결재 초기화·새 개정 경로로 허용
            return True
        return False

    def write(self, vals):
        # Child RPC edits must share this lock and the mixin's revision path.
        # 전기된 청구가 있는 품의: 거래처·회사·구분과 항목 구조(추가/이동/삭제), 청구된 항목은 고정.
        # 아직 청구되지 않은 잔여 항목의 값 정정만 기존 정책(결재 초기화·새 개정)으로 허용한다.
        evidence_fields = {"line_ids", "partner_id", "company_id", "pumui_type"}
        if evidence_fields.intersection(vals):
            with self.env.cr.savepoint():
                self.sorted("id")._approval_lock_target()
                locked = self._has_posted_invoice()
                if locked:
                    shared = locked._settlement_shared()
                    if {"partner_id", "company_id", "pumui_type"} & set(vals) or (
                            "line_ids" in vals and self._line_commands_touch_evidence(vals["line_ids"], locked.line_ids, bool(shared))):
                        raise UserError(_(self._POSTED_EVIDENCE_MESSAGE))
                return super().write(vals)
        return super().write(vals)

    # ── 결재 (리포트 #7: 반려 사유 필수, 승인 전 지급 차단) ──
    def action_reject_approval(self):
        for rec in self:
            if not rec.rejection_reason:
                raise UserError(_("반려 사유를 먼저 입력해 주세요. (반려 사유는 필수입니다)"))
            rec.message_post(body=_("반려 사유: %s") % rec.rejection_reason)
        return super().action_reject_approval()

    def action_submit_approval(self):
        for rec in self:
            if not rec.line_ids:
                raise UserError(_("품의 항목이 없습니다. 항목을 입력 후 상신하세요."))
        # 결재선이 비어 있으면 기본 결재선 템플릿(모델/부서/금액 매칭) 먼저 적용
        self._approval_ensure_request()
        self._approval_apply_default_template()
        for rec in self:
            if not rec.approval_line_ids:
                raise UserError(_("결재선(승인자)을 지정한 후 상신하세요. "
                                  "(매칭되는 결재선 템플릿이 없습니다)"))
        return super().action_submit_approval()

    # ── 청구서 생성 (승인 후에만, 단계별 지원) ──
    def _get_invoiceable_lines(self, stage=False):
        self.ensure_one()
        linked_invoice_lines = self.line_ids.mapped("invoice_line_id")
        manually_linked_moves = self.move_ids.filtered(
            lambda move: move.state != "cancel"
            and not (move.invoice_line_ids & linked_invoice_lines)
        )
        if manually_linked_moves:
            raise UserError(_(
                "수동으로 연결한 청구서가 있어 품의서에서 청구서를 자동 생성할 수 "
                "없습니다. 남은 청구서도 공급업체 청구서 화면에서 작성한 뒤 같은 "
                "품의서를 연결해 주세요."
            ))
        lines = self.line_ids.filtered(lambda l: not l.invoiced)
        if stage:
            lines = lines.filtered(lambda l: l.payment_stage == stage)
        return lines

    def action_create_invoice(self, stage=False):
        self.ensure_one()
        if self.approval_state != "approved":
            raise UserError(_("승인 완료된 품의서만 청구서를 생성할 수 있습니다. (현재: 미승인)"))
        lines = self._get_invoiceable_lines(stage=stage)
        if not lines:
            raise UserError(_("청구할 미청구 항목이 없습니다."))
        move_type = "in_invoice" if self.pumui_type == "purchase" else "out_invoice"
        inv_lines = []
        for l in lines:
            inv_lines.append((0, 0, {
                "product_id": l.product_id.id or False,
                "name": l.name,
                "quantity": l.quantity,
                "price_unit": l.price_unit,
                "tax_ids": [(6, 0, l.tax_ids.ids)],
            }))
        move = self.env["account.move"].with_company(self.company_id).create({
            "move_type": move_type,
            "partner_id": self.partner_id.id,
            "company_id": self.company_id.id,
            "invoice_date": fields.Date.context_today(self),
            "ref": _("품의 %s") % self.name,
            "pumui_id": self.id,
            "invoice_line_ids": inv_lines,
        })
        # 품의 라인 ↔ 청구 라인 연결 (순서 매핑)
        product_mls = move.invoice_line_ids.filtered(lambda ml: ml.display_type == "product")
        for l, ml in zip(lines, product_mls):
            l._link_invoice_line(ml)
        self.message_post(body=_("청구서 %s 생성 (%s)") % (
            move.name or move.id, dict(PAYMENT_STAGE).get(stage, _("전체 잔여"))))
        return {
            "type": "ir.actions.act_window", "res_model": "account.move",
            "res_id": move.id, "view_mode": "form", "target": "current",
        }

    def action_open_make_invoice_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "pumui.make.invoice",
            "view_mode": "form", "target": "new",
            "context": {"default_pumui_id": self.id},
            "name": _("청구서 생성"),
        }

    def action_view_moves(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window", "res_model": "account.move",
            "view_mode": "list,form", "name": _("연결 청구서: %s") % self.name,
            "domain": [("pumui_id", "=", self.id)],
        }


class PumuiRequestLine(models.Model):
    _name = "pumui.request.line"
    _description = "품의서 항목"
    _order = "pumui_id, sequence, id"

    pumui_id = fields.Many2one("pumui.request", string="품의서", required=True,
                               ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one("product.product", string="품목")
    name = fields.Char(string="내역", required=True)
    payment_stage = fields.Selection(PAYMENT_STAGE, string="단계", default="normal", required=True)
    quantity = fields.Float(string="수량", default=1.0)
    price_unit = fields.Monetary(string="단가", currency_field="currency_id")
    tax_ids = fields.Many2many("account.tax", string="세금",
                               domain="[('type_tax_use','!=','none')]")
    currency_id = fields.Many2one(related="pumui_id.currency_id")
    price_subtotal = fields.Monetary(string="공급가액", compute="_compute_price", store=True)
    price_tax = fields.Monetary(string="세액", compute="_compute_price", store=True)
    price_total = fields.Monetary(string="합계", compute="_compute_price", store=True)
    invoice_line_id = fields.Many2one("account.move.line", string="연결 청구 라인",
                                      readonly=True, copy=False)
    invoiced = fields.Boolean(string="청구됨", compute="_compute_invoiced", store=True)

    @api.model_create_multi
    def create(self, vals_list):
        with self.env.cr.savepoint():
            parent_ids = {vals.get("pumui_id", self.env.context.get("default_pumui_id"))
                          for vals in vals_list}
            parents = self.env["pumui.request"].browse(sorted(i for i in parent_ids if i))
            if parents._has_posted_invoice():
                raise UserError(_(self.env["pumui.request"]._POSTED_EVIDENCE_MESSAGE))
            # An empty command list changes no rows but invokes the existing
            # parent approval reset/new-revision path.
            if parents:
                parents.write({"line_ids": []})
            return super().create(vals_list)

    def write(self, vals):
        evidence_fields = {"pumui_id", "product_id", "name", "payment_stage",
                           "quantity", "price_unit", "tax_ids", "sequence",
                           # 저장 계산 필드는 UI 에서만 읽기전용이다. RPC 로 직접 쓰면 예산 상한이 부풀므로 근거 변경으로 취급(D-1).
                           "price_subtotal", "price_tax", "price_total"}
        if "invoice_line_id" in vals and self.env.context.get("pumui_invoice_link") is not _INVOICE_LINK_TOKEN:
            # 청구서 생성 경로(action_create_invoice)만 내부 객체 토큰으로 통과한다. RPC 가 넣는 True/문자열은 토큰이 아니므로
            # 외부 해제/재연결은 재청구 후보를 만드는 근거 변경으로 취급한다(D-1, 총괄 040-1).
            evidence_fields = evidence_fields | {"invoice_line_id"}
        if not evidence_fields.intersection(vals):
            # Invoice linking from the invoice action and other bookkeeping are not
            # changes to the approved quantity/price/items.
            return super().write(vals)
        with self.env.cr.savepoint():
            Request = self.env["pumui.request"]
            parents = self.mapped("pumui_id")
            if vals.get("pumui_id"):
                parents |= Request.browse(vals["pumui_id"])
            locked = parents._has_posted_invoice()
            if locked and (vals.get("pumui_id") or any(line.invoice_line_id for line in self)
                           or self.mapped("pumui_id") & locked._settlement_shared()):
                # 전기 근거 있는 품의로/에서 항목 이동, 이미 청구된 항목 값 변경, 정산 공유 품의(라인 전체가 소비 근거) → 차단.
                raise UserError(_(Request._POSTED_EVIDENCE_MESSAGE))
            parents.sorted("id").write({"line_ids": []})
            return super().write(vals)

    def unlink(self):
        with self.env.cr.savepoint():
            if any(line.invoice_line_id for line in self) or self.mapped("pumui_id")._has_posted_invoice():
                raise UserError(_(self.env["pumui.request"]._POSTED_EVIDENCE_MESSAGE))
            self.mapped("pumui_id").sorted("id").write({"line_ids": []})
            return super().unlink()

    @api.depends("quantity", "price_unit", "tax_ids")
    def _compute_price(self):
        for l in self:
            base = (l.quantity or 0.0) * (l.price_unit or 0.0)
            taxes = l.tax_ids.compute_all(
                l.price_unit or 0.0, currency=l.currency_id, quantity=l.quantity or 0.0,
                product=l.product_id, partner=l.pumui_id.partner_id,
            ) if l.tax_ids else {"total_excluded": base, "total_included": base}
            l.price_subtotal = taxes["total_excluded"]
            l.price_tax = taxes["total_included"] - taxes["total_excluded"]
            l.price_total = taxes["total_included"]

    @api.depends("invoice_line_id", "invoice_line_id.move_id.state")
    def _compute_invoiced(self):
        for l in self:
            ml = l.invoice_line_id
            l.invoiced = bool(ml) and ml.move_id.state != "cancel"

    @api.onchange("product_id")
    def _onchange_product(self):
        for l in self:
            if l.product_id:
                l.name = l.product_id.display_name
                is_purchase = l.pumui_id.pumui_type == "purchase"
                l.price_unit = l.product_id.standard_price if is_purchase else l.product_id.lst_price
                l.tax_ids = (l.product_id.supplier_taxes_id if is_purchase
                             else l.product_id.taxes_id)
