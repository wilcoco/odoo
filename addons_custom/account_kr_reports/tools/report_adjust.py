"""표준 보고서·계정 설정 보정 (K-GAAP 기준).

오두 표준 모듈(l10n_kr_reports, account_reports)이 넣은 보고서 정의에서 결함이
확인된 부분을 이 모듈에서 멱등하게 바로잡는다.

- 표준 모듈 업그레이드가 수식을 원래 값으로 되돌릴 수 있으므로, 수식 보정은
  account_kr_reports 설치·업그레이드 때마다 다시 확인한다
  (data/report_adjust_data.xml → kr.fs.line._kr_adjust_standard_reports).
- 예상한 '결함 수식'과 정확히 같을 때만 고친다. 사용자가 화면에서 이미 다른
  수식으로 바꿔 둔 경우는 건드리지 않고 로그만 남긴다.
"""
import logging
import re

_logger = logging.getLogger(__name__)


def _norm(formula):
    # account.report.expression.write 와 같은 규칙으로 공백을 정규화해 비교한다.
    return re.sub(r"\s+", " ", (formula or "").strip())


def _balance_expression(env, line_xmlid):
    line = env.ref(line_xmlid, raise_if_not_found=False)
    if not line:
        # account_kr_reports는 Enterprise account_reports에 대한 선택적 연동이다.
        # 해당 모듈이 미설치면 모델 자체가 registry에 없으므로 빈 recordset도 만들 수 없다.
        return False
    return line.expression_ids.filtered(lambda e: e.label == "balance")


# ---------------------------------------------------------------------------
# 손익계산서(KR) — l10n_kr_reports.l10n_kr_pl
# ---------------------------------------------------------------------------
# (라인 xml_id, 결함 수식, 올바른 수식, 사유)
KR_PL_FORMULA_FIXES = (
    (
        "l10n_kr_reports.l10n_kr_pl_income",
        "KR_GRP.balance + KR_EXP.balance",
        "KR_GRP.balance - KR_EXP.balance",
        "영업이익 = 매출총이익 - 판매비와관리비. KR_EXP(계정 61)는 양수 차변잔액이라 "
        "더하면 판관비의 2배만큼 영업이익·당기순이익이 부풀려진다",
    ),
    (
        "l10n_kr_reports.l10n_kr_pl_tax_expense",
        "63",
        "63 + 67",
        "법인세비용에 670001 법인세등(더존 998 법인세등의 이관 계정)을 포함. "
        "빠지면 손익계산서(KR)에서 법인세가 누락되고 재무상태표(KR) 당기순이익과 어긋난다",
    ),
)


def fix_kr_pl_formulas(env):
    """손익계산서(KR)의 결함 수식을 바로잡는다. 고친 수식 개수를 돌려준다."""
    fixed = 0
    for xmlid, wrong, right, reason in KR_PL_FORMULA_FIXES:
        expression = _balance_expression(env, xmlid)
        if not expression:
            continue
        current = _norm(expression.formula)
        if current == _norm(right):
            continue
        if current != _norm(wrong):
            _logger.warning(
                "손익계산서(KR) %s 수식이 예상과 달라 보정하지 않음: %r (기대 결함: %r)",
                xmlid, expression.formula, wrong,
            )
            continue
        expression.sudo().write({"formula": right})
        fixed += 1
        _logger.info("손익계산서(KR) %s 수식 보정: %r → %r — %s", xmlid, wrong, right, reason)
    return fixed
