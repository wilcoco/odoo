from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

from ..tools.approval_number import approval_number_key, normalize_approval_number

INV_TYPES = ("out_invoice", "in_invoice", "out_refund", "in_refund")
PURCHASE_TAX_MOVE_TYPES = ("in_invoice", "in_refund")
TAX_DOCUMENT_TYPES = ("tax_invoice", "invoice")


class AccountMove(models.Model):
    """리포트 #15·#16·#17·#18: 한국식 과세유형·증빙종류·승인번호(중복차단)·수정분 연결."""
    _inherit = "account.move"

    kr_tax_type = fields.Selection(
        [("taxable", "과세"), ("zero", "영세"), ("exempt", "면세")],
        string="과세 구분", compute="_compute_kr_tax_type", store=True, readonly=False,
        index=True, tracking=True,
        help="라인 세금에서 자동 추정(과세: 세율>0 / 영세: 0% 세금 존재 / 면세: 세금 없음).\n"
             "직접 고르면 그 값이 유지되고, 라인 세금이 해당 구분에 맞게 바뀝니다.")
    kr_tax_type_manual = fields.Boolean(
        string="과세 구분 수동 지정", copy=False, default=False,
        help="사용자가 과세 구분을 직접 고른 전표. 라인 세금이 바뀌어도 자동 추정이 덮어쓰지 않는다.")
    kr_doc_type = fields.Selection(
        [("tax_invoice", "세금계산서"), ("invoice", "계산서(면세)"), ("card", "카드"),
         ("cash_receipt", "현금영수증"), ("etc", "기타")],
        string="증빙 종류", default="tax_invoice", index=True, tracking=True)
    kr_approval_number = fields.Char(
        string="세금계산서승인번호", copy=False, index=True, tracking=True,
        help="국세청 승인번호 — 중복 업로드 차단 기준 (리포트 #16)")
    kr_approval_number_key = fields.Char(
        string="세금계산서승인번호 조회 키",
        compute="_compute_kr_approval_number_key",
        store=True,
        copy=False,
        index=True,
        help="승인번호의 공백·하이픈·대소문자 차이를 제거한 내부 조회 키")
    kr_is_correction = fields.Boolean(
        string="수정/마이너스분", compute="_compute_kr_correction", store=True,
        help="환불 전표이거나 총액이 음수면 수정·마이너스 세금계산서로 표시")
    kr_origin_number = fields.Char(
        string="원본 세금계산서 승인번호", copy=False, tracking=True,
        help="수정/마이너스 세금계산서의 원본 승인번호 (리포트 #17)")
    kr_partner_vat = fields.Char(related="partner_id.vat", string="사업자등록번호")

    _sql_constraints = [
        ("kr_approval_number_uniq", "unique(kr_approval_number)",
         "이미 업로드된 세금계산서입니다. 승인번호와 거래처를 확인해주세요."),
    ]

    @api.depends("kr_approval_number")
    def _compute_kr_approval_number_key(self):
        for move in self:
            move.kr_approval_number_key = approval_number_key(
                move.kr_approval_number
            )

    @api.model
    def _kr_approval_key(self, value):
        """다른 모듈이 승인번호를 비교할 때 사용하는 단일 정규화 계약."""
        return approval_number_key(value)

    @api.model
    def _kr_find_by_approval_number(
        self, approval_number, company=None, move_types=None, limit=None
    ):
        """표기 차이와 무관하게 정본 승인번호로 전표를 찾는다.

        호출자의 접근권한과 활성 회사 범위를 유지한다. 전사 중복 확인이 필요한
        내부 로직은 ``self.sudo()``에서 이 메서드를 호출해야 한다.
        """
        key = self._kr_approval_key(approval_number)
        if not key:
            return self.browse()
        domain = [("kr_approval_number_key", "=", key)]
        if company:
            company_id = company.id if hasattr(company, "id") else company
            domain.append(("company_id", "=", company_id))
        if move_types:
            domain.append(("move_type", "in", tuple(move_types)))
        return self.search(domain, limit=limit)

    @api.constrains("kr_approval_number", "kr_approval_number_key")
    def _check_kr_approval_number_key_unique(self):
        keys = set(self.filtered("kr_approval_number_key").mapped(
            "kr_approval_number_key"
        ))
        for key in keys:
            duplicates = self.sudo().search([
                ("kr_approval_number_key", "=", key),
            ], limit=2)
            if len(duplicates) > 1:
                raise ValidationError(_(
                    "이미 등록된 세금계산서승인번호입니다. 하이픈·공백·대소문자가 "
                    "달라도 같은 승인번호로 처리합니다."
                ))

    @api.model
    def _kr_normalize_approval_values(self, vals):
        vals = dict(vals)
        for field_name in ("kr_approval_number", "kr_origin_number"):
            if field_name in vals:
                normalized = normalize_approval_number(vals[field_name])
                if normalized:
                    vals[field_name] = normalized
        return vals

    @api.model
    def _kr_prepare_legacy_ref_approval(self, vals):
        """과거 ref의 승인번호를 정본이 비어 있을 때 한 번만 복사한다."""
        vals = self._kr_normalize_approval_values(vals)
        if (
            self.env.context.get("skip_kr_legacy_ref_sync")
            or "kr_approval_number" in vals
        ):
            return vals
        move_type = vals.get(
            "move_type", self.env.context.get("default_move_type")
        )
        document_type = vals.get(
            "kr_doc_type",
            self.env.context.get("default_kr_doc_type", "tax_invoice"),
        )
        if (
            move_type in PURCHASE_TAX_MOVE_TYPES
            and document_type in TAX_DOCUMENT_TYPES
            and (approval := normalize_approval_number(vals.get("ref")))
        ):
            vals["kr_approval_number"] = approval
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        return super().create([
            self._kr_prepare_legacy_ref_approval(vals) for vals in vals_list
        ])

    def write(self, vals):
        vals = self._kr_normalize_approval_values(vals)
        protected_fields = {
            "kr_approval_number": _("세금계산서승인번호"),
            "kr_origin_number": _("원본 세금계산서 승인번호"),
        }
        for field_name, label in protected_fields.items():
            if field_name not in vals:
                continue
            new_key = self._kr_approval_key(vals.get(field_name))
            for move in self:
                old_key = self._kr_approval_key(move[field_name])
                if old_key and not new_key:
                    raise UserError(_(
                        "%(field)s는 매핑 기준 데이터이므로 삭제할 수 없습니다. "
                        "잘못 입력한 값은 초안 상태에서 올바른 번호로 변경하세요."
                    ) % {"field": label})
                if move.state == "posted" and old_key and old_key != new_key:
                    raise UserError(_(
                        "전기된 전표의 %(field)s는 변경할 수 없습니다. "
                        "필요하면 전표를 초안으로 되돌린 뒤 수정하세요."
                    ) % {"field": label})

        write_self = self
        if set(vals) <= set(protected_fields):
            write_self = self.with_context(skip_is_manually_modified=True)
        result = super(AccountMove, write_self).write(vals)
        if (
            self.env.context.get("skip_kr_legacy_ref_sync")
            or "kr_approval_number" in vals
            or "ref" not in vals
        ):
            return result

        approval = normalize_approval_number(vals.get("ref"))
        if not approval:
            return result
        moves = self.filtered(
            lambda move: (
                not move.kr_approval_number
                and move.move_type in PURCHASE_TAX_MOVE_TYPES
                and move.kr_doc_type in TAX_DOCUMENT_TYPES
            )
        )
        if moves:
            moves.with_context(
                skip_kr_legacy_ref_sync=True,
                skip_is_manually_modified=True,
            ).write({"kr_approval_number": approval})
        return result

    @api.depends("invoice_line_ids.tax_ids", "invoice_line_ids.tax_ids.amount")
    def _compute_kr_tax_type(self):
        for mv in self:
            if mv.move_type not in INV_TYPES:
                mv.kr_tax_type = False
                continue
            # 사용자가 직접 고른 전표는 덮어쓰지 않는다 —
            # 면세로 바꿔도 라인 세금 변경 때마다 과세로 되돌아가던 문제
            if mv.kr_tax_type_manual:
                continue
            mv.kr_tax_type = mv._kr_auto_tax_type()

    def _kr_auto_tax_type(self):
        """라인 세금에서 추정한 과세 구분 (과세>0 / 영세 0% / 세금없음 면세)."""
        self.ensure_one()
        taxes = self.invoice_line_ids.filtered(
            lambda l: l.display_type == "product").mapped("tax_ids")
        if not taxes:
            return "exempt"
        if any(t.amount > 0 for t in taxes):
            return "taxable"
        return "zero"

    def _kr_tax_for_type(self, tax_type):
        """과세 구분에 맞는 세금 코드 — 한국 세목(l10n_kr) 명명 규칙 기준.

        과세: 10% TI / 영세: 0% ... ZR(영세율) / 면세: 0% ... TF(면세).
        면세도 **세금 코드가 있어야** 분개와 부가세 신고 태그가 맞는다
        (세금을 비워두면 신고 자료에서 빠진다).
        """
        self.ensure_one()
        use = "sale" if self.move_type in ("out_invoice", "out_refund") else "purchase"
        Tax = self.env["account.tax"]
        base = [("type_tax_use", "=", use), ("company_id", "=", self.company_id.id)]
        if tax_type == "taxable":
            return (Tax.search(base + [("name", "=", "10% TI")], limit=1)
                    or Tax.search(base + [("amount", "=", 10), ("amount_type", "=", "percent")], limit=1))
        if tax_type == "zero":
            return (Tax.search(base + [("name", "like", "ZR")], limit=1)
                    or Tax.search(base + [("amount", "=", 0)], limit=1))
        if tax_type == "exempt":
            return (Tax.search(base + [("name", "like", "TF")], limit=1)
                    or Tax.search(base + [("amount", "=", 0)], limit=1))
        return Tax.browse()

    @api.onchange("kr_tax_type")
    def _onchange_kr_tax_type(self):
        """과세 구분을 고르면 **라인 세금이 그에 맞게 바뀐다.**

        기존에는 구분만 바뀌고 세금은 그대로여서, 면세로 골라도 세액이 계산된
        분개가 만들어지고 담당자가 수동으로 맞춰야 했다.
        """
        for mv in self:
            if mv.move_type not in INV_TYPES or not mv.kr_tax_type:
                continue
            if mv.kr_tax_type == mv._kr_auto_tax_type():
                continue  # 라인 세금과 이미 일치 — 사용자의 의도적 변경이 아니다
            mv.kr_tax_type_manual = True
            tax = mv._kr_tax_for_type(mv.kr_tax_type)
            if not tax:
                return {"warning": {
                    "title": _("세금 코드 없음"),
                    "message": _("'%s' 에 해당하는 세금 코드를 찾지 못했습니다. "
                                 "회계 설정 › 세금을 확인해 주세요. 라인 세금은 그대로 둡니다.")
                                % dict(self._fields["kr_tax_type"].selection).get(mv.kr_tax_type)}}
            for line in mv.invoice_line_ids.filtered(lambda l: l.display_type == "product"):
                line.tax_ids = [(6, 0, tax.ids)]
            mv.kr_doc_type = "invoice" if mv.kr_tax_type == "exempt" else "tax_invoice"

    @api.depends("move_type", "amount_total")
    def _compute_kr_correction(self):
        # amount_total_signed 는 매입청구서(in_invoice)에서 항상 음수(오두 부호 규약)라
        # 정상 매입분이 전부 수정분으로 오판됐다 → 부호 없는 amount_total 로 판정
        for mv in self:
            mv.kr_is_correction = (
                mv.move_type in ("out_refund", "in_refund")
                or (mv.move_type in ("out_invoice", "in_invoice") and mv.amount_total < 0))
