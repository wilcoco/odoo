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

KRW 한정
  Float 필드의 ``digits`` 는 레코드가 아니라 레지스트리 전체에 적용된다. 따라서
  모든 회사의 기준통화가 KRW인 DB에서만 패치를 켠다. 주문/청구서 통화가 따로
  있는 필드는 외화 문서를 보호하기 위해 0자리 대상에서 제외한다.

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
KRW_CURRENCY_CODE = "KRW"

# 회사 기준통화 금액(합계·잔액·평가액) 필드 → "KR Amount" (기본 0자리)
# 이 필드 메타데이터는 회사별로 나눌 수 없으므로 KRW 전용 DB에서만 적용한다.
AMOUNT_FIELDS = {
    "account.account": ("current_balance",),                 # 계정과목 폼의 '잔액' 버튼
    "account.invoice.report": (                              # 청구서 분석 (SQL 뷰)
        "price_subtotal", "price_average", "price_margin", "inventory_value",
    ),
    "product.product": ("value_svl",),                       # 재고 평가액
    "stock.lot": ("value_svl",),
    "stock.valuation.layer.revaluation": ("current_value_svl",),
}

# 레코드마다 통화가 달라질 수 있어 정적 0자리 패치를 적용하면 안 되는 필드.
# 문서화와 회귀 테스트에서 이 목록이 AMOUNT_FIELDS로 다시 들어가는 것을 막는다.
DOCUMENT_CURRENCY_FIELDS = {
    "account.invoice.report": ("price_subtotal_currency", "price_total"),
    "purchase.bill.union": ("amount",),
    "sale.order": ("amount_paid",),
}

# 단가 성격 필드 → 기존 "Product Price" 설정을 그대로 따르게 한다.
# (금액과 단가의 자리수를 따로 관리할 수 있도록 분리)
UNIT_PRICE_FIELDS = {
    "purchase.order.line": ("price_unit_discounted",),
    "purchase.bill.line.match": ("product_uom_price",),
    "sale.report": ("price_unit",),                          # 판매 분석 평균 단가
}

DISABLE_PARAM = "account_kr_plus_patch.integer_amounts"


def _all_currency_codes_are_krw(currency_codes):
    """레지스트리 전역 패치를 적용해도 되는 KRW 전용 DB인지 판별한다."""
    codes = list(currency_codes)
    return bool(codes) and all(code == KRW_CURRENCY_CODE for code in codes)


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
        if not self._kr_all_companies_use_krw():
            _logger.debug("회계 금액 소수점 제거 미적용: 기준통화가 KRW가 아닌 회사가 존재")
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
            _logger.info("KRW 회계 금액 소수점 제거 적용: %s", ", ".join(patched))

    def _kr_all_companies_use_krw(self):
        """필드 메타데이터가 전역이므로 모든 회사가 KRW일 때만 허용한다."""
        try:
            companies = self.env["res.company"].sudo().with_context(active_test=False).search([])
            currency_codes = companies.mapped("currency_id.name")
        except Exception:  # 설치 초기 등 회사/통화 테이블을 안전하게 못 읽는 상황
            _logger.debug("회사 기준통화 확인 실패로 금액 자리수 패치를 건너뜀", exc_info=True)
            return False
        return _all_currency_codes_are_krw(currency_codes)

    def _kr_amount_digits_enabled(self):
        try:
            param = self.env["ir.config_parameter"].sudo().get_param(DISABLE_PARAM, "1")
        except Exception:  # 설치 초기 등 파라미터 테이블을 못 읽는 상황
            return True
        return str(param).strip().lower() not in ("0", "false", "off")
