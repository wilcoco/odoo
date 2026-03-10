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

    # ── 금형 ──
    @http.route("/api/v1/planning/mold", auth="bearer", type="http", methods=["GET"], csrf=False)
    def list_molds(self, **kwargs):
        molds = request.env["injection.mold"].sudo().search([("state", "=", "active")])
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
        caps = request.env["injection.machine.mold.capability"].sudo().search([("active", "=", True)])
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
        runs = request.env["injection.planning.run"].sudo().search([], limit=20, order="create_date desc")
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
