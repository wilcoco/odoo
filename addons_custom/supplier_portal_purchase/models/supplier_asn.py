import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero
from .scm_utils import check_actor, check_quantity

_ASN_WRITE = object()


class SupplierAsn(models.Model):
    """납품 예정 통보(ASN) — 협력사가 포털에서 사전 등록하는 무지(無紙) 납품 명세.

    종이 거래명세서 대체: 협력사 등록 → 도착 시 사내에서 [입고전표 생성] 원클릭 →
    담당자는 실물 수량 대조·확정만. 확정되면 기존 사슬(IQC 자동·인수확인서 포털 게시)로 연결.
    """
    _name = "supplier.asn"
    _description = "납품 예정(ASN)"
    _order = "expected_date desc, id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(default="신규", readonly=True, copy=False)
    partner_id = fields.Many2one("res.partner", string="협력사", required=True, index=True)
    expected_date = fields.Date(string="도착 예정일", required=True,
                                default=fields.Date.context_today)
    note = fields.Char(string="비고(차량/기사 등)")
    state = fields.Selection([
        ("announced", "납품 예정"),
        ("received", "입고 완료"),
        ("cancelled", "취소"),
    ], default="announced", tracking=True, index=True)
    line_ids = fields.One2many("supplier.asn.line", "asn_id", string="납품 품목")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, index=True)
    allocation_revision = fields.Integer(default=0, readonly=True, copy=False)
    picking_ids = fields.Many2many("stock.picking", compute="_compute_pickings", string="입고 및 백오더")

    def _compute_pickings(self):
        for asn in self:
            asn.picking_ids = asn.line_ids.move_ids.picking_id | asn.picking_id

    picking_id = fields.Many2one("stock.picking", string="입고 전표", readonly=True, copy=False)
    qr_token = fields.Char(string="납품패스 토큰", readonly=True, copy=False,
                           default=lambda self: secrets.token_urlsafe(16),
                           help="기사 제시용 QR 의 건별 토큰 — 포털 토큰과 분리(화면 노출 안전)")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("picking_id") or vals.get("state", "announced") != "announced":
                raise UserError(_("납품 예정 생성 시 완료 상태나 입고 근거를 지정할 수 없습니다."))
            vals.update(state="announced", picking_id=False, allocation_revision=0)
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "신규") == "신규":
                name = seq.next_by_code("supplier.asn")
                if not name:
                    # 안전망: 시퀀스 data(data/sequence.xml)가 없는 예외 상황.
                    # 동시 생성 레이스로 같은 code 시퀀스가 2개 생기지 않게 조회 후 생성.
                    if not seq.sudo().search(
                            [("code", "=", "supplier.asn")], limit=1):
                        seq.sudo().create({
                            "name": "납품 예정(ASN)", "code": "supplier.asn",
                            "prefix": "ASN-%(y)s-", "padding": 4,
                        })
                    name = seq.next_by_code("supplier.asn")
                vals["name"] = name
        return super().create(vals_list)

    @api.constrains("company_id", "partner_id", "line_ids")
    def _check_scm_scope(self):
        for asn in self:
            check_actor(asn, asn.partner_id)
            asn.line_ids._check_scm_scope()

    def write(self, vals):
        for asn in self:
            if not (not asn.company_id and vals.get("company_id") and self.env.user.has_group("base.group_system")):
                check_actor(asn, asn.partner_id)
            if (set(vals) & {"picking_id", "allocation_revision", "state"}
                    and self.env.context.get("_asn_write") is not _ASN_WRITE):
                raise UserError(_("입고 연결과 상태는 ASN 처리 동작으로만 변경할 수 있습니다."))
            if set(vals) & {"company_id", "partner_id", "line_ids"} and asn.line_ids.move_ids:
                raise UserError(_("입고에 배정된 ASN의 회사·업체·품목은 바꿀 수 없습니다."))
        return super().write(vals)

    def _lock_allocation(self):
        self.ensure_one()
        check_actor(self, self.partner_id)
        self.env.cr.execute("SELECT id FROM supplier_asn WHERE id=%s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        self.with_context(_asn_write=_ASN_WRITE).write({"allocation_revision": self.allocation_revision + 1})

    def action_create_picking(self):
        """Idempotently allocate an existing PO receipt; never duplicate its demand."""
        self.ensure_one()
        self._lock_allocation()
        if self.state == "cancelled":
            raise UserError(_("취소된 ASN은 입고할 수 없습니다. 새 납품 예정을 등록하세요."))
        active = self.line_ids.move_ids.picking_id.filtered(lambda p: p.state not in ("done", "cancel"))
        if len(active) > 1:
            raise UserError(_("ASN에 여러 활성 입고가 있습니다. 기존 배정 확인이 필요합니다."))
        if active:
            return self._picking_action(active)
        if self.state == "received":
            return self._picking_action(self.picking_id)
        if self.picking_id and not self.line_ids.move_ids:
            raise UserError(_("기존 ASN 입고의 원 구매 배정 근거가 없습니다. 기존 전표를 대사한 뒤 이관하세요."))
        if not self.line_ids or any(not line.purchase_line_id for line in self.line_ids):
            raise UserError(_("ASN 품목마다 원 구매/수량 요구 행을 지정하세요. 무연결 입고는 생성하지 않습니다."))
        self.line_ids._check_scm_scope()
        po_lines = self.line_ids.purchase_line_id.sorted("id")
        # UPDATE is a transaction serialization barrier, including two different
        # ASNs competing for the same PO remainder under PostgreSQL repeatable read.
        self.env.cr.execute("UPDATE purchase_order_line SET scm_allocation_revision=COALESCE(scm_allocation_revision,0)+1 WHERE id IN %s", (tuple(po_lines.ids),))
        po_lines.invalidate_recordset()
        picked = self.env["stock.picking"]
        for line in self.line_ids:
            completed = sum(m.product_uom._compute_quantity(m.quantity, line.product_id.uom_id)
                for m in line.move_ids if m.state == "done" and m.location_dest_id.usage == "internal"
                and m.location_id.usage == "supplier")
            remaining = line.qty - completed
            if float_compare(remaining, 0, precision_rounding=line.product_id.uom_id.rounding) <= 0:
                continue
            candidates = self.env["stock.move"].search([
                ("purchase_line_id", "=", line.purchase_line_id.id),
                ("company_id", "=", self.company_id.id),
                ("supplier_asn_line_id", "=", False),
                ("state", "in", ("confirmed", "waiting", "assigned", "partially_available")),
                ("location_id.usage", "=", "supplier"), ("location_dest_id.usage", "=", "internal"),
            ], order="date, id")
            available = sum(candidates.mapped("product_qty"))
            if float_compare(available, remaining, precision_rounding=line.product_id.uom_id.rounding) < 0:
                raise UserError(_("원 구매 행의 미배정 입고 잔량이 부족합니다: %s") % line.product_id.display_name)
            for move in candidates:
                if float_is_zero(remaining, precision_rounding=line.product_id.uom_id.rounding):
                    break
                if move.picked or move.move_line_ids.filtered(lambda ml: ml.lot_id or ml.lot_name):
                    raise UserError(_("이미 실물 수량/LOT가 처리된 입고는 ASN으로 재배정할 수 없습니다."))
                qty = min(remaining, move.product_qty)
                move._do_unreserve()
                if float_compare(qty, move.product_qty, precision_rounding=line.product_id.uom_id.rounding) < 0:
                    assigned = self.env["stock.move"].create(move._split(qty))
                else:
                    assigned = move
                if not picked:
                    picked = self.env["stock.picking"].create({
                        "picking_type_id": move.picking_type_id.id,
                        "partner_id": self.partner_id.id, "company_id": self.company_id.id,
                        "origin": line.purchase_line_id.order_id.name,
                        "location_id": move.location_id.id, "location_dest_id": move.location_dest_id.id,
                    })
                if (move.picking_type_id != picked.picking_type_id or move.location_id != picked.location_id
                        or move.location_dest_id != picked.location_dest_id):
                    raise UserError(_("입고 경로가 다른 구매 행은 ASN을 분리해 주세요."))
                assigned.with_context(_asn_write=_ASN_WRITE).write({"picking_id": picked.id, "supplier_asn_line_id": line.id})
                assigned._action_confirm(merge=False)
                values = {"product_id": line.product_id.id, "quantity": qty,
                    "product_uom_id": line.product_id.uom_id.id,
                    "location_id": picked.location_id.id, "location_dest_id": picked.location_dest_id.id}
                if line.lot_name:
                    lot = self.env["stock.lot"].search([("name", "=", line.lot_name),
                        ("product_id", "=", line.product_id.id), ("company_id", "=", self.company_id.id)], limit=1)
                    if not lot:
                        lot = self.env["stock.lot"].create({"name": line.lot_name,
                            "product_id": line.product_id.id, "company_id": self.company_id.id})
                    values["lot_id"] = lot.id
                assigned.move_line_ids.unlink()
                assigned.write({"move_line_ids": [(0, 0, values)]})
                remaining -= qty
        if not picked:
            raise UserError(_("새로 입고할 ASN 잔량이 없습니다. 기존 입고 및 취소 근거를 확인하세요."))
        self.with_context(_asn_write=_ASN_WRITE).write({"picking_id": picked.id})
        return self._picking_action(picked)

    def _picking_action(self, picking):
        return {"type": "ir.actions.act_window", "res_model": "stock.picking",
                "res_id": picking.id, "view_mode": "form"}

    def action_cancel(self):
        for asn in self:
            asn._lock_allocation()
            if asn.picking_id and not asn.line_ids.move_ids:
                raise UserError(_("기존 ASN 입고의 원 구매 배정 근거를 먼저 대사해야 합니다."))
            if asn.state == "received" or asn.line_ids.move_ids.filtered(lambda m: m.state == "done"):
                raise UserError(_("실입고가 있는 ASN은 취소할 수 없습니다. 별도 반품/정정 절차를 사용하세요."))
            # Release the allocation back to ordinary PO receiving, retaining the
            # PO obligation. Cancelling the ASN is not cancellation of the order.
            allocated = asn.line_ids.move_ids.filtered(lambda m: m.state != "cancel")
            allocated._do_unreserve()
            allocated.with_context(_asn_write=_ASN_WRITE).write({"supplier_asn_line_id": False})
            asn.with_context(_asn_write=_ASN_WRITE).write({"state": "cancelled"})
        return True

    def unlink(self):
        if self.picking_id or self.line_ids.move_ids:
            raise UserError(_("입고 전표 근거가 있는 ASN은 삭제할 수 없습니다."))
        return super().unlink()

    def _mark_received_from_picking(self, picking):
        for asn in self:
            complete = all(float_compare(
                sum(m.product_uom._compute_quantity(m.quantity, line.product_id.uom_id)
                    for m in line.move_ids if m.state == "done" and m.location_id.usage == "supplier"
                    and m.location_dest_id.usage == "internal"), line.qty,
                precision_rounding=line.product_id.uom_id.rounding) >= 0 for line in asn.line_ids)
            if asn.line_ids and complete and asn.state != "cancelled":
                asn.with_context(_asn_write=_ASN_WRITE).write({"state": "received"})


class SupplierAsnLine(models.Model):
    _name = "supplier.asn.line"
    _description = "납품 예정 라인"

    asn_id = fields.Many2one("supplier.asn", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", string="품목", required=True)
    qty = fields.Float(string="납품 수량 (제품 기본 단위)", required=True)
    company_id = fields.Many2one(related="asn_id.company_id", store=True, index=True)
    purchase_line_id = fields.Many2one("purchase.order.line", string="원 구매/수량 요구 행",
        ondelete="restrict", domain="[('company_id', '=', company_id)]")
    move_ids = fields.One2many("stock.move", "supplier_asn_line_id", string="배정 재고 이동", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            parent = self.env["supplier.asn"].browse(vals.get("asn_id", self.env.context.get("default_asn_id")))
            if parent.picking_id or parent.state not in (False, "announced"):
                raise UserError(_("이미 처리된 ASN에 새 품목을 추가할 수 없습니다."))
        return super().create(vals_list)

    @api.constrains("asn_id", "company_id", "product_id", "qty", "purchase_line_id")
    def _check_scm_scope(self):
        for line in self:
            check_actor(line, line.asn_id.partner_id)
            check_quantity(line.qty, positive=True)
            line.asn_id.partner_id._scm_check_supply_product(line.product_id, line.company_id)
            po_line = line.purchase_line_id
            if po_line and (po_line.company_id != line.company_id or po_line.product_id != line.product_id
                    or po_line.order_id.partner_id.commercial_partner_id != line.asn_id.partner_id.commercial_partner_id):
                raise ValidationError(_("ASN의 회사·업체·품목과 원 구매 행이 일치해야 합니다."))

    def write(self, vals):
        destination = self.env["supplier.asn"].browse(vals.get("asn_id"))
        if destination and (destination.picking_id or destination.state != "announced"):
            raise UserError(_("처리된 ASN으로 품목을 옮길 수 없습니다."))
        for line in self:
            check_actor(line, line.asn_id.partner_id)
            if (line.move_ids or line.asn_id.picking_id) and set(vals) & {"asn_id", "product_id", "qty", "purchase_line_id", "lot_name"}:
                raise UserError(_("이미 입고에 배정된 ASN 행은 변경할 수 없습니다."))
        return super().write(vals)

    def unlink(self):
        if self.move_ids or self.asn_id.picking_id:
            raise UserError(_("입고 근거가 있는 ASN 행은 삭제할 수 없습니다."))
        return super().unlink()

    lot_name = fields.Char(string="LOT 번호", help="협력사 LOT 라벨 번호 (LOT 관리 품목)")


class StockPickingAsn(models.Model):
    _inherit = "stock.picking"

    asn_ids = fields.One2many("supplier.asn", "picking_id", string="납품 예정(ASN)")

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.state != "done":
                continue
            asns = picking.asn_ids | picking.move_ids.supplier_asn_line_id.asn_id
            if asns:
                asns._mark_received_from_picking(picking)
            # 발주 연동 입고면 포탈 상태도 납품완료로 — 협력사 화면 정합.
            # 단, 분할 납품이면 잔여 전표가 남으므로 모든 입고가 완료/취소된 뒤에만
            # 납품완료로 전환한다(부분입고 1회에 조기 완료되지 않게).
            if "purchase_id" in picking._fields and picking.purchase_id:
                po = picking.purchase_id
                if (po.auto_generated and po.portal_state == "approved"
                        and all(p.state in ("done", "cancel")
                                for p in po.picking_ids)):
                    po.action_mark_done()
        return res


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"
    scm_allocation_revision = fields.Integer(default=0, readonly=True, copy=False)


class StockMove(models.Model):
    _inherit = "stock.move"
    supplier_asn_line_id = fields.Many2one("supplier.asn.line", string="ASN 배정", readonly=True,
                                          index=True, copy=True, ondelete="restrict")

    def write(self, vals):
        if "supplier_asn_line_id" in vals and self.env.context.get("_asn_write") is not _ASN_WRITE:
            raise UserError(_("ASN 입고 배정은 납품 예정 처리 동작으로만 변경할 수 있습니다."))
        return super().write(vals)

    @api.constrains("supplier_asn_line_id", "company_id", "product_id", "purchase_line_id", "product_uom_qty", "state")
    def _check_asn_allocation(self):
        for move in self.filtered("supplier_asn_line_id"):
            line = move.supplier_asn_line_id
            if (move.company_id != line.company_id or move.product_id != line.product_id
                    or move.purchase_line_id != line.purchase_line_id):
                raise ValidationError(_("ASN 배정과 재고 이동의 회사·제품·구매 행이 다릅니다."))
            allocated = sum(m.product_qty for m in line.move_ids if m.state != "cancel"
                            and m.location_id.usage == "supplier" and m.location_dest_id.usage == "internal")
            if float_compare(allocated, line.qty, precision_rounding=line.product_id.uom_id.rounding) > 0:
                raise ValidationError(_("ASN 수량을 초과해 입고 이동을 배정할 수 없습니다."))
