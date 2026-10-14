"""부품 이종검사 — 판정과 **실제 차단**.

기존 `mrp_bom_scan_guard` 는 스캔 결과를 화면에 적어 주기만 했다. 틀린 부품을 스캔해도
작업을 막지 않았고, LOT 을 전혀 보지 않아 「알 수 없는 LOT」·「품질보류 LOT」은 판정
대상조차 아니었다. 중복 스캔 방지도 2초 debounce 라 3초 뒤 같은 부품을 또 스캔하면
통과했다(사람 손가락이 아니라 **실물 중복 투입**을 막아야 한다).

여기서 세 가지를 더한다.
  1. `_scan_verdict` — 부작용 없는 판정. 화면·시험·게이트가 같은 판정을 쓴다.
  2. `action_confirm_scan` — 판정이 통과일 때만 증빙을 남기고, 막히면 그 자리에서 멈춘다.
  3. 작업 완료 게이트 — 필요한 부품의 통과 증빙이 없거나 미해소 차단이 남아 있으면
     작업지시/제조오더를 완료하지 못한다.

**여기서 정하지 않는 것**: 품질 합격 기준값. CP/PFMEA 선행과 초·중·종 검사 차단은
`iatf_quality_precedence` 가 이미 소유하므로 중복 구현하지 않는다. 이 파일은 **투입 부품이
그 BOM·개정·차종에 맞는 물건인가**만 본다.
"""
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import UserError


BLOCKING_STATES = (
    "wrong_operation", "not_in_bom", "not_found", "over_consumed",
    "unknown_lot", "quality_hold", "quality_evidence", "duplicate_scan",
    "wrong_bom_revision", "wrong_vehicle",
)


