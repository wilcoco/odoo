"""[R136] 회사 운영 흐름 — canonical 업무 지도 위에 실제 ERP 원장을 읽기 전용으로 연결하는 서버 어댑터.

계약: docs/tasks/R136-DATA-CONTRACT.md (v3). 원칙:
- 지도(노드·부모·관계)는 data/r136_canonical_map.json 이 정본이며 docs 사본과 같아야 한다(시험이 대조).
- 모든 호출은 **현재 사용자**로 ORM ACL·record rule 을 지난다. sudo 집계 없음. 권한이 없으면 0 이 아니라 `restricted`.
- 모듈/모델이 없으면 `not_installed`, 어댑터가 없으면 `not_wired` — 숨기거나 정상으로 표시하지 않는다.
- 집계와 드릴다운은 같은 domain. 단위가 다른 수량을 합치지 않고 완료율을 만들지 않는다.
- 실제 FK 없는 관계는 그리지 않는다(맵 edge 만). 상태를 쓰거나 승인하지 않는다(읽기 전용).
"""
import json
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import file_open

_logger = logging.getLogger(__name__)
MAP_PATH = "cams_ops_dashboard/data/r136_canonical_map.json"


def _state_of(rec, field, mapping):
    return mapping.get(rec[field], "unknown") if field in rec._fields else "unknown"


