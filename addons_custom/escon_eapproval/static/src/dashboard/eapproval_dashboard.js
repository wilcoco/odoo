/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime } from "@web/core/l10n/dates";

const POLL_MS = 60000;

const APPROVAL_STATE = {
    draft: { label: "초안", cls: "muted" },
    in_progress: { label: "결재 중", cls: "running" },
    approved: { label: "승인", cls: "ok" },
    rejected: { label: "반려", cls: "danger" },
};

const LEAVE_STATE = {
    draft: { label: "저장됨", cls: "muted" },
    confirm: { label: "승인 대기", cls: "warn" },
    validate1: { label: "1차 승인", cls: "running" },
    validate: { label: "승인", cls: "ok" },
    refuse: { label: "거부", cls: "danger" },
    cancel: { label: "취소", cls: "muted" },
};

const BILLING_STATE = {
    none: { label: "미청구", cls: "muted" },
    partial: { label: "부분 청구", cls: "warn" },
    invoiced: { label: "청구 완료", cls: "running" },
    paid: { label: "지급 완료", cls: "ok" },
};

/**
 * 에스콘 전자결재 대시보드.
 * 데이터는 `escon.eapproval.dashboard.get_dashboard_data` 단일 RPC 로 받고
 * 60초마다 갱신한다. (디자인·구조는 injection_worksite 대시보드 차용)
 */
export class EapprovalDashboard extends Component {
    static template = "escon_eapproval.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");

        this.state = useState({
            data: null,
            loading: false,
            initialLoading: true,
            lastUpdated: null,
            error: null,
        });

        onMounted(() => {
            this.refresh();
            this._pollId = setInterval(() => {
                if (!document.hidden) {
                    this.refresh();
                }
            }, POLL_MS);
            this._visHandler = () => {
                if (!document.hidden) {
                    this.refresh();
                }
            };
            document.addEventListener("visibilitychange", this._visHandler);
        });

        onWillUnmount(() => {
            if (this._pollId) {
                clearInterval(this._pollId);
            }
            if (this._visHandler) {
                document.removeEventListener("visibilitychange", this._visHandler);
            }
        });
    }

    async refresh() {
        if (this.state.loading) {
            this._pending = true;
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "escon.eapproval.dashboard", "get_dashboard_data", [], {});
            this.state.data = data;
            this.state.error = null;
            this.state.lastUpdated = new Date();
        } catch (error) {
            this.state.error = "대시보드 데이터를 불러오지 못했습니다.";
            if (this.state.initialLoading) {
                this.notification.add(this.state.error, { type: "danger" });
            }
            throw error;
        } finally {
            this.state.loading = false;
            this.state.initialLoading = false;
            if (this._pending) {
                this._pending = false;
                this.refresh();
            }
        }
    }

    // ------------------------------------------------------------------
    // 파생 값
    // ------------------------------------------------------------------
    get data() {
        return this.state.data;
    }

    get kpi() {
        return this.state.data?.kpi || {};
    }

    get pumui() {
        return this.state.data?.pumui || { installed: false };
    }

    get greeting() {
        const u = this.state.data?.user;
        if (!u) {
            return "";
        }
        const org = [u.department, u.grade || u.job].filter(Boolean).join(" · ");
        return org ? `${u.name} (${org})` : u.name;
    }

    get lastUpdatedLabel() {
        const d = this.state.lastUpdated;
        if (!d) {
            return "";
        }
        const hh = String(d.getHours()).padStart(2, "0");
        const mm = String(d.getMinutes()).padStart(2, "0");
        const ss = String(d.getSeconds()).padStart(2, "0");
        return `${hh}:${mm}:${ss}`;
    }

    // ------------------------------------------------------------------
    // 표시 헬퍼
    // ------------------------------------------------------------------
    display(value, fallback = "-") {
        if (value === false || value === undefined || value === null || value === "") {
            return fallback;
        }
        return value;
    }

    num(value, digits = 0) {
        const n = Number(value || 0);
        return n.toLocaleString(undefined, {
            maximumFractionDigits: digits,
            minimumFractionDigits: 0,
        });
    }

    fmtDt(value, format = "MM-dd HH:mm") {
        if (!value) {
            return "-";
        }
        try {
            return deserializeDateTime(value).toFormat(format);
        } catch {
            return value;
        }
    }

    barStyle(value) {
        const safe = Math.max(0, Math.min(100, Number(value || 0)));
        return `width: ${safe}%`;
    }

    approvalState(state) {
        return APPROVAL_STATE[state] || { label: state || "-", cls: "muted" };
    }

    leaveState(state) {
        return LEAVE_STATE[state] || { label: state || "-", cls: "muted" };
    }

    billingState(state) {
        return BILLING_STATE[state] || { label: state || "-", cls: "muted" };
    }

    usagePct(balance) {
        if (!balance.allocated) {
            return 0;
        }
        return Math.min(100, (balance.used / balance.allocated) * 100);
    }

    // ------------------------------------------------------------------
    // 액션 (드릴다운)
    // ------------------------------------------------------------------
    openDoc(row) {
        if (!row.doc_ok) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: row.doc_name || "",
            res_model: row.doc_model,
            res_id: row.doc_id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openRecord(resModel, resId, name) {
        if (!resId) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: name || "",
            res_model: resModel,
            res_id: resId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openXml(key) {
        const xmlId = this.state.data?.drill?.xml_ids?.[key];
        if (xmlId) {
            return this.action.doAction(xmlId);
        }
    }

    hasXml(key) {
        return Boolean(this.state.data?.drill?.xml_ids?.[key]);
    }

    /** 품의서 새로 작성 (pumui_approval 설치 시에만 버튼 노출) */
    newPumui() {
        if (!this.pumui.installed) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "품의서 작성",
            res_model: "pumui.request",
            views: [[false, "form"]],
            target: "current",
        });
    }

    /** 휴가 신청 다이얼로그 (hr_holidays 표준 폼) */
    newLeave() {
        return this.openXml("leave_dashboard");
    }
}

registry.category("actions").add("escon_eapproval.dashboard", EapprovalDashboard);