class MrpBomScanGuardLog(models.Model):
    _inherit = "mrp.bom.scan.guard.log"

    _NEW_STATES = [
        ("unknown_lot", "알 수 없는 LOT"),
        ("quality_hold", "품질 보류 LOT"),
        ("quality_evidence", "품질 근거 재검토"),
        ("duplicate_scan", "중복 투입"),
        ("wrong_bom_revision", "다른 BOM/개정"),
        ("wrong_vehicle", "다른 차종"),
    ]

    result_state = fields.Selection(selection_add=_NEW_STATES,
                                    ondelete={k: "cascade" for k, _n in _NEW_STATES})

    # 증빙 — 배정 4항: 작업자·공정·시간·스캔값·LOT·사유·BR/MO/BOM 개정
    lot_id = fields.Many2one("stock.lot", string="LOT", index=True)
    bom_id = fields.Many2one("mrp.bom", string="적용 BOM")
    bom_revision = fields.Char(string="BOM 개정", help="적용 BOM 의 개정/배치 이름.")
    vehicle_code = fields.Char(string="차종/ALC")
    br_reference = fields.Char(string="BR 근거", help="이 제조오더가 따라온 원청 BR 식별자.")
    blocking = fields.Boolean(string="차단됨", compute="_compute_blocking", store=True)
    resolved = fields.Boolean(string="해소됨", readonly=True, copy=False)
    resolved_reason = fields.Char(string="해소 사유", readonly=True, copy=False)
    resolved_by = fields.Many2one("res.users", string="해소자", readonly=True, copy=False)
    resolved_at = fields.Datetime(string="해소 시각", readonly=True, copy=False)

    @api.depends("result_state")
    def _compute_blocking(self):
        for rec in self:
            rec.blocking = rec.result_state in BLOCKING_STATES

    blocked_minutes = fields.Float(
        string="차단 경과 (분)", compute="_compute_blocked_minutes",
        help="차단이 생긴 뒤 해소까지 걸린 시간. 아직 안 풀렸으면 지금까지의 경과.")
    overdue = fields.Boolean(
        string="경보 한도 초과", compute="_compute_blocked_minutes",
        help="이 차단이 경보 한도를 넘겨 서 있는지. BR 납기와는 다른 값이다.")

    @api.depends("create_date", "resolved", "resolved_at")
    def _compute_blocked_minutes(self):
        """차단이 얼마나 오래 서 있었는지.

        [운영기준 20260911-06 5항] 조립은 BR 수신 후 **2시간 안에 고객 도착**이어야
        한다. 차단 자체는 옳지만, 그 차단이 얼마나 서 있었는지 모르면 2시간을 지킬 수
        없다. 그래서 경과를 재고 한도를 넘겼는지 표시한다.
        """
        now = fields.Datetime.now()
        for rec in self:
            if not rec.blocking or not rec.create_date:
                rec.blocked_minutes = 0.0
                rec.overdue = False
                continue
            end = rec.resolved_at if (rec.resolved and rec.resolved_at) else now
            # DB 시각(create_date)과 파이썬 시각이 몇십 ms 어긋날 수 있다(컨테이너
            # 분리). 경과시간이 음수가 되는 일은 없어야 하므로 0 에서 자른다.
            elapsed = (end - rec.create_date).total_seconds() / 60.0
            rec.blocked_minutes = max(elapsed, 0.0)
            limit = rec.company_id.scan_block_alert_minutes
            rec.overdue = bool(limit) and rec.blocked_minutes > limit

    alerted = fields.Boolean(
        string="납기초과 경보함", readonly=True, copy=False,
        help="같은 차단으로 되풀이 경보하지 않기 위한 표시.")

    @api.model
    def _cron_alert_overdue_scan_blocks(self, limit=200):
        """납기를 넘겨 서 있는 차단을 제조오더에 경보로 남긴다.

        **게이트에서 경보하지 않는 이유** — 게이트는 `UserError` 를 올리는 자리이고,
        예외가 나가면 그 트랜잭션이 롤백되므로 거기서 남긴 경보는 사라진다.
        `action_confirm_scan` 에서 겪은 것과 같은 함정이다(시험이 두 번 다 잡았다).
        그리고 납기 초과는 **누가 완료 버튼을 누를 때**가 아니라 **시간이 지나면**
        알려야 하는 사실이다. 그래서 별도 주기 작업으로 뺀다.
        """
        pending = self.search([
            ("blocking", "=", True), ("resolved", "=", False), ("alerted", "=", False),
        ], limit=limit)
        alerted = self.browse()
        for log in pending:
            if not log.overdue or not log.production_id:
                continue
            log.production_id.message_post(body=_(
                "⚠ 이종검사 차단이 경보 한도(%(limit).0f분)를 넘겨 서 있습니다 — "
                "%(scan)s / %(state)s (%(mins).0f분 경과). 정상 재스캔 또는 승인된 "
                "처분이 필요합니다.",
                limit=log.company_id.scan_block_alert_minutes,
                scan=log.scan_value, state=log.result_state,
                mins=log.blocked_minutes))
            alerted |= log
        if alerted:
            alerted.sudo().write({"alerted": True})
        return len(alerted)

    _RESOLVER_GROUPS = (
        "mrp.group_mrp_manager",
        "quality.group_quality_manager",
    )

    def action_resolve(self, reason=False):
        """정상 재스캔·승인된 처분 뒤에만 차단을 푼다. 사유 없이는 풀지 않는다.

        [아스트라 20260912 04:45] 「추가 정적 우려도 기존 개발 소유 `scan_gate.py`
        `action_resolve` 에서 **역할 검사 없이 sudo 쓰기**하는지 검토 요청합니다.
        root 하네스는 지정 생산관리자만 정상 해제하지만 **그것이 일반 사용자 우회
        차단 증거는 아닙니다.** 일반작업자 경보해제 시도/타회사 로그 접근 거부를
        재현하고 관리자 정정 사유·재스캔 정상 절차 유지하십시오. **무조건 최고권한
        부여는 해결이 아닙니다.**」

        맞습니다. 원장 ACL 은 `base.group_user` 에게 **읽기만** 줬는데
        (`ir.model.access.csv`), 이 메서드가 `sudo()` 로 그것을 그냥 넘었습니다.
        **사유만 적으면 아무나 차단을 풀 수 있었습니다.**

        이제 세 가지를 본다 — 그 다음에만 서버 권한으로 쓴다:
          1. **역할**: 생산관리자 또는 품질관리자.
          2. **회사**: 내가 접근할 수 있는 회사의 로그만.
          3. **사유**: 종전대로 비워 둘 수 없다.
        """
        reason = reason or self.env.context.get("scan_guard_resolution")
        if not reason:
            raise UserError(_("차단을 해소하려면 사유를 남겨야 합니다."))
        if not self.env.su and not any(
                self.env.user.has_group(group) for group in self._RESOLVER_GROUPS):
            raise UserError(_(
                "이종검사 차단 해소는 생산관리자 또는 품질관리자가 합니다. "
                "정상 재스캔으로 증빙을 남기거나 담당자에게 요청하십시오."))
        self.check_access("read")
        for log in self:
            if log.company_id and log.company_id not in self.env.companies:
                raise UserError(_(
                    "허용된 회사의 이종검사 기록만 해소할 수 있습니다."))
        return self.sudo().write({
            "resolved": True, "resolved_reason": reason,
            "resolved_by": self.env.user.id,
            "resolved_at": fields.Datetime.now(),
        })


