import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError


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
    picking_id = fields.Many2one("stock.picking", string="입고 전표", readonly=True, copy=False)
    qr_token = fields.Char(string="납품패스 토큰", readonly=True, copy=False,
                           default=lambda self: secrets.token_urlsafe(16),
                           help="기사 제시용 QR 의 건별 토큰 — 포털 토큰과 분리(화면 노출 안전)")

    @api.model_create_multi
    def create(self, vals_list):
        seq = self.env["ir.sequence"]
        for vals in vals_list:
            if vals.get("name", "신규") == "신규":
                name = seq.next_by_code("supplier.asn")
                if not name:
                    # 시퀀스 부재 시(데이터 미적재 등) 상수 폴백으로 중복 채번되지 않게
                    # 규칙(ASN-%(y)s-)대로 즉석 생성 후 재채번
                    seq.sudo().create({
                        "name": "납품 예정(ASN)", "code": "supplier.asn",
                        "prefix": "ASN-%(y)s-", "padding": 4,
                    })
                    name = seq.next_by_code("supplier.asn")
                vals["name"] = name
        return super().create(vals_list)

    def action_create_picking(self):
        """도착 시 원클릭: ASN → 입고 전표(라인·LOT 프리필). 확정은 담당자가 실물 대조 후."""
        self.ensure_one()
        if self.state != "announced":
            raise UserError(_("납품 예정 상태에서만 입고 전표를 만들 수 있습니다."))
        if not self.line_ids:
            raise UserError(_("납품 품목이 없습니다."))
        wh = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1)
        sup_loc = self.env.ref("stock.stock_location_suppliers")
        Lot = self.env["stock.lot"]
        move_vals = []
        for line in self.line_ids:
            move_vals.append((0, 0, {
                "name": "%s/%s" % (self.name, line.product_id.default_code or ""),
                "product_id": line.product_id.id,
                "product_uom_qty": line.qty,
                "location_id": sup_loc.id,
                "location_dest_id": wh.lot_stock_id.id,
            }))
        picking = self.env["stock.picking"].create({
            "picking_type_id": wh.in_type_id.id,
            "partner_id": self.partner_id.id,
            "origin": self.name,
            "location_id": sup_loc.id,
            "location_dest_id": wh.lot_stock_id.id,
            "move_ids": move_vals,
        })
        # 확정(예약 재생성) 후에 라인을 채워야 수량·LOT 프리필이 유지된다
        picking.action_confirm()
        # 짝맞추기는 순서가 아니라 품목 기준 — 같은 품목 여러 줄이면
        # action_confirm 이 move 를 병합해 순서 zip 이 어긋난다
        moves_by_product = {m.product_id.id: m for m in picking.move_ids}
        picking.move_ids.move_line_ids.unlink()
        for line in self.line_ids:
            move = moves_by_product.get(line.product_id.id)
            if move is None:
                raise UserError(_("전표 라인 매칭 실패(%s) — 전표를 확인하세요.")
                                % line.product_id.display_name)
            ml = {"product_id": line.product_id.id,
                  "quantity": line.qty,
                  "location_id": sup_loc.id,
                  "location_dest_id": wh.lot_stock_id.id}
            # 협력사가 LOT 을 기재했으면 추적설정과 무관하게 부여 —
            # 수입검사(IQC) 보류가 LOT 에 걸리므로 추적 사슬의 열쇠다
            if line.lot_name:
                lot = Lot.search([("name", "=", line.lot_name),
                                  ("product_id", "=", line.product_id.id)], limit=1)
                if not lot:
                    lot = Lot.create({"name": line.lot_name,
                                      "product_id": line.product_id.id,
                                      "company_id": self.env.company.id})
                ml["lot_id"] = lot.id
            move.write({"move_line_ids": [(0, 0, ml)]})
        self.write({"picking_id": picking.id})
        self.message_post(body=_("입고 전표 %s 생성 — 실물 대조 후 확정하세요.") % picking.name)
        return {"type": "ir.actions.act_window", "res_model": "stock.picking",
                "res_id": picking.id, "view_mode": "form"}

    def action_cancel(self):
        for asn in self:
            if asn.state == "received":
                raise UserError(_("이미 입고 완료된 납품 예정은 취소할 수 없습니다."))
            asn.state = "cancelled"

    def _mark_received_from_picking(self, picking):
        """입고 전표 확정 훅에서 호출 — ASN 을 입고 완료로 마킹."""
        for asn in self:
            if asn.state == "announced" and asn.picking_id == picking:
                asn.state = "received"
                asn.message_post(body=_("입고 확정됨 (%s) — 협력사 포털 인수확인서 게시") % picking.name)


class SupplierAsnLine(models.Model):
    _name = "supplier.asn.line"
    _description = "납품 예정 라인"

    asn_id = fields.Many2one("supplier.asn", required=True, ondelete="cascade")
    product_id = fields.Many2one("product.product", string="품목", required=True)
    qty = fields.Float(string="납품 수량", required=True)
    lot_name = fields.Char(string="LOT 번호", help="협력사 LOT 라벨 번호 (LOT 관리 품목)")


class StockPickingAsn(models.Model):
    _inherit = "stock.picking"

    asn_ids = fields.One2many("supplier.asn", "picking_id", string="납품 예정(ASN)")

    def button_validate(self):
        res = super().button_validate()
        for picking in self:
            if picking.state != "done":
                continue
            if picking.asn_ids:
                picking.asn_ids._mark_received_from_picking(picking)
            # 발주 연동 입고면 포탈 상태도 납품완료로 — 협력사 화면 정합
            if "purchase_id" in picking._fields and picking.purchase_id:
                po = picking.purchase_id
                if po.auto_generated and po.portal_state == "approved":
                    po.action_mark_done()
        return res
