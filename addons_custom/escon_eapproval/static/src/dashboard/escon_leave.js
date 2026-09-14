/** @odoo-module **/

import { onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { listView } from "@web/views/list/list_view";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";

/**
 * 에스콘 휴가 목록 (js_class="escon_leave_list")
 *
 * "휴가 신청" 메뉴(action_escon_leave_open)는 이 목록을
 * context {'escon_open_leave_dialog': 1} 로 연다 — 목록이 마운트된 직후
 * 휴가 신청 폼을 팝업(다이얼로그)으로 한 번 띄운다 (페이지 이동 없음).
 * 다이얼로그는 액션 스택과 무관한 dialog 서비스로 열어 액션 전환 정리에
 * 닫히지 않게 하고, 플래그는 한 번 쓰고 지워 폼 복귀 시 재팝업을 막는다.
 */
export class EsconLeaveListController extends listView.Controller {
    setup() {
        super.setup();
        this.dialogService = useService("dialog");
        this.ormService = useService("orm");
        onMounted(() => {
            const context = this.props.context || {};
            if (context.escon_open_leave_dialog) {
                delete context.escon_open_leave_dialog;
                this.openLeaveRequestDialog();
            }
        });
    }

    async openLeaveRequestDialog() {
        const [, viewId] = await this.ormService.call(
            "ir.model.data", "check_object_reference",
            ["escon_eapproval", "view_escon_leave_form"]);
        this.dialogService.add(FormViewDialog, {
            resModel: "hr.leave",
            viewId,
            title: "휴가 신청",
            context: {},
            onRecordSaved: () => this.model.load(),
        });
    }
}

registry.category("views").add("escon_leave_list", {
    ...listView,
    Controller: EsconLeaveListController,
});