class MrpBomScanGuardWizard(models.TransientModel):
    _inherit = "mrp.bom.scan.guard.wizard"

    lot_id = fields.Many2one("stock.lot", string="LOT", readonly=True)
    result_state = fields.Selection(
        selection_add=MrpBomScanGuardLog._NEW_STATES,
        ondelete={k: "cascade" for k, _n in MrpBomScanGuardLog._NEW_STATES})

    # ────────────────────────────────────────────────────────────
    # 판정 — 부작용 없음
    # ────────────────────────────────────────────────────────────
    @api.model
    def _scan_resolve_lot(self, value, product=None):
        """스캔값이 가리키는 LOT. 품목을 알면 그 품목으로 좁힌다."""
        self.ensure_one()
        domain = [("name", "=", value), ("company_id", "=", self.production_id.company_id.id)]
        if product:
            domain.append(("product_id", "=", product.id))
        lots = self.env["stock.lot"].search(domain, limit=2)
        return lots if len(lots) == 1 else lots.browse()

    @api.model
    def _scan_bom_context(self, production):
        """이 제조오더에 실제로 적용된 BOM 의 개정·차종. 없으면 빈 값."""
        bom = production.bom_id
        revision = vehicle = False
        if bom:
            if "bom_version_id" in bom._fields and bom.bom_version_id:
                version = bom.bom_version_id
                revision = version.display_name
                if "csrt_id" in version._fields and version.csrt_id:
                    vehicle = version.csrt_id.display_name
            if not vehicle and "alc" in bom._fields:
                vehicle = bom.alc or False
        return bom, revision, vehicle

    def _scan_verdict(self, value):
        """스캔값 하나에 대한 판정. **아무것도 바꾸지 않는다.**

        돌려주는 것: ``{state, product, lot, reason}``.
        `state` 가 `ok` 가 아니면 전부 차단 사유다.
        """
        self.ensure_one()
        self.workorder_id.check_access('read')
        if self.production_id.company_id not in self.env.companies:
            raise UserError(_('허용된 회사의 작업지시만 스캔할 수 있습니다.'))
        code = (value or "").strip()
        production = self.production_id
        empty = self.env["product.product"]
        if not code:
            return {"state": "not_found", "product": empty, "lot": False,
                    "reason": _("스캔값이 비어 있습니다.")}

        product = self._find_product_by_scan_value(code)
        lot = self._scan_resolve_lot(code, product or None)
        if lot and not product:
            product = lot.product_id

        if not product:
            # 품목도 LOT 도 아니면 **모르는 물건**이다. 통과시키지 않는다.
            return {"state": "unknown_lot", "product": empty, "lot": False,
                    "reason": _("등록되지 않은 스캔값입니다: %s", code)}

        # ── 품질 보류 LOT 은 투입 금지 ──
        if lot and "quality_hold" in lot._fields and lot.quality_hold:
            return {"state": "quality_hold", "product": product, "lot": lot,
                    "reason": _("LOT %(lot)s 은 품질 보류 상태입니다(%(why)s).",
                                lot=lot.name, why=lot.hold_reason or _("사유 미기재"))}

        # ── 같은 LOT 을 이 작업지시에 두 번 투입하지 않는다 ──
        if lot:
            already = self.env["mrp.bom.scan.guard.log"].sudo().search_count([
                ("workorder_id", "=", self.workorder_id.id),
                ("lot_id", "=", lot.id),
                ("result_state", "=", "ok"),
            ])
            if already:
                return {"state": "duplicate_scan", "product": product, "lot": lot,
                        "reason": _("LOT %s 은 이 작업지시에 이미 투입되었습니다.", lot.name)}

        # ── BOM 에 있는 부품인가 / 이 공정인가 ──
        expected = self._expected_moves_for_operation()
        move = expected.filtered(lambda m: m.product_id == product)[:1]
        if not move:
            in_mo = production.move_raw_ids.filtered(lambda m: m.product_id == product)
            if in_mo:
                return {"state": "wrong_operation", "product": product, "lot": lot,
                        "reason": _("%s 는 이 제조오더의 자재지만 이 공정 투입분이 아닙니다.",
                                    product.display_name)}
            # 다른 BOM/차종의 부품인지 구분해서 알려 준다.
            bom, revision, vehicle = self._scan_bom_context(production)
            other = self.env["mrp.bom.line"].sudo().search(
                [("product_id", "=", product.id)], limit=1).bom_id
            if other and bom and other != bom:
                other_vehicle = other.alc if "alc" in other._fields else False
                if other_vehicle and vehicle and other_vehicle != vehicle:
                    return {"state": "wrong_vehicle", "product": product, "lot": lot,
                            "reason": _("%(prod)s 는 차종 %(other)s 용입니다. 이 오더는 "
                                        "%(mine)s 입니다.", prod=product.display_name,
                                        other=other_vehicle, mine=vehicle)}
                return {"state": "wrong_bom_revision", "product": product, "lot": lot,
                        "reason": _("%(prod)s 는 다른 BOM(%(other)s)의 부품입니다. 이 오더의 "
                                    "적용 BOM 은 %(mine)s(%(rev)s)입니다.",
                                    prod=product.display_name, other=other.display_name,
                                    mine=bom.display_name, rev=revision or _("개정 미지정"))}
            return {"state": "not_in_bom", "product": product, "lot": lot,
                    "reason": _("%s 는 이 제조오더에 들어가지 않는 품목입니다.",
                                product.display_name)}

        # ── 계획 수량을 넘겨 투입하지 않는다 ──
        planned = move.product_uom_qty
        done = self._qty_done_of_move(move)
        if planned and done >= planned:
            return {"state": "over_consumed", "product": product, "lot": lot,
                    "reason": _("%(prod)s 는 계획 수량에 도달했습니다(%(done).2f/%(plan).2f).",
                                prod=product.display_name, done=done, plan=planned)}

        # ── LOT 추적 품목인데 LOT 을 못 읽었으면 통과시키지 않는다 ──
        if product.tracking != "none" and not lot:
            return {"state": "unknown_lot", "product": product, "lot": False,
                    "reason": _("%s 는 LOT 관리 품목인데 스캔값에서 LOT 을 찾지 못했습니다.",
                                product.display_name)}

        if hasattr(move, '_assert_iqc_measurement_at_scan'):
            try:
                move._assert_iqc_measurement_at_scan(lot)
            except UserError as exc:
                return {"state": "quality_evidence", "product": product, "lot": lot,
                        "reason": str(exc)}
        return {"state": "ok", "product": product, "lot": lot, "reason": False}

    @api.onchange('scan_value')
    def _onchange_scan_value(self):
        """Preview the same decision; only explicit confirmation writes a log."""
        for wizard in self:
            if not wizard.scan_value or not wizard.workorder_id:
                wizard.matched_product_id = False
                wizard.lot_id = False
                wizard.result_state = False
                wizard.message = False
                continue
            verdict = wizard._scan_verdict(wizard.scan_value)
            wizard.matched_product_id = verdict['product']
            wizard.lot_id = verdict['lot'] or False
            wizard.result_state = verdict['state']
            wizard.message = Markup('<p>%s</p><p>%s</p>') % (
                verdict['reason'] or _('정상'), _('미리보기입니다. 확정 버튼을 누르면 스캔 이력이 기록됩니다.'))

    # ────────────────────────────────────────────────────────────
    # 증빙 기록 + 차단
    # ────────────────────────────────────────────────────────────
    def _scan_evidence_values(self, verdict, code):
        self.ensure_one()
        production = self.production_id
        bom, revision, vehicle = self._scan_bom_context(production)
        br_reference = False
        for name in ("bodyfull", "inj_bodyfull"):
            if name in production._fields and production[name]:
                br_reference = production[name]
                break
        return {
            "workorder_id": self.workorder_id.id,
            "scan_value": code,
            "matched_product_id": verdict["product"].id or False,
            "lot_id": verdict["lot"].id if verdict["lot"] else False,
            "bom_id": bom.id if bom else False,
            "bom_revision": revision or False,
            "vehicle_code": vehicle or False,
            "br_reference": br_reference,
            "result_state": verdict["state"],
            "message": Markup("<p>%s</p>") % (verdict["reason"] or _("정상")),
        }

    def action_confirm_scan(self):
        """스캔을 확정한다. 판정은 통과든 차단이든 **언제나** 증빙으로 남는다.

        **여기서 `UserError` 를 올리지 않는 이유** — 처음에는 차단 시 예외를 올렸다.
        그런데 Odoo 에서 예외가 서버 메서드 밖으로 나가면 **그 트랜잭션이 통째로
        롤백된다.** 즉 방금 남긴 차단 증빙까지 같이 사라진다. 「차단했다」는 사실이
        남지 않으면 배정 4항(작업자·공정·시간·스캔값·LOT·사유 증빙)이 성립하지 않는다.
        시험이 이것을 잡았다.

        그래서 역할을 나눈다.
          - 이 메서드: 사실을 **기록**하고 화면에 거부를 알린다. 통과가 아니면 투입
            증빙(`ok`)을 만들지 않으므로 그 부품은 투입된 것으로 취급되지 않는다.
          - `button_finish` / `button_mark_done`: 미해소 차단이 있으면 **실제로 막는다.**
            거기서는 막는 것이 목적이고 남길 것이 없으므로 예외가 맞다.
        """
        self.ensure_one()
        code = (self.scan_value or "").strip()
        verdict = self._scan_verdict(code)
        log = self.env["mrp.bom.scan.guard.log"].sudo().create(
            self._scan_evidence_values(verdict, code))
        self.matched_product_id = verdict["product"].id or False
        self.lot_id = verdict["lot"].id if verdict["lot"] else False
        self.result_state = verdict["state"]
        self.message = log.message
        if verdict["state"] == "ok":
            return True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("투입할 수 없습니다"),
                "message": _("%(why)s\n정상 부품을 다시 스캔하거나, 승인된 처분 뒤에 "
                             "진행하십시오.", why=verdict["reason"]),
                "type": "danger",
                "sticky": True,
            },
        }


