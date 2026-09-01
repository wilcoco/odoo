"""에스콘 전자결재 대시보드 집계.

OWL 클라이언트(`escon_eapproval.dashboard`)가 단일 RPC
(`escon.eapproval.dashboard.get_dashboard_data`)로 화면 전체 데이터를 받는다.

설계 원칙 (injection_worksite 대시보드와 동일)
- 쿼리는 배치(search_read / _read_group)로, 문서별 루프 RPC 를 만들지 않는다.
- 권한 오류(AccessError)는 섹션 단위로 격리해 errors[] 에 남기고 나머지는 계속 그린다.
- sudo() 는 라벨(ir.model 명칭) 조회에만 쓴다 — 문서 데이터는 사용자 권한 그대로.
"""

import logging
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError

from .setup import ESCON_GROUPS

_logger = logging.getLogger(__name__)

APPROVAL_STATES = ("draft", "in_progress", "approved", "rejected")

# Odoo 전자결재(approval.request) 상태 → 공통 상태 키 (클라이언트 칩 공유)
APPROVALS_STATE_MAP = {
    "new": "draft",
    "pending": "in_progress",
    "approved": "approved",
    "refused": "rejected",
    "cancel": "cancel",
}

# 클라이언트 드릴다운용 액션 xml id (설치 안 된 모듈 것은 페이로드에서 빠진다)
DRILL_XML_IDS = {
    "pumui_list": "pumui_approval.action_pumui_request",
    "pumui_inbox": "pumui_approval.action_pumui_my_inbox",
    "pumui_pending": "pumui_approval.action_pumui_to_approve",
    "pumui_unlinked": "pumui_approval.action_moves_no_pumui",
    "leave_dashboard": "escon_eapproval.action_escon_leave_open",
    "leave_my": "escon_eapproval.action_escon_leave_my",
    "leave_approve": "hr_holidays.hr_leave_action_action_approve_department",
    "templates": "iatf_approval.action_iatf_approval_template",
    "approvals_new": "escon_eapproval.action_eapproval_compose",
    "approvals_my": "approvals.approval_request_action",
    "approvals_review": "approvals.approval_request_action_to_review",
}


def _d(value):
    return fields.Date.to_string(value) if value else False


def _dt(value):
    return fields.Datetime.to_string(value) if value else False


