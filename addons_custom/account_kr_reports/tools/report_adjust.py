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


# ---------------------------------------------------------------------------
# 계정 유형 — 영업외수익(42)
# ---------------------------------------------------------------------------
def fix_non_operating_income_types(env):
    """코드 42로 시작하는 영업외수익 계정이 income(매출)으로 지정된 것을 income_other 로 바꾼다.

    오두 기본 손익계산서(account_reports.profit_and_loss)는 계정코드가 아니라 계정
    유형으로 집계한다. 한국 계정과목표에서 42xxxx(이자수익·잡이익 등)가 income 으로
    들어와 있어 매출액에 섞이고 영업이익이 영업외수익만큼 부풀려졌다.
    income 과 income_other 는 모두 수익 그룹이라 전표·잔액·결산 이월에는 영향이 없다.
    계정코드는 회사별 값이므로 최상위 회사마다 조회한다. 바꾼 계정을 돌려준다.
    """
    Account = env["account.account"].sudo()
    changed = Account.browse()
    for company in env["res.company"].sudo().search([("parent_id", "=", False)]):
        accounts = Account.with_company(company).search([
            ("company_ids", "in", company.ids),
            ("code", "=like", "42%"),
            ("account_type", "=", "income"),
        ])
        if accounts:
            accounts.write({"account_type": "income_other"})
            changed |= accounts
            _logger.info(
                "영업외수익 계정 유형 보정(%s): %s → income_other",
                company.name, ", ".join(accounts.with_company(company).mapped("code")),
            )
    return changed


# ---------------------------------------------------------------------------
# 계정 유형 — 판매비와관리비(61)의 감가상각비
# ---------------------------------------------------------------------------
def fix_sga_depreciation_types(env):
    """코드 61로 시작하는 판관비 계정이 expense_depreciation 으로 지정된 것을 expense 로 바꾼다.

    기본 손익계산서의 '영업외비용'(OEXP) 칸은 실제로 expense_depreciation 유형을 집계한다.
    610006 감가상각비(더존 감가상각비(판)의 이관 계정)가 이 유형이라 판관비가 아닌
    영업외비용으로 빠지고 영업이익이 감가상각비만큼 부풀려진다. 2025년 결산부터 실제
    금액이 들어온다. 둘 다 비용 그룹이라 전표·잔액에는 영향이 없다. 바꾼 계정을 돌려준다.
    """
    Account = env["account.account"].sudo()
    changed = Account.browse()
    for company in env["res.company"].sudo().search([("parent_id", "=", False)]):
        accounts = Account.with_company(company).search([
            ("company_ids", "in", company.ids),
            ("code", "=like", "61%"),
            ("account_type", "=", "expense_depreciation"),
        ])
        if accounts:
            accounts.write({"account_type": "expense"})
            changed |= accounts
            _logger.info(
                "판관비 감가상각 계정 유형 보정(%s): %s → expense",
                company.name, ", ".join(accounts.with_company(company).mapped("code")),
            )
    return changed


# ---------------------------------------------------------------------------
# 기본 손익계산서 — account_reports.profit_and_loss
# ---------------------------------------------------------------------------
STANDARD_PL_TAX_LINE_CODE = "TAX"


def fix_standard_pl_net_profit_tax(env):
    """기본 손익계산서에 법인세 라인(코드 TAX)이 있으면 당기순이익(NEP)에서 차감되게 한다.

    이 DB에는 화면에서 '법인세등'(670001) 라인을 추가했지만(2026-04-27) 표준 NEP 수식
    (REV + OIN - COS - EXP - OEXP)은 그 라인을 모른다. 법인세가 계상되는 순간
    당기순이익이 법인세만큼 과대 표시된다. TAX 라인이 없는 DB는 대상이 아니다.
    고쳤으면 True.
    """
    report = env.ref("account_reports.profit_and_loss", raise_if_not_found=False)
    if not report:
        return False
    tax_line = report.line_ids.filtered(lambda l: l.code == STANDARD_PL_TAX_LINE_CODE)[:1]
    net_line = report.line_ids.filtered(lambda l: l.code == "NEP")[:1]
    if not tax_line or not net_line:
        return False
    tax_expression = tax_line.expression_ids.filtered(lambda e: e.label == "balance")[:1]
    net_expression = net_line.expression_ids.filtered(lambda e: e.label == "balance")[:1]
    if not tax_expression or not net_expression or net_expression.engine != "aggregation":
        return False
    if re.search(r"\bTAX\.balance\b", net_expression.formula or ""):
        return False
    # 법인세 라인이 비용을 양수로 집계(sum / 부호 없는 계정코드)하면 차감, 음수 집계면 가산
    if tax_expression.engine == "domain":
        positive = not (tax_expression.subformula or "").strip().startswith("-")
    elif tax_expression.engine == "account_codes":
        positive = not (tax_expression.formula or "").strip().startswith("-")
    else:
        _logger.warning(
            "기본 손익계산서 TAX 라인 엔진(%s)을 해석할 수 없어 당기순이익 보정 생략",
            tax_expression.engine,
        )
        return False
    new_formula = "%s %s TAX.balance" % (_norm(net_expression.formula), "-" if positive else "+")
    _logger.info("기본 손익계산서 당기순이익 수식 보정: %r → %r", net_expression.formula, new_formula)
    net_expression.sudo().write({"formula": new_formula})
    return True