class MrpWorkorder(models.Model):
    _inherit = "mrp.workorder"

    def _scan_guard_required_products(self):
        """이 작업지시에서 **스캔 증빙을 요구하는** 부품."""
        self.ensure_one()
        moves = self.production_id.move_raw_ids.filtered(
            lambda m: m.state not in ("done", "cancel"))
        if self.operation_id:
            moves = moves.filtered(
                lambda m: not m.bom_line_id or not m.bom_line_id.operation_id
                or m.bom_line_id.operation_id == self.operation_id)
        return moves.mapped("product_id")

    def _assert_scan_guard_clear(self):
        """미해소 차단이 남아 있으면 진행하지 않는다."""
        Log = self.env["mrp.bom.scan.guard.log"].sudo()
        for workorder in self:
            blocked = Log.search([
                ("workorder_id", "=", workorder.id),
                ("blocking", "=", True),
                ("resolved", "=", False),
            ])
            if blocked:
                raise UserError(_(
                    "%(wo)s 에 해소되지 않은 이종검사 차단이 %(n)d 건 있습니다.\n%(list)s\n"
                    "정상 재스캔 또는 승인된 처분으로 해소한 뒤 진행하십시오.",
                    wo=workorder.display_name, n=len(blocked),
                    list="\n".join(
                        " · %s: %s (%.0f분 경과%s)" % (
                            log.scan_value, log.result_state, log.blocked_minutes,
                            _(", 경보 한도 초과") if log.overdue else "")
                        for log in blocked[:5])))
        return True



    def button_finish(self):
        # 배정 3·4항: 정상 부품만 투입하고, 차단은 증빙과 처분을 거친 뒤에만 통과한다.
        self._assert_scan_guard_clear()
        return super().button_finish()


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    def button_mark_done(self):
        for production in self:
            production.workorder_ids._assert_scan_guard_clear()
        return super().button_mark_done()


