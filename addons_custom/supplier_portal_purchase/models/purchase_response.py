import hashlib
import json

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from .scm_utils import check_actor, check_quantity

_REVIEW_WRITE = object()


def request_snapshot(po):
    return {"company": po.company_id.id, "partner": po.partner_id.id,
        "lines": {str(line.id): {"product": line.product_id.id, "uom": line.product_uom.id,
            "quantity": line.product_qty, "date": fields.Datetime.to_string(line.date_planned)}
            for line in po.order_line if not line.display_type}}


def request_revision(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class PurchaseOrderResponse(models.Model):
    """협력사 응답 (정형화)"""
    _name = "purchase.order.response"
    _description = "협력사 발주 응답"
    _order = "create_date desc"
    company_id = fields.Many2one(related="purchase_order_id.company_id", store=True, index=True)
    request_snapshot = fields.Json(string="응답 당시 요청 근거", readonly=True, copy=False)
    request_revision = fields.Char(string="요청 개정 식별자", readonly=True, copy=False)

    purchase_order_id = fields.Many2one(
        "purchase.order",
        string="발주서",
        required=True,
        ondelete="cascade",
    )
    partner_id = fields.Many2one(
        related="purchase_order_id.partner_id",
        store=True,
    )
    response_type = fields.Selection(
        [
            ("full_accept", "전체 승인"),
            ("partial_accept", "조건부 승인"),
            ("reject", "납품 불가"),
        ],
        string="응답 유형",
        required=True,
    )
    response_date = fields.Datetime(
        string="응답 일시",
        default=fields.Datetime.now,
    )
    note = fields.Text(
        string="비고",
    )
    line_response_ids = fields.One2many(
        "purchase.order.line.response",
        "response_id",
        string="품목별 응답",
    )

    # 구매담당 검토
    review_state = fields.Selection(
        [
            ("pending", "검토 대기"),
            ("approved", "승인"),
            ("rejected", "반려"),
        ],
        string="검토 상태",
        default="pending",
    )
    reviewed_by = fields.Many2one(
        "res.users",
        string="검토자",
    )
    reviewed_date = fields.Datetime(
        string="검토 일시",
    )
    reject_reason = fields.Text(
        string="반려 사유",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            po = self.env["purchase.order"].browse(vals.get("purchase_order_id", self.env.context.get("default_purchase_order_id")))
            check_actor(po, po.partner_id)
            self.env.cr.execute("SELECT id FROM purchase_order WHERE id=%s FOR UPDATE", (po.id,))
            po.invalidate_recordset()
            if po.portal_state not in ("new", "rejected"):
                raise UserError(_("이미 응답이 접수됐습니다. 최신 요청과 응답을 확인하세요."))
            snapshot = request_snapshot(po)
            vals.update(request_snapshot=snapshot, request_revision=request_revision(snapshot),
                review_state="pending", reviewed_by=False, reviewed_date=False)
        responses = super().create(vals_list)
        for response in responses:
            # PO 상태 변경
            response.purchase_order_id.portal_state = "responded"
            # 구매담당자에게 알림
            response.purchase_order_id._create_portal_notification(
                "response_received",
                user=response.purchase_order_id.buyer_id,
            )
        return responses

    def write(self, vals):
        for response in self:
            check_actor(response, response.partner_id)
            if set(vals) & {"purchase_order_id", "request_snapshot", "request_revision"}:
                raise UserError(_("응답 당시의 요청 근거는 변경할 수 없습니다."))
            if set(vals) & {"review_state", "reviewed_by", "reviewed_date", "reject_reason"}:
                if self.env.context.get("_scm_review_write") is not _REVIEW_WRITE:
                    raise UserError(_("응답 검토 기록은 승인/반려 동작으로만 남길 수 있습니다."))
            elif response.review_state != "pending":
                raise UserError(_("검토가 완료된 응답은 변경할 수 없습니다."))
        return super().write(vals)

    def unlink(self):
        if any(response.review_state != "pending" for response in self):
            raise UserError(_("검토가 완료된 응답 증빙은 삭제할 수 없습니다."))
        return super().unlink()


class PurchaseOrderLineResponse(models.Model):
    """품목별 응답 상세"""
    _name = "purchase.order.line.response"
    _description = "품목별 발주 응답"
    company_id = fields.Many2one(related="response_id.company_id", store=True, index=True)
    _sql_constraints = [("response_order_line_unique", "unique(response_id, order_line_id)",
                         "한 응답에서 같은 요청 품목을 중복 응답할 수 없습니다.")]

    response_id = fields.Many2one(
        "purchase.order.response",
        string="응답",
        required=True,
        ondelete="cascade",
    )
    order_line_id = fields.Many2one(
        "purchase.order.line",
        string="발주 라인",
        required=True,
    )
    product_id = fields.Many2one(
        related="order_line_id.product_id",
        store=True,
    )

    # 요청 (원본)
    requested_qty = fields.Float(
        string="요청 수량",
        readonly=True,
    )
    requested_date = fields.Datetime(
        string="요청 납기",
        readonly=True,
    )

    # 협력사 응답
    confirmed_qty = fields.Float(
        string="확정 수량",
    )
    confirmed_date = fields.Date(
        string="확정 납기",
    )
    line_note = fields.Text(
        string="품목 비고",
    )
    line_status = fields.Selection(
        [
            ("ok", "일치"),
            ("qty_diff", "수량 차이"),
            ("date_diff", "납기 차이"),
            ("both_diff", "수량+납기 차이"),
            ("reject", "불가"),
        ],
        string="상태",
        compute="_compute_line_status",
        store=True,
    )

    # 구매담당 결정
    is_approved = fields.Boolean(
        string="승인",
        default=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            response = self.env["purchase.order.response"].browse(vals.get("response_id", self.env.context.get("default_response_id")))
            check_actor(response, response.partner_id)
            if response.review_state != "pending":
                raise UserError(_("검토된 응답에 행을 추가할 수 없습니다."))
            line_id = vals.get("order_line_id", self.env.context.get("default_order_line_id"))
            source = (response.request_snapshot or {}).get("lines", {}).get(str(line_id))
            if not source:
                raise UserError(_("응답 당시 요청에 없는 품목 행입니다. 새 요청으로 다시 응답하세요."))
            vals.update(requested_qty=source["quantity"], requested_date=source["date"])
        return super().create(vals_list)

    @api.constrains("response_id", "order_line_id", "confirmed_qty", "company_id")
    def _check_scm_scope(self):
        for line in self:
            check_actor(line, line.response_id.partner_id)
            check_quantity(line.confirmed_qty)
            if line.order_line_id.order_id != line.response_id.purchase_order_id:
                raise ValidationError(_("응답의 원 구매 주문과 품목 행이 다릅니다."))

    def write(self, vals):
        for line in self:
            check_actor(line, line.response_id.partner_id)
            if line.response_id.review_state != "pending" or set(vals) & {
                    "response_id", "order_line_id", "requested_qty", "requested_date"}:
                raise UserError(_("응답 요청 근거나 검토가 완료된 품목을 변경할 수 없습니다."))
        return super().write(vals)

    def unlink(self):
        if any(line.response_id.review_state != "pending" for line in self):
            raise UserError(_("검토된 응답의 품목은 삭제할 수 없습니다."))
        return super().unlink()

    @api.depends("requested_qty", "confirmed_qty", "requested_date", "confirmed_date")
    def _compute_line_status(self):
        for line in self:
            if line.confirmed_qty == 0 and not line.confirmed_date:
                line.line_status = "reject"
            elif not line.confirmed_qty or not line.confirmed_date:
                line.line_status = "ok"
            else:
                qty_diff = abs(line.requested_qty - line.confirmed_qty) > 0.01
                # requested_date는 Datetime, confirmed_date는 Date → date()로 비교
                req_date = line.requested_date.date() if line.requested_date else None
                conf_date = line.confirmed_date
                date_diff = req_date and conf_date and req_date != conf_date

                if qty_diff and date_diff:
                    line.line_status = "both_diff"
                elif qty_diff:
                    line.line_status = "qty_diff"
                elif date_diff:
                    line.line_status = "date_diff"
                else:
                    line.line_status = "ok"
