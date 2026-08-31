"""회계 화면 금액에서 소수점(.00)을 없앤다 — 원화(KRW)는 소수 단위가 없다.

Odoo **기본 기능**으로 되는 부분 (여기서 손댈 필요 없음)
  1) 통화 반올림 계수  ``res.currency.rounding = 1``  →  ``decimal_places = 0``
     설정 > 회계 > 통화 > KRW.  ``fields.Monetary`` 로 선언된 금액은 전부 이 값을 따른다.
     (청구서 총액·분개 차변/대변·매입매출장·일월계표 등 대부분이 여기 해당)
  2) 소수점 정확도(``decimal.precision``) — 설정 > 기술 > 소수점 정확도.
     ``digits="Product Price"`` 처럼 **이름으로** 자리수를 참조하는 필드가 따른다.
     (단가 price_unit, 수량 quantity = "Product Unit of Measure" 등)

기본 기능으로 **안 되는** 부분 (이 파일이 담당)
  ``digits`` 인자 없이 선언된 ``fields.Float`` 는 자리수가 (16, 2) 로 고정이라
  설정 어디에서도 못 바꾼다 → 화면에 늘 "1,234,567.00" 으로 뜬다.
  아래 표에 적힌 **금액 필드만** 골라 자리수 소스를 다시 지정한다.

수량은 건드리지 않는다
  quantity / qty_* / product_uom_qty / quantity_svl 처럼 수량 성격인 Float 는
  표에서 의도적으로 제외했다. 수량 자리수는 "Product Unit of Measure" 설정으로
  관리한다 (소수점이 필요하면 그 값을 2 이상으로 둘 것).

되돌리기
  시스템 파라미터 ``account_kr_plus_patch.integer_amounts`` 를 ``0`` 으로 두고 서버 재시작.
  (필드 자리수는 레지스트리 구성 시점에 한 번 적용되므로 재시작이 필요하다)
"""

import logging

from odoo import models

_logger = logging.getLogger(__name__)

# 새로 추가한 소수점 정확도 항목 — data/decimal_precision.xml 에서 0자리로 생성.
# 레코드가 없으면 Odoo 가 2를 돌려주므로(=현재 동작) 설치 전에도 안전하다.
AMOUNT_PRECISION = "KR Amount"

# 금액(합계·잔액·평가액) 필드 → "KR Amount" (기본 0자리)
AMOUNT_FIELDS = {
    "account.account": ("current_balance",),                 # 계정과목 폼의 '잔액' 버튼
    "account.invoice.report": (                              # 청구서 분석 (SQL 뷰)
        "price_subtotal", "price_subtotal_currency", "price_total",
        "price_average", "price_margin", "inventory_value",
    ),
    "purchase.bill.union": ("amount",),                      # 구매 청구 대사 (SQL 뷰)
    "sale.order": ("amount_paid",),                          # 온라인 결제 수령액
    "product.product": ("value_svl",),                       # 재고 평가액
    "stock.lot": ("value_svl",),
    "stock.valuation.layer.revaluation": ("current_value_svl",),
}

# 단가 성격 필드 → 기존 "Product Price" 설정을 그대로 따르게 한다.
# (금액과 단가의 자리수를 따로 관리할 수 있도록 분리)
UNIT_PRICE_FIELDS = {
    "purchase.order.line": ("price_unit_discounted",),
    "purchase.bill.line.match": ("product_uom_price",),
    "sale.report": ("price_unit",),                          # 판매 분석 평균 단가
}

DISABLE_PARAM = "account_kr_plus_patch.integer_amounts"


class AccountMove(models.Model):
    """레지스트리 구성 직후 한 번 실행되는 자리수 패치의 걸이."""
    _inherit = "account.move"

    def _register_hook(self):
        res = super()._register_hook()
        self._kr_apply_amount_digits()
        return res

    def _kr_apply_amount_digits(self):
        if not self._kr_amount_digits_enabled():
            return
        patched = []
        for digits, table in ((AMOUNT_PRECISION, AMOUNT_FIELDS),
                              ("Product Price", UNIT_PRICE_FIELDS)):
            for model_name, field_names in table.items():
                if model_name not in self.env:
                    continue  # 해당 모듈 미설치 — 조용히 건너뛴다
                model = self.env[model_name]
                for fname in field_names:
                    field = model._fields.get(fname)
                    if field is None or field.type != "float":
                        continue
                    if field._digits is not None:
                        continue  # 이미 자리수가 지정된 필드는 존중한다
                    if field.store and model._auto:
                        # 실제 컬럼이 있는 저장 필드는 자리수를 바꾸면 컬럼 타입까지
                        # 바뀐다(float8 → numeric). 표시 목적으로 그런 위험을 지지 않는다.
                        _logger.debug("금액 자리수 패치 제외(저장 필드): %s.%s", model_name, fname)
                        continue
                    field._digits = digits
                    patched.append("%s.%s" % (model_name, fname))
        if patched:
            _logger.info("회계 금액 소수점 제거 적용: %s", ", ".join(patched))

    def _kr_amount_digits_enabled(self):
        try:
            param = self.env["ir.config_parameter"].sudo().get_param(DISABLE_PARAM, "1")
        except Exception:  # 설치 초기 등 파라미터 테이블을 못 읽는 상황
            return True
        return str(param).strip().lower() not in ("0", "false", "off")
