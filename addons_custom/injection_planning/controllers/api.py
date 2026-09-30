import json

from odoo import http
from odoo.http import request


class InjectionPlanningAPI(http.Controller):

    def _json_body(self):
        try:
            return json.loads(request.httprequest.data)
        except Exception:
            return {}

    def _error_response(self, message, status=400):
        return request.make_json_response(
            {"success": False, "error": message}, status=status,
        )

    def _success_response(self, data=None, status=200):
        return request.make_json_response(
            {"success": True, "data": data}, status=status,
        )

    def _scoped(self, model, domain=None, **kwargs):
        """토큰 사용자의 **권한과 회사 범위 안에서** 조회한다.

        [275 계획 리뷰 (4)] 예전에는 bearer 인증만 통과하면 `sudo()` 로 전 회사의
        금형·조합·계획을 그대로 내보냈다. 토큰이 곧 전권이 되는 셈이다. 토큰은 '누구인가'
        만 말한다 — 무엇을 볼 수 있는지는 그 사용자의 ACL·회사 규칙이 정한다.
        """
        companies = request.env.companies or request.env.user.company_ids
        scoped = request.env[model].with_context(
            allowed_company_ids=companies.ids)
        company_domain = []
        if "company_id" in scoped._fields:
            company_domain = ["|", ("company_id", "=", False),
                              ("company_id", "in", companies.ids)]
        return scoped.search(company_domain + (domain or []), **kwargs)

    # ── 금형 ──
    @http.route("/api/v1/planning/mold", auth="bearer", type="http", methods=["GET"], csrf=False)
    def list_molds(self, **kwargs):
        molds = self._scoped("injection.mold", [("state", "=", "active")])
        data = [{
            "id": m.id,
            "code": m.code,
            "name": m.name,
            "product_id": m.product_id.id,
            "product_name": m.product_id.name if m.product_id else "",
            "cavity_count": m.cavity_count,
            "changeover_hours": m.changeover_hours,
        } for m in molds]
        return self._success_response(data)

    # ── 사출기-금형 조합 ──
    @http.route("/api/v1/planning/capability", auth="bearer", type="http", methods=["GET"], csrf=False)
    def list_capabilities(self, **kwargs):
        caps = self._scoped("injection.machine.mold.capability", [("active", "=", True)])
        data = [{
            "id": c.id,
            "workcenter_id": c.workcenter_id.id,
            "workcenter_name": c.workcenter_id.name,
            "mold_id": c.mold_id.id,
            "mold_code": c.mold_id.code,
            "product_id": c.product_id.id if c.product_id else None,
            "cycle_time": c.cycle_time,
            "defect_rate": c.defect_rate,
            "initial_scrap": c.initial_scrap,
            "hourly_capacity": c.hourly_capacity,
        } for c in caps]
        return self._success_response(data)

    # ── 계획 실행 ──
    @http.route("/api/v1/planning/run", auth="bearer", type="http", methods=["GET"], csrf=False)
    def list_runs(self, **kwargs):
        runs = self._scoped("injection.planning.run", [], limit=20, order="create_date desc")
        data = [{
            "id": r.id,
            "name": r.name,
            "plan_date_from": str(r.plan_date_from),
            "plan_date_to": str(r.plan_date_to),
            "state": r.state,
            "mo_count": r.mo_count,
            "total_planned_qty": r.total_planned_qty,
            "total_changeovers": r.total_changeovers,
        } for r in runs]
        return self._success_response(data)
