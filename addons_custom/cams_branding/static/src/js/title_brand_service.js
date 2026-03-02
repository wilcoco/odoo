/** @odoo-module **/

import { registry } from "@web/core/registry";

const BRAND = "ESCON ERP";

export const camsBrandTitleService = {
    dependencies: ["title"],
    start(env, { title }) {
        title.setParts({ brand: BRAND });
    },
};

registry.category("services").add("cams_brand_title", camsBrandTitleService);