class FactoryFlow(models.AbstractModel):
    _name = "cams.factory.flow"
    _description = "회사 운영 흐름 (읽기 전용 어댑터)"

    # ── 노드별 어댑터: process_id → 정의. 모델이 없으면 not_installed, 정의가 없으면 not_wired.
    # state_map: 원천 state 값 → 대기/진행/완료/보류/취소. late_field: 기한 필드(있으면 '기한 경과' 독립 지표).
    ADAPTERS = {
        "CO.SALES.PLAN_RECV": dict(model="production.demand", date="demand_date",
                                   state_field="state", state_map={"draft": "wait", "confirmed": "progress", "done": "done", "cancelled": "cancel"}),
        "CO.PROD.INJ_PLAN": dict(model="injection.planning.run", date="plan_date_from",
                                 state_field="state", state_map={"draft": "wait", "calculating": "wait", "review": "progress", "confirmed": "done", "done": "done", "cancelled": "cancel"},
                                 hold_expr=lambda r: getattr(r, "feasibility", "") in ("infeasible_proven", "infeasible_unresolved")),
        "CO.PROD.INJ_EXEC": dict(model="mrp.production", date="date_start", extra_domain=[("planning_line_id", "!=", False)],   # 사출 계획에서 나온 MO 만
                                 state_field="state", state_map={"draft": "wait", "confirmed": "wait", "progress": "progress", "to_close": "progress", "done": "done", "cancel": "cancel"},
                                 hold_expr=lambda r: getattr(r, "settlement_status", "") == "blocked"),
        "CO.SALES.BR": dict(model="br.intake", date="received_at", late_field="arrived_at",
                            state_expr=lambda r: "done" if getattr(r, "arrived_at", False) else ("progress" if getattr(r, "received_at", False) else "wait"),
                            late_expr=lambda r: bool(getattr(r, "arrived_at", False)) and (getattr(r, "transit_minutes", 0.0) or 0.0) > 120.0),
        "CO.QA.INSPECT": dict(model="iatf.process.inspection", date="create_date", state_field="state",
                              state_map={"draft": "wait", "inspecting": "progress", "decided": "done", "closed": "done", "cancelled": "cancel"}),
        "CO.QA.NC": dict(model="iatf.nonconformity", date="create_date", state_field="state",
                         state_map={"draft": "wait", "containment": "progress", "analysis": "progress", "corrective": "progress",
                                    "verification": "progress", "closed": "done", "cancelled": "cancel"}),
        "CO.FIN.SETTLE": dict(model="vendor.mrp.accrual", date="date",
                              state_expr=lambda r: "done" if (r.bill_id and r.bill_id.state == "posted") else ("progress" if r.state == "billed" else "wait")),
        "CO.ADM.OPS": dict(model="ops.task", date="scheduled_date", late_field="due_date",
                           state_field="state", state_map={"todo": "wait", "done": "done"},
                           late_expr=lambda r: getattr(r, "is_overdue", False)),
        "CO.EQ.AVAIL": dict(model="injection.machine.availability", date="date",
                            state_expr=lambda r: "hold" if getattr(r, "unavail_reason", False) else "done"),
        "CO.EQ.MOLD": dict(model="injection.mold", date="write_date",
                           state_expr=lambda r: {"active": "done", "maintenance": "hold", "retired": "cancel"}.get(r.state, "unknown")),
        # ── 2차 확장(7): 공급 계획·부품 입고·클레임·고장·계측기·결재(iatf 체계만)·PM
        "CO.MAT.SUPPLY_PLAN": dict(model="outsource.planning.run", date="plan_date_from", state_field="state",
                                   state_map={"draft": "wait", "calculating": "wait", "review": "progress", "confirmed": "done", "done": "done", "cancelled": "cancel"}),
        "CO.MAT.RECEIPT": dict(model="stock.picking", date="scheduled_date", extra_domain=[("picking_type_code", "=", "incoming")],
                               state_field="state", state_map={"draft": "wait", "waiting": "wait", "confirmed": "wait", "assigned": "progress", "done": "done", "cancel": "cancel"},
                               late_expr=lambda r: bool(r.date_deadline) and r.state not in ("done", "cancel") and r.date_deadline < fields.Datetime.now(),
                               note="입고 picking 만(무발주 식별·반품 경로는 미연결)"),
        "CO.SALES.CLAIM": dict(model="iatf.customer.complaint", date="received_date", state_field="state",
                               state_map={"new": "wait", "containment": "progress", "analysis": "progress", "corrective": "progress", "verification": "progress", "closed": "done"},
                               late_expr=lambda r: bool(r.response_due_date) and r.state != "closed" and r.response_due_date < fields.Date.today()),
        "CO.EQ.MAINT": dict(model="iatf.equipment.breakdown", date="occurrence_date", state_field="state",
                            state_map={"open": "wait", "repairing": "progress", "closed": "done"},
                            note="고장 원장만(예방보전 일정·일상점검은 미연결)"),
        "CO.EQ.GAGE": dict(model="iatf.measurement.equipment", date="next_calibration_date", state_field="state",
                           state_map={"active": "done", "calibrating": "progress", "quarantine": "hold", "retired": "cancel"},
                           late_expr=lambda r: bool(getattr(r, "is_overdue", False))),
        "CO.ADM.APPROVAL": dict(model="iatf.approval.request", date="create_date", state_field="state",
                                state_map={"draft": "wait", "in_progress": "progress", "approved": "done", "rejected": "cancel"},
                                note="iatf.approval 체계만(pumui·eapproval 은 미연결 — 통합 대기 목록 아님)"),
    }

    @api.model
    def _load_map(self):
        with file_open(MAP_PATH, "r") as handle:
            return json.load(handle)

    @api.model
    def _companies_domain(self, Model):
        if "company_id" in Model._fields:
            return [("company_id", "in", self.env.companies.ids)]
        return []

    @api.model
    def _period_domain(self, adapter, date_from, date_to):
        field = adapter.get("date")
        dom = []
        if field and date_from:
            dom.append((field, ">=", date_from))
        if field and date_to:
            dom.append((field, "<=", date_to))
        return dom

    @api.model
    def _node_domain(self, adapter, Model, filters):
        return (self._companies_domain(Model) + list(adapter.get("extra_domain", []))
                + self._period_domain(adapter, (filters or {}).get("date_from"), (filters or {}).get("date_to")))

    @api.model
    def _classify(self, adapter, rec):
        if "state_expr" in adapter:
            state = adapter["state_expr"](rec)
        else:
            state = _state_of(rec, adapter.get("state_field", "state"), adapter.get("state_map", {}))
        if state in ("wait", "progress") and adapter.get("hold_expr") and adapter["hold_expr"](rec):
            state = "hold"
        late = bool(adapter.get("late_expr") and adapter["late_expr"](rec))   # 기한 경과는 상태와 독립 지표
        return state, late

    @api.model
    def _node_status(self, node, filters):
        """한 노드의 연결 상태와 집계. 권한·모듈 부재를 상태로 돌려주고 0 으로 위장하지 않는다."""
        pid = node["process_id"]
        adapter = self.ADAPTERS.get(pid)
        base = {"process_id": pid, "as_of": fields.Datetime.to_string(fields.Datetime.now())}
        if not adapter:
            return dict(base, link="not_wired", counts=None, note=node.get("evidence") or "")
        Model = self.env.get(adapter["model"])
        if Model is None:
            return dict(base, link="not_installed", counts=None, model=adapter["model"])
        try:
            Model.check_access("read")
        except AccessError:
            return dict(base, link="restricted", counts=None, model=adapter["model"])
        domain = self._node_domain(adapter, Model, filters)
        records = Model.search(domain, limit=int((filters or {}).get("scan_limit") or 2000))
        counts = {"wait": 0, "progress": 0, "done": 0, "hold": 0, "cancel": 0, "unknown": 0, "late": 0}
        for rec in records:
            state, late = self._classify(adapter, rec)
            counts[state] = counts.get(state, 0) + 1
            if late:
                counts["late"] += 1
        total = Model.search_count(domain)
        updated = max((rec.write_date for rec in records if rec.write_date), default=False)
        return dict(base, link="linked", model=adapter["model"], domain=domain, total=total, note=adapter.get("note", ""),
                    scanned=len(records), truncated=total > len(records), counts=counts,
                    updated_at=fields.Datetime.to_string(updated) if updated else False,
                    denominator="현재 필터·회사 범위의 건수(단위 합산 없음)")

    @api.model
    def get_map(self, level=2, filters=None):
        """지도: 노드 계층 + 요청 계층까지의 노드별 연결 상태·집계. 상위 노드는 하위 leaf 상태를 요약(퍼센트 없음)."""
        data = self._load_map()
        nodes = [dict(n) for n in data["nodes"] if n["level"] <= int(level)]
        by_id = {n["process_id"]: n for n in nodes}
        for n in nodes:
            if n["level"] == int(level) or n["level"] >= 2:
                n["status"] = self._node_status(n, filters)
        # 상위 요약: 하위 노드의 link 상태 분포와 상태 건수 합(같은 단위인 '건수' 만)
        for n in nodes:
            if n["level"] < int(level):
                children = [c for c in nodes if c["parent_id"] == n["process_id"]]
                links = {}
                agg = {"wait": 0, "progress": 0, "done": 0, "hold": 0, "cancel": 0, "unknown": 0, "late": 0}
                for c in children:
                    st = c.get("status") or {}
                    links[st.get("link", "aggregate")] = links.get(st.get("link", "aggregate"), 0) + 1
                    for k, v in (st.get("counts") or {}).items():
                        agg[k] = agg.get(k, 0) + v
                n["status"] = {"process_id": n["process_id"], "link": "aggregate", "child_links": links, "counts": agg,
                               "note": "하위 노드 건수 합계(고유 사건 중복 제거 안 함 — 단계별 합계)"}
        return {"schema": data["schema"], "as_of": fields.Datetime.to_string(fields.Datetime.now()),
                "company_ids": self.env.companies.ids, "level": int(level), "nodes": nodes,
                "edges": [e for e in data.get("edges", [])],
                "filters": filters or {}, "heuristic_note": "합성/실 데이터 여부는 DB 에 따른다. 완료율을 만들지 않는다."}

    @api.model
    def get_node(self, process_id, filters=None, limit=20, offset=0):
        """노드 상세: 집계와 **같은 domain** 의 사례 목록(페이지). 권한 없는 사례는 목록에도 없다(ORM)."""
        data = self._load_map()
        node = next((n for n in data["nodes"] if n["process_id"] == process_id), None)
        if not node:
            raise UserError(_("업무 ID 를 찾을 수 없습니다: %s") % process_id)
        status = self._node_status(node, filters)
        rows = []
        if status["link"] == "linked":
            Model = self.env[status["model"]]
            adapter = self.ADAPTERS[process_id]
            for rec in Model.search(status["domain"], limit=max(1, min(int(limit), 200)), offset=max(0, int(offset)), order="id desc"):
                state, late = self._classify(adapter, rec)
                rows.append({"id": rec.id, "display_name": rec.display_name, "state": state, "late": late,
                             "write_date": fields.Datetime.to_string(rec.write_date) if rec.write_date else False})
        return {"node": node, "status": status, "rows": rows, "limit": limit, "offset": offset,
                "children": [n["process_id"] for n in data["nodes"] if n["parent_id"] == process_id]}

    @api.model
    def get_action(self, process_id, res_id=None, filters=None):
        """실제 원본으로 이동. 호출 시점에 다시 권한을 확인하고 집계와 같은 domain 을 쓴다(클라이언트 상태 불신)."""
        adapter = self.ADAPTERS.get(process_id)
        if not adapter or self.env.get(adapter["model"]) is None:
            raise UserError(_("이 업무는 실제 원장에 연결되어 있지 않습니다: %s") % process_id)
        Model = self.env[adapter["model"]]
        Model.check_access("read")
        # Odoo 18 클라이언트 doAction 은 dict 액션에 `views` 배열을 요구한다(view_mode 만 주면 _preprocessAction 에서 실패).
        action = {"type": "ir.actions.act_window", "res_model": adapter["model"], "name": process_id,
                  "view_mode": "list,form", "views": [[False, "list"], [False, "form"]],
                  "domain": self._node_domain(adapter, Model, filters), "target": "current"}
        if res_id:
            rec = Model.browse(int(res_id)).exists()
            if not rec:
                raise UserError(_("원본 문서가 없습니다."))
            rec.check_access("read")
            action.update({"view_mode": "form", "views": [[False, "form"]], "res_id": rec.id})
        return action
