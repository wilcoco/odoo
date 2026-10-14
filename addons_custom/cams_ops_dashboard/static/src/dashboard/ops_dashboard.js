/** @odoo-module **/

import { Component, onMounted, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const POLL_MS = 60000;

export class OpsDashboard extends Component {
    static template = "cams_ops_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            data: null,
            loading: false,
            initialLoading: true,
            error: null,
            departmentId: false,
            lastUpdated: null,
        });
        onMounted(() => {
            this.refresh();
            this.pollId = setInterval(() => {
                if (!document.hidden) {
                    this.refresh();
                }
            }, POLL_MS);
        });
        onWillUnmount(() => clearInterval(this.pollId));
    }

    get data() {
        return this.state.data;
    }

    get counts() {
        return this.data?.counts || {};
    }

    get lastUpdatedLabel() {
        if (!this.state.lastUpdated) {
            return "";
        }
        return this.state.lastUpdated.toLocaleTimeString("ko-KR", { hour12: false });
    }

    async refresh() {
        if (this.state.loading) {
            return;
        }
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "cams.ops.dashboard",
                "get_dashboard_data",
                [],
                { limit: 20, department_id: this.state.departmentId || false }
            );
            this.state.error = null;
            this.state.lastUpdated = new Date();
        } catch (error) {
            this.state.error = "운영 대시보드 데이터를 불러오지 못했습니다.";
            if (this.state.initialLoading) {
                this.notification.add(this.state.error, { type: "danger" });
            }
        } finally {
            this.state.loading = false;
            this.state.initialLoading = false;
        }
    }

    async onDepartmentChange(event) {
        this.state.departmentId = Number(event.target.value) || false;
        await this.refresh();
    }

    openTask(task) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: task.label,
            res_model: "ops.task",
            res_id: task.id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openToday() {
        return this.action.doAction("cams_ops_process.action_ops_task_today");
    }

    openAll() {
        return this.action.doAction("cams_ops_process.action_ops_task_all");
    }

    async completeTask(task) {
        try {
            await this.orm.call("ops.task", "action_mark_done", [[task.id]]);
            this.notification.add("완료 보고했습니다.", { type: "success" });
            await this.refresh();
        } catch (error) {
            this.notification.add("업무를 완료 처리하지 못했습니다.", { type: "danger" });
        }
    }

    async approveTask(task) {
        try {
            await this.orm.call("ops.task", "action_approve", [[task.id]]);
            this.notification.add("업무를 승인했습니다.", { type: "success" });
            await this.refresh();
        } catch (error) {
            this.notification.add("업무를 승인하지 못했습니다.", { type: "danger" });
        }
    }
}

registry.category("actions").add("cams_ops_dashboard.dashboard", OpsDashboard);
