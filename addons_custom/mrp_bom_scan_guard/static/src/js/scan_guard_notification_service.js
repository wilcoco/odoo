/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";

export const scanGuardNotificationService = {
    dependencies: ["bus_service", "notification", "action"],

    start(env, { bus_service, notification, action }) {
        // Subscribe to the custom channel and listen to the matching notification type
        bus_service.addChannel("mrp_bom_scan_guard");
        bus_service.subscribe("scan_guard_notification", (payload) => {
            // Expected payload from server (mrp_bom_scan_guard/models/mrp_bom_scan_guard.py::_log_and_notify)
            // {
            //   log_id, workorder_id, workorder_name, production_id, production_name,
            //   result_state, message, scan_value
            // }
            const title = _t("BOM Scan Guard");
            const result = payload?.result_state;
            const type = ["wrong_operation", "not_in_bom", "not_found"].includes(result)
                ? "danger"
                : (result === "over_consumed" ? "warning" : "success");
            const sticky = true;

            const buttons = [{
                name: _t("Open Logs"),
                primary: false,
                onClick: () => {
                    if (payload?.workorder_id) {
                        action.doAction({
                            name: _t("Scan Guard Logs"),
                            type: "ir.actions.act_window",
                            res_model: "mrp.bom.scan.guard.log",
                            domain: [["workorder_id", "=", payload.workorder_id]],
                            views: [[false, "list"], [false, "form"]],
                            target: "current",
                        });
                    } else {
                        // Fallback to global logs action
                        action.doAction("mrp_bom_scan_guard.action_mrp_bom_scan_guard_logs");
                    }
                }
            }];

            // Strip HTML from server-provided message to avoid exposing tags in the popup
            const toText = (html) => {
                try {
                    const tmp = document.createElement("div");
                    tmp.innerHTML = html;
                    return (tmp.textContent || tmp.innerText || "").trim();
                } catch (_) {
                    return html;
                }
            };
            const rawMsg = payload?.message || _t("Mismatch detected while scanning components.");
            const msg = typeof rawMsg === "string" ? toText(rawMsg) : _t("Mismatch detected while scanning components.");
            notification.add(msg, { sticky, title, type, buttons });
        });
        bus_service.start();
    }
};

registry.category("services").add("scanGuardNotification", scanGuardNotificationService);
