/** @odoo-module **/
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("work_environment_sheet_defaults_r226", {
    steps: () => [
        { trigger: ".o_list_button_add", run: "click" },
        { trigger: '.o_field_widget[name="name"] input', run: `edit ${window.__r226SheetName}` },
        { trigger: '.o_field_widget[name="quality_purpose"] select', run() {
            const value = document.querySelector('.o_field_widget[name="quality_purpose"] select').value;
            if (JSON.parse(value) !== "general") throw new Error("R226: form must default to general");
        } },
        { trigger: ".o_form_button_save", run: "click" },
        { trigger: ".o_form_status_indicator_buttons.invisible:not(:visible)", run() {
            if (document.querySelector('.o_error_dialog, .o_field_invalid')) {
                throw new Error("R226: ordinary worker could not save general sheet");
            }
            const name = document.querySelector('.o_field_widget[name="name"] input');
            if (!name || name.value !== window.__r226SheetName) throw new Error("R226: saved sheet missing");
        } },
    ],
});
