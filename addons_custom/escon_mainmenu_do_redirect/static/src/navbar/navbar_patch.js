/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

/**
 * 네비바 왼쪽 앱 버튼(그리드 아이콘): 앱 드롭다운 대신 ESCON 홈 화면으로 이동.
 */
patch(NavBar.prototype, {
    onEsconHomeClick() {
        const home = this.menuService
            .getApps()
            .find((app) => app.xmlid === "escon_mainmenu.menu_escon_mainmenu_root");
        if (home) {
            this.menuService.selectMenu(home);
        } else {
            // 홈 메뉴가 접근 불가한 경우 액션 직접 호출 (안전망)
            this.actionService.doAction("escon_mainmenu.action_escon_mainmenu", {
                clearBreadcrumbs: true,
            });
        }
    },
});
