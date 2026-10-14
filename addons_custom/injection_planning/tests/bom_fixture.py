"""[R145 재기준화] 운영 BOM PLM(escon_bom_util 18.0.2.5.0, 미러 bfcdb58) 규칙에 맞는 시험용 BOM.

운영에서 사출 계획은 `mrp.bom.find_for_purpose(product, "injection")` 로만 BOM 을 찾는다
(표준 BOM fallback 없음). 그래서 시험 fixture 도 운영과 같은 모양 — 관리 BOM·목적 '사출'·
관리번호·활성 — 으로 만든다. 게이트를 낮추지 않고 fixture 를 운영 규칙에 맞춘 것이다.
escon_bom_util 이 없는 설치(순수 injection_planning)에서는 일반 BOM 으로 만든다.
"""
from odoo import Command  # noqa: F401 - 호출자 편의


def injection_management_number(env, name="TEST-INJECTION"):
    Number = env["escon.bom.management.number"].with_context(active_test=False)
    number = Number.search([("name", "=", name)], limit=1)
    if number:
        return number
    department = env["hr.department"].search([("name", "=", "T-사출팀")], limit=1) or \
        env["hr.department"].create({"name": "T-사출팀"})
    return Number.create({"name": name, "department_id": department.id})


def _is_injection_product(env, vals):
    """계획 코드의 사출품 판정(is_injection_part 또는 capability/금형 보유)과 같은 기준."""
    tmpl = env["product.template"].browse(vals.get("product_tmpl_id"))
    if not tmpl:
        return False
    if tmpl._fields.get("is_injection_part") and tmpl.is_injection_part:
        return True
    products = tmpl.product_variant_ids
    if "injection.machine.mold.capability" in env and env["injection.machine.mold.capability"].search_count(
            ["|", ("product_id", "in", products.ids), ("mold_id.product_id", "in", products.ids)]):
        return True
    return "injection.mold" in env and bool(env["injection.mold"].search_count([("product_id", "in", products.ids)]))


def injection_bom(env, vals, purpose=None):
    """운영 규칙의 BOM 하나를 만든다(기존 `env["mrp.bom"].create(vals)` 대체).

    사출품(계획 코드의 `_is_inj` 와 같은 기준)의 BOM 만 관리 사출 BOM 으로 만든다. 완제품(조립품) BOM 은
    운영 규칙대로 Odoo 표준 BOM 으로 두어 수요 전개의 `general_assembly` 표준 fallback 을 탄다 —
    운영 데이터에서 완제품 BOM 이 그렇게 분류되기 때문이다(escon_bom_util 18.0.2.5.0 migration).
    """
    Bom = env["mrp.bom"]
    if "bom_purpose" not in Bom._fields:
        return Bom.create(vals)
    if purpose is None:
        purpose = "injection" if _is_injection_product(env, vals) else "odoo_standard"
    if purpose == "odoo_standard":
        return Bom.create(vals)
    managed = dict(vals)
    managed.setdefault("bom_purpose", purpose)
    managed.setdefault("source_type", "injection_process" if purpose == "injection" else "manual")
    managed.setdefault("management_number_id", injection_management_number(env).id)
    managed.setdefault("bom_state", "active")
    managed.setdefault("active", True)
    return Bom.with_context(allow_managed_bom_create=True).create(managed)
