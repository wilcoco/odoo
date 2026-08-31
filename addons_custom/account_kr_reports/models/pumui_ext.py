from odoo import api, fields, models


class PumuiRequest(models.Model):
    """품의서에서도 연결 청구서의 승인번호 정본을 놓치지 않게 표시한다."""

    _inherit = "pumui.request"

    kr_approval_numbers = fields.Char(
        string="연결 세금계산서승인번호",
        compute="_compute_kr_tax_invoice_numbers",
        store=True,
        help="취소되지 않은 연결 청구서의 kr_approval_number 정본 목록")
    kr_origin_numbers = fields.Char(
        string="연결 원본 세금계산서 승인번호",
        compute="_compute_kr_tax_invoice_numbers",
        store=True,
        help="취소되지 않은 연결 수정 청구서의 kr_origin_number 목록")

    @api.depends(
        "move_ids.state",
        "move_ids.kr_approval_number",
        "move_ids.kr_origin_number",
    )
    def _compute_kr_tax_invoice_numbers(self):
        for request in self:
            moves = request.move_ids.filtered(lambda move: move.state != "cancel")
            request.kr_approval_numbers = self._kr_join_move_values(
                moves, "kr_approval_number"
            )
            request.kr_origin_numbers = self._kr_join_move_values(
                moves, "kr_origin_number"
            )

    @staticmethod
    def _kr_join_move_values(moves, field_name):
        values = dict.fromkeys(
            value for value in moves.sorted("id").mapped(field_name) if value
        )
        return ", ".join(values) or False