class ResCompany(models.Model):
    _inherit = "res.company"

    # [아스트라 20260911-07] 「사용자 지정 2시간은 **BR 수신부터 고객 도착**이다.
    # 차단 지속시간 120분과 혼동하지 않는다.」 — 맞는 지적이라 이름을 고쳤다.
    # 이 값은 **이종검사 차단이 얼마나 오래 서 있으면 경보할지**이지 납기가 아니다.
    # 기본값은 2시간 납기 안에서 처리돼야 하므로 그보다 짧게 잡는 것이 맞고,
    # 실제 값은 현장 운영 기준이라 발명하지 않는다 — 우선 30분으로 두고 설정으로 연다.
    # 0 은 '미설정' 이 아니라 **끄기**이며 기본값으로 되살리지 않는다.
    scan_block_alert_minutes = fields.Float(
        string="이종검사 차단 경보 한도 (분) [잠정]", default=30.0,
        help="이종검사 차단이 이 시간을 넘겨 서 있으면 제조오더에 경보를 남긴다.\n\n"
             "⚠ 기본값 30분은 **개발이 제시한 잠정 기본안**이며 회사 확정 정책이 "
             "아니다. 품질·생산 담당이 현장 기준으로 확정해야 한다.\n"
             "⚠ 사용자 확정값인 BR 납기 120분(수신→고객 도착)과는 **다른 값**이다. "
             "그쪽은 br.intake 의 br_delivery_deadline_minutes 다.\n"
             "0 이면 경보하지 않는다.")