class EsconEapprovalDashboard(models.AbstractModel):
    _name = "escon.eapproval.dashboard"
    _description = "에스콘 전자결재 대시보드 집계"

    # ------------------------------------------------------------------
    # 품의서 작성 화면 (OWL) — 유형 카드 목록
    # ------------------------------------------------------------------
    @api.model
    def get_compose_data(self):
        user = self.env.user
        categories = []
        counts = {}
        Request = self.env["approval.request"]
        for category, count in Request._read_group(
                [("request_owner_id", "=", user.id),
                 ("request_status", "in", ("new", "pending"))],
                groupby=["category_id"], aggregates=["__count"]):
            counts[category.id] = count
        for category in self.env["approval.category"].search([], order="sequence, id"):
            image = category.image
            categories.append({
                "id": category.id,
                "name": category.name,
                "description": category.description or "",
                "group": category.escon_group or "admin",
                "image": image.decode("ascii") if isinstance(image, bytes)
                         else (image or ""),
                "my_open": counts.get(category.id, 0),
            })
        xml_ids = {}
        for key in ("leave_dashboard", "pumui_list"):
            xmlid = DRILL_XML_IDS[key]
            if self.env.ref(xmlid, raise_if_not_found=False):
                xml_ids[key] = xmlid
        return {
            "groups": [{"key": key, "label": label} for key, label in ESCON_GROUPS],
            "categories": categories,
            "pumui": {"installed": "pumui.request" in self.env},
            "drill": {"xml_ids": xml_ids},
        }

    # ------------------------------------------------------------------
    # 결재 요청 → 화면 행
    # ------------------------------------------------------------------
    def _request_row(self, request):
        """iatf.approval.request 1건을 대상 문서 정보와 함께 직렬화."""
        doc_name = "(문서 없음)"
        doc_label = request.res_model or "-"
        doc_ok = False
        if request.res_model and request.res_model in self.env:
            model = self.env["ir.model"].sudo()._get(request.res_model)
            doc_label = model.name or request.res_model
            try:
                target = self.env[request.res_model].browse(request.res_id)
                if target.exists():
                    doc_name = target.display_name
                    doc_ok = True
                else:
                    doc_name = "(삭제된 문서)"
            except AccessError:
                doc_name = "(권한 없는 문서)"
        lines = request.line_ids
        return {
            "id": request.id,
            "doc_model": request.res_model,
            "doc_id": request.res_id,
            "doc_ok": doc_ok,
            "doc_label": doc_label,
            "doc_name": doc_name,
            "requester": request.requester_id.name or "-",
            "state": request.state,
            "date": _dt(request.create_date),
            "step_done": len(lines.filtered(lambda l: l.state == "approved")),
            "step_total": len(lines),
            "current_approver": request.current_approver_id.name or "-",
        }

    def _approvals_row(self, request):
        """Odoo 전자결재(approval.request) 1건을 결재 대기/내 상신 공통 행으로 직렬화."""
        approvers = request.approver_ids
        pending = approvers.filtered(lambda a: a.status == "pending")[:1]
        return {
            # iatf 요청 id 와 t-key 충돌을 피하려고 음수 id 사용
            "id": -request.id,
            "doc_model": "approval.request",
            "doc_id": request.id,
            "doc_ok": True,
            "doc_label": request.category_id.name or "전자결재",
            "doc_name": request.name or request.display_name,
            "requester": request.request_owner_id.name or "-",
            "state": APPROVALS_STATE_MAP.get(request.request_status, "draft"),
            "date": _dt(request.create_date),
            "step_done": len(approvers.filtered(lambda a: a.status == "approved")),
            "step_total": len(approvers),
            "current_approver": pending.user_id.name if pending else "-",
        }

    # ------------------------------------------------------------------
    # 진입점
    # ------------------------------------------------------------------
    @api.model
    def get_dashboard_data(self, limit=10):
        user = self.env.user
        employee = user.employee_id
        errors = []
        limit = int(limit or 10)

        def safe(section, fn, default):
            try:
                return fn()
            except AccessError as exc:
                _logger.info("eapproval.dashboard %s 권한 없음: %s", section, exc)
                errors.append({"section": section, "message": "접근 권한이 없습니다."})
                return default

        now = fields.Datetime.now()
        d30 = now - timedelta(days=30)
        Request = self.env["iatf.approval.request"]

        # ── 내가 결재할 차례 ────────────────────────────────────────────
        to_approve = safe(
            "to_approve",
            lambda: [
                self._request_row(r)
                for r in Request.search(
                    [("state", "=", "in_progress"),
                     ("current_approver_id", "=", user.id)],
                    order="id desc", limit=50)
            ],
            [],
        )

        # ── 내 상신 문서 (모든 결재 문서 공통) ──────────────────────────
        my_requests = safe(
            "my_requests",
            lambda: [
                self._request_row(r)
                for r in Request.search(
                    [("requester_id", "=", user.id)],
                    order="id desc", limit=limit)
            ],
            [],
        )

        def _my_counts():
            counts = dict.fromkeys(APPROVAL_STATES, 0)
            for state, count in Request._read_group(
                    [("requester_id", "=", user.id)],
                    groupby=["state"], aggregates=["__count"]):
                counts[state] = count
            counts["approved_30d"] = Request.search_count(
                [("requester_id", "=", user.id), ("state", "=", "approved"),
                 ("approved_date", ">=", _dt(d30))])
            counts["rejected_30d"] = Request.search_count(
                [("requester_id", "=", user.id), ("state", "=", "rejected"),
                 ("rejected_date", ">=", _dt(d30))])
            return counts

        my_counts = safe("my_counts", _my_counts,
                         dict.fromkeys(APPROVAL_STATES, 0)
                         | {"approved_30d": 0, "rejected_30d": 0})

        # ── Odoo 전자결재(approvals) 통합 — 같은 리스트/KPI 에 합산 ─────
        appr_counts = {"in_progress": 0, "approved_30d": 0, "rejected_30d": 0}
        if "approval.request" in self.env:
            ApprovalRequest = self.env["approval.request"]

            def _appr_to_approve():
                lines = self.env["approval.approver"].search(
                    [("user_id", "=", user.id), ("status", "=", "pending")], limit=50)
                requests = lines.mapped("request_id").filtered(
                    lambda r: r.request_status == "pending")
                return [self._approvals_row(r) for r in requests]

            def _appr_mine():
                return [
                    self._approvals_row(r)
                    for r in ApprovalRequest.search(
                        [("request_owner_id", "=", user.id)],
                        order="id desc", limit=limit)
                ]

            def _appr_counts():
                base = [("request_owner_id", "=", user.id)]
                return {
                    "in_progress": ApprovalRequest.search_count(
                        base + [("request_status", "=", "pending")]),
                    "approved_30d": ApprovalRequest.search_count(
                        base + [("request_status", "=", "approved"),
                                ("date_confirmed", ">=", _dt(d30))]),
                    "rejected_30d": ApprovalRequest.search_count(
                        base + [("request_status", "=", "refused"),
                                ("write_date", ">=", _dt(d30))]),
                }

            to_approve += safe("approvals_to_approve", _appr_to_approve, [])
            my_requests += safe("approvals_my_requests", _appr_mine, [])
            appr_counts = safe("approvals_counts", _appr_counts, appr_counts)

        to_approve.sort(key=lambda r: r["date"] or "", reverse=True)
        my_requests.sort(key=lambda r: r["date"] or "", reverse=True)
        my_requests = my_requests[:limit]

        # ── 휴가 (hr_holidays) ─────────────────────────────────────────
        Leave = self.env["hr.leave"]

        def _leaves():
            rows = []
            for lv in Leave.search([("user_id", "=", user.id)],
                                   order="request_date_from desc", limit=8):
                rows.append({
                    "id": lv.id,
                    "type": lv.holiday_status_id.name or "-",
                    "date_from": _d(lv.request_date_from),
                    "date_to": _d(lv.request_date_to),
                    "days": round(lv.number_of_days, 2),
                    "state": lv.state,
                })
            return rows

        leaves = safe("leaves", _leaves, [])

        def _leave_balance():
            """유형별 배정/사용/잔여 — Odoo 표준 계산을 그대로 사용.
            (배정 유효기간을 존중하므로 기간 만료된 연차는 자동으로 빠진다)"""
            if not employee:
                return []
            balance = []
            types = self.env["hr.leave.type"].with_context(
                employee_id=employee.id).search([("requires_allocation", "=", "yes")])
            for lt in types:
                if not lt.max_leaves:
                    continue
                balance.append({
                    "type": lt.name,
                    "allocated": round(lt.max_leaves, 2),
                    "used": round(lt.leaves_taken, 2),
                    "remaining": round(lt.virtual_remaining_leaves, 2),
                })
            return balance

        leave_balance = safe("leave_balance", _leave_balance, [])
        leave_pending = safe(
            "leave_pending",
            lambda: Leave.search_count(
                [("user_id", "=", user.id), ("state", "in", ("confirm", "validate1"))]),
            0,
        )

        # ── 품의서 (설치된 경우에만) ────────────────────────────────────
        pumui = {"installed": False}
        if "pumui.request" in self.env:
            def _pumui():
                Pumui = self.env["pumui.request"]
                counts = dict.fromkeys(APPROVAL_STATES, 0)
                none_count = 0
                for state, count in Pumui._read_group(
                        [("requester_id", "=", user.id)],
                        groupby=["approval_state"], aggregates=["__count"]):
                    if state:
                        counts[state] = count
                    else:
                        none_count = count
                counts["draft"] += none_count  # 결재요청 미생성 = 초안
                recent = []
                for rec in Pumui.search([("requester_id", "=", user.id)],
                                        order="id desc", limit=5):
                    recent.append({
                        "id": rec.id,
                        "name": rec.name,
                        "title": rec.title,
                        "partner": rec.partner_id.name or "-",
                        "amount_total": rec.amount_total,
                        "approval_state": rec.approval_state or "draft",
                        "billing_status": rec.billing_status,
                        "date": _d(rec.date),
                    })
                data = {
                    "installed": True,
                    "counts": counts,
                    "to_approve_count": Pumui.search_count(
                        [("approval_state", "=", "in_progress"),
                         ("approval_current_approver_id", "=", user.id)]),
                    "recent": recent,
                    "unlinked_moves": 0,
                }
                try:
                    data["unlinked_moves"] = self.env["account.move"].search_count(
                        [("move_type", "in", ("out_invoice", "in_invoice")),
                         ("pumui_id", "=", False), ("state", "!=", "cancel")])
                except AccessError:
                    pass  # 회계 권한이 없는 사용자는 미연계 카운트만 생략
                return data

            pumui = safe("pumui", _pumui, {"installed": False})

        # ── 드릴다운 xml id (설치/권한에 따라 존재하는 것만) ───────────
        xml_ids = {}
        for key, xmlid in DRILL_XML_IDS.items():
            if self.env.ref(xmlid, raise_if_not_found=False):
                xml_ids[key] = xmlid
        if not user.has_group("hr_holidays.group_hr_holidays_responsible"):
            xml_ids.pop("leave_approve", None)
        if not user.has_group("escon_eapproval.group_eapproval_manager"):
            xml_ids.pop("templates", None)

        return {
            "user": {
                "name": user.name,
                "department": employee.department_id.name or "" if employee else "",
                "job": employee.job_id.name or "" if employee else "",
                "grade": employee.job_grade_id.name or "" if employee else "",
                "has_employee": bool(employee),
            },
            "kpi": {
                "to_approve": len(to_approve),
                "my_in_progress": my_counts.get("in_progress", 0)
                                  + appr_counts.get("in_progress", 0),
                "my_approved_30d": my_counts.get("approved_30d", 0)
                                   + appr_counts.get("approved_30d", 0),
                "my_rejected_30d": my_counts.get("rejected_30d", 0)
                                   + appr_counts.get("rejected_30d", 0),
                "leave_remaining": round(
                    sum(b["remaining"] for b in leave_balance), 2),
                "leave_pending": leave_pending,
            },
            "to_approve": to_approve,
            "my_requests": my_requests,
            "my_counts": my_counts,
            "leaves": leaves,
            "leave_balance": leave_balance,
            "pumui": pumui,
            "drill": {"xml_ids": xml_ids},
            "errors": errors,
            "server_time": _dt(now),
        }
