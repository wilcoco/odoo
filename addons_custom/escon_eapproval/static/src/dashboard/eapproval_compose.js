/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

/**
 * 품의서 작성 메인 화면.
 * 전자결재 유형 카드를 고르면 해당 유형의 새 요청 폼이 열린다.
 * (Odoo Approvals 기본 칸반 대신 에스콘 대시보드 디자인의 카드 그리드)
 */
export class EapprovalCompose extends Component {
    static template = "escon_eapproval.Compose";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, error: null });

        onWillStart(async () => {
            try {
                this.state.data = await this.orm.call(
                    "escon.eapproval.dashboard", "get_compose_data", [], {});
            } catch {
                this.state.error = "결재 유형을 불러오지 못했습니다.";
            }
        });
    }

    get data() {
        return this.state.data;
    }

    imgSrc(category) {
        return category.image ? `data:image/png;base64,${category.image}` : null;
    }

    async openCategory(category) {
        const act = await this.orm.call(
            "approval.category", "create_request", [category.id]);
        return this.action.doAction(act);
    }

    openXml(key) {
        const xmlId = this.state.data?.drill?.xml_ids?.[key];
        if (xmlId) {
            return this.action.doAction(xmlId);
        }
    }

    /** 청구서 연계 품의서 (pumui_approval) 새 문서 */
    newPumui() {
        if (!this.state.data?.pumui?.installed) {
            return;
        }
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "품의서 (청구 연계)",
            res_model: "pumui.request",
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("escon_eapproval.compose", EapprovalCompose);
