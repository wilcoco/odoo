/** @odoo-module **/

import { registry } from "@web/core/registry";
import { EsconMainMenu } from "./mainmenu";

/**
 * Enterprise 홈 메뉴(앱 그리드) 전면 대체.
 *
 * web_enterprise의 home_menu 서비스는 start() 시점에 "menu" 액션(앱 그리드)을
 * 등록하고, 네비바 ⊞ 토글·hotkey·초기 진입이 전부 doAction("menu")를 호출한다.
 * 여기서는 home_menu 서비스에 의존하는 서비스를 하나 더 등록해,
 * home_menu가 시작된 "이후에" 확실하게 "menu" 액션을 ESCON 홈으로 덮어쓴다.
 * (asset 로드 순서와 무관하게 서비스 의존성 순서로 보장)
 *
 * Community 서버에는 home_menu 서비스가 없으므로 이 서비스는 시작되지 않고
 * 조용히 무시된다 — 그 경우는 navbar_patch가 앱 드롭다운을 홈 버튼으로 바꾼다.
 */
registry.category("services").add("escon_mainmenu.home_menu_override", {
    dependencies: ["home_menu"],
    start() {
        const actions = registry.category("actions");
        // 원본 Odoo 홈(앱 그리드)은 "Odoo 기본 홈 보기"에서 쓸 수 있게 보존
        if (actions.contains("menu")) {
            actions.add("escon_mainmenu.odoo_home", actions.get("menu"));
        }
        actions.add("menu", EsconMainMenu, { force: true });
    },
});
