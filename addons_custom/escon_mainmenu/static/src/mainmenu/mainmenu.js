/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

/**
 * 기본 카테고리 구성 (사용자 설정이 없을 때의 기본값).
 * 여기 적힌 메뉴가 전부 보이는 게 아니라, 현재 DB에 설치돼 있고
 * 사용자가 접근권한을 가진 메뉴만 런타임에 살아남는다 (menu 서비스 기준).
 */
const DEFAULT_CATEGORIES = [
    {
        key: "inbound",
        title: "입고 관리",
        icon: "fa-truck",
        color: "#2563eb",
        items: [
            { xmlid: "purchase.menu_purchase_form_action", label: "구매 발주" },
            { xmlid: "purchase.menu_purchase_rfq", label: "견적 요청(RFQ)" },
            { xmlid: "stock.in_picking", label: "입고 작업" },
            { xmlid: "iatf_incoming_inspection.menu_iatf_incoming_inspections", label: "수입검사" },
            { xmlid: "supplier_portal_purchase.menu_outsource_purchase_orders", label: "외주 발주 현황" },
            { xmlid: "supplier_portal_purchase.menu_supplier_asn", label: "납품 예정(ASN)" },
        ],
    },
    {
        key: "production",
        title: "생산 관리",
        icon: "fa-industry",
        color: "#d97706",
        items: [
            { xmlid: "mrp.menu_mrp_production_action", label: "제조 오더" },
            { xmlid: "mrp.menu_mrp_workorder_todo", label: "작업 지시" },
            { xmlid: "injection_planning.menu_planning_run", label: "사출 생산계획" },
            { xmlid: "injection_planning.menu_daily_summary", label: "일별 분석" },
            { xmlid: "production_planning.menu_production_demand", label: "생산 수요" },
            { xmlid: "mrp.menu_mrp_bom_form_action", label: "BOM (자재명세서)" },
        ],
    },
    {
        key: "stock",
        title: "재고 관리",
        icon: "fa-cubes",
        color: "#059669",
        items: [
            { xmlid: "stock.menu_stock_root", label: "재고 개요" },
            { xmlid: "stock.menu_action_inventory_tree", label: "재고 현황/조정" },
            { xmlid: "stock.int_picking", label: "내부 이동" },
            { xmlid: "stock_account.menu_valuation", label: "재고 평가" },
        ],
    },
    {
        key: "outbound",
        title: "출고/판매 관리",
        icon: "fa-paper-plane",
        color: "#7c3aed",
        items: [
            { xmlid: "sale.menu_sale_order", label: "판매 주문" },
            { xmlid: "sale.menu_sale_quotations", label: "견적서" },
            { xmlid: "stock.out_picking", label: "출고 작업" },
            { xmlid: "iatf_shipping_inspection.menu_iatf_shipping_inspections", label: "출하검사" },
            { xmlid: "sale.menu_sale_order_invoice", label: "청구 대기 주문" },
        ],
    },
    {
        key: "accounting",
        title: "회계 관리",
        icon: "fa-calculator",
        color: "#dc2626",
        items: [
            { xmlid: "account.menu_board_journal_1", label: "회계 대시보드" },
            { xmlid: "account.menu_action_move_out_invoice_type", label: "고객 청구서" },
            { xmlid: "account.menu_action_move_in_invoice_type", label: "공급자 청구서" },
            { xmlid: "account.menu_action_move_journal_line_form", label: "전표" },
            { xmlid: "account_kr_reports.menu_kr_cash_status", label: "자금현황" },
            { xmlid: "account_kr_reports.menu_kr_daily_sheet", label: "일계표" },
        ],
    },
    {
        key: "hr",
        title: "인사 관리",
        icon: "fa-users",
        color: "#0891b2",
        items: [
            { xmlid: "hr.menu_hr_employee_user", label: "직원" },
            { xmlid: "hr.menu_hr_department_kanban", label: "부서" },
            { xmlid: "hr_attendance.menu_hr_attendance_view_attendances", label: "근태 현황" },
            { xmlid: "hr_payroll_kr.menu_kr_attendance_sheet", label: "월 근태 집계" },
            { xmlid: "hr_payroll_kr.menu_kr_insurance_notice", label: "4대보험 고지액" },
            { xmlid: "hr_payroll_kr.menu_kr_severance", label: "퇴직금 계산서" },
        ],
    },
];

// 아이콘 선택 그리드 (10 x 5)
const ICON_CHOICES = [
    "fa-truck", "fa-industry", "fa-cubes", "fa-paper-plane", "fa-calculator",
    "fa-users", "fa-folder-open", "fa-wrench", "fa-line-chart", "fa-shopping-cart",
    "fa-clipboard", "fa-cogs", "fa-flask", "fa-check-square-o", "fa-book",
    "fa-archive", "fa-bar-chart", "fa-bell", "fa-bolt", "fa-briefcase",
    "fa-building", "fa-bullseye", "fa-calendar", "fa-camera", "fa-car",
    "fa-certificate", "fa-clock-o", "fa-cloud", "fa-code", "fa-comments",
    "fa-credit-card", "fa-database", "fa-desktop", "fa-envelope", "fa-exchange",
    "fa-file-text-o", "fa-filter", "fa-fire", "fa-flag", "fa-gavel",
    "fa-gift", "fa-globe", "fa-heart", "fa-home", "fa-inbox",
    "fa-key", "fa-leaf", "fa-lightbulb-o", "fa-lock", "fa-map-marker",
];

const PROFILE_MODEL = "escon.mainmenu.profile";

function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj));
}

/** 저장된 설정과 기본값을 병합해 완전한 config 를 만든다. */
function normalizeConfig(raw) {
    const config = {
        favorites: [],
        categories: deepClone(DEFAULT_CATEGORIES),
        appOrderMode: "odoo", // "odoo": Odoo 홈 순서 연동, "custom": 직접 지정
        appOrder: [],
        showAllApps: true,
    };
    if (raw && typeof raw === "object") {
        if (Array.isArray(raw.favorites)) {
            config.favorites = raw.favorites;
        }
        if (Array.isArray(raw.categories) && raw.categories.length) {
            config.categories = raw.categories;
        }
        if (raw.appOrderMode === "custom") {
            config.appOrderMode = "custom";
        }
        if (Array.isArray(raw.appOrder)) {
            config.appOrder = raw.appOrder;
        }
        if (typeof raw.showAllApps === "boolean") {
            config.showAllApps = raw.showAllApps;
        }
    }
    return config;
}

/** 저장 직전 편집용 임시 키(_addSel 등)를 걷어낸다. */
function sanitizeConfig(config) {
    return {
        favorites: [...config.favorites],
        categories: config.categories.map((c) => ({
            key: c.key,
            title: c.title,
            icon: c.icon,
            color: c.color,
            items: c.items.map((i) => ({ xmlid: i.xmlid, label: i.label })),
        })),
        appOrderMode: config.appOrderMode,
        appOrder: [...config.appOrder],
        showAllApps: config.showAllApps,
    };
}

export class EsconMainMenu extends Component {
    static template = "escon_mainmenu.Home";
    static props = ["*"];

    setup() {
        this.menuService = useService("menu");
        this.actionService = useService("action");
        this.orm = useService("orm");
        this.iconChoices = ICON_CHOICES;

        this.state = useState({
            view: "home", // "home" | "settings"
            config: normalizeConfig(false),
            draft: null, // 설정 화면 편집본
            settingsSection: "favs", // 좌측 네비 활성 항목
            iconPickerFor: null, // 아이콘 그리드가 열린 카테고리 key
        });
        this._drag = null; // 드래그 정렬 진행 상태

        this.menuByXmlid = {};
        for (const menu of this.menuService.getAll()) {
            if (menu.xmlid) {
                this.menuByXmlid[menu.xmlid] = menu;
            }
        }

        // 홈(자기 자신) 제외한 모든 앱
        this.allApps = this.menuService
            .getApps()
            .filter(
                (app) =>
                    app.actionID &&
                    app.xmlid !== "escon_mainmenu.menu_escon_mainmenu_root"
            );

        // 설정 화면의 "메뉴 추가" 선택지: 액션이 있는 모든 메뉴 (앱 이름 / 메뉴 이름)
        this.allMenuChoices = this.menuService
            .getAll()
            .filter((m) => m.xmlid && m.actionID && m.id !== "root")
            .map((m) => {
                const app = this.menuService.getMenu(m.appID);
                const appName = app && app.id !== m.id ? app.name + " / " : "";
                return { xmlid: m.xmlid, label: appName + m.name };
            })
            .sort((a, b) => a.label.localeCompare(b.label, "ko"));

        this.today = new Date().toLocaleDateString("ko-KR", {
            year: "numeric",
            month: "long",
            day: "numeric",
            weekday: "long",
        });

        onWillStart(async () => {
            const raw = await this.orm.call(PROFILE_MODEL, "get_my_config", []);
            this.state.config = normalizeConfig(raw);
        });
    }

    // ─────────────── 파생 데이터 ───────────────

    /** Odoo(Enterprise) 홈에서 사용자가 정렬한 앱 순서 (없으면 null) */
    get odooHomeOrder() {
        try {
            return JSON.parse(user.settings?.homemenu_config || "null");
        } catch {
            return null;
        }
    }

    _orderApps(config) {
        const apps = this.allApps;
        const order =
            config.appOrderMode === "custom" && config.appOrder.length
                ? config.appOrder
                : this.odooHomeOrder;
        if (!order || !order.length) {
            return [...apps];
        }
        const idx = new Map(order.map((xmlid, i) => [xmlid, i]));
        return [...apps].sort((a, b) => {
            const ai = idx.has(a.xmlid) ? idx.get(a.xmlid) : Infinity;
            const bi = idx.has(b.xmlid) ? idx.get(b.xmlid) : Infinity;
            if (ai === Infinity && bi === Infinity) {
                return apps.indexOf(a) - apps.indexOf(b);
            }
            return ai - bi;
        });
    }

    get orderedApps() {
        return this._orderApps(this.state.config);
    }

    get favoriteApps() {
        return this.state.config.favorites
            .map((xmlid) => this.allApps.find((a) => a.xmlid === xmlid))
            .filter(Boolean);
    }

    /** 설치·권한 필터를 통과한 카테고리 (홈 화면 렌더용) */
    get categories() {
        return this.state.config.categories.map((cat) => ({
            ...cat,
            items: cat.items
                .map((item) => ({ ...item, menu: this.menuByXmlid[item.xmlid] }))
                .filter((item) => item.menu && item.menu.actionID),
        }));
    }

    get hasOdooHome() {
        return registry.category("actions").contains("escon_mainmenu.odoo_home");
    }

    get userLogin() {
        return user.login || "";
    }

    /** 설정 화면: 편집본 기준 앱 순서 목록 */
    get draftOrderedApps() {
        return this._orderApps(this.state.draft);
    }

    // ─────────────── 홈 동작 ───────────────

    openMenu(menu) {
        this.menuService.selectMenu(menu);
    }

    onHeadClick(cat) {
        if (cat.items.length) {
            this.openMenu(cat.items[0].menu);
        }
    }

    toggleAllApps() {
        this.state.config.showAllApps = !this.state.config.showAllApps;
        this._persist();
    }

    openOdooHome() {
        this.actionService.doAction("escon_mainmenu.odoo_home");
    }

    async openAccountSettings() {
        const actionDescription = await this.orm.call("res.users", "action_get");
        actionDescription.res_id = user.userId;
        this.actionService.doAction(actionDescription);
    }

    _persist() {
        return this.orm.call(PROFILE_MODEL, "save_my_config", [
            sanitizeConfig(this.state.config),
        ]);
    }

    // ─────────────── 설정 화면 ───────────────

    openSettings() {
        this.state.draft = deepClone(sanitizeConfig(this.state.config));
        this.state.view = "settings";
    }

    cancelSettings() {
        this.state.draft = null;
        this.state.view = "home";
    }

    async saveSettings() {
        this.state.config = normalizeConfig(deepClone(sanitizeConfig(this.state.draft)));
        this.state.draft = null;
        this.state.view = "home";
        await this._persist();
    }

    async resetSettings() {
        await this.orm.call(PROFILE_MODEL, "reset_my_config", []);
        this.state.config = normalizeConfig(false);
        this.state.draft = null;
        this.state.view = "home";
    }

    // 즐겨찾기
    isFavorite(xmlid) {
        return this.state.draft.favorites.includes(xmlid);
    }

    toggleFavorite(xmlid) {
        const favs = this.state.draft.favorites;
        const i = favs.indexOf(xmlid);
        if (i >= 0) {
            favs.splice(i, 1);
        } else {
            favs.push(xmlid);
        }
    }

    // 좌측 네비 → 해당 설정 섹션으로 스크롤
    scrollToSection(section) {
        this.state.settingsSection = section;
        const el = document.getElementById("emm-sec-" + section);
        if (el) {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
        }
    }

    // 아이콘 그리드 피커
    toggleIconPicker(catKey) {
        this.state.iconPickerFor = this.state.iconPickerFor === catKey ? null : catKey;
    }

    pickIcon(cat, icon) {
        cat.icon = icon;
        this.state.iconPickerFor = null;
    }

    // ─── 드래그 정렬 (핸들을 잡고 이동) ───
    // 핸들에서 dragstart → 같은 목록의 행 위를 지나갈 때마다 실시간 재배치

    onHandleDragStart(ev, type, index, catIndex = null) {
        this._drag = { type, index, catIndex };
        ev.dataTransfer.effectAllowed = "move";
        ev.dataTransfer.setData("text/plain", "emm-drag");
    }

    onRowDragOver(ev, type, index, catIndex = null) {
        const d = this._drag;
        if (!d || d.type !== type || d.catIndex !== catIndex) {
            return;
        }
        ev.preventDefault();
        if (d.index === index) {
            return;
        }
        if (type === "cat") {
            this._moveInList(this.state.draft.categories, d.index, index);
        } else if (type === "item") {
            this._moveInList(this.state.draft.categories[catIndex].items, d.index, index);
        } else if (type === "app") {
            const list = this.draftOrderedApps.map((a) => a.xmlid);
            this._moveInList(list, d.index, index);
            this.state.draft.appOrder = list;
            this.state.draft.appOrderMode = "custom";
        }
        d.index = index;
    }

    onRowDrop(ev) {
        ev.preventDefault();
        this._drag = null;
    }

    onDragEnd() {
        this._drag = null;
    }

    _moveInList(list, from, to) {
        const [moved] = list.splice(from, 1);
        list.splice(to, 0, moved);
    }

    // 카테고리
    addCategory() {
        this.state.draft.categories.push({
            key: "cat_" + Date.now(),
            title: "새 그룹",
            icon: "fa-folder-open",
            color: "#475569",
            items: [],
        });
    }

    removeCategory(ci) {
        this.state.draft.categories.splice(ci, 1);
    }

    // 카테고리 항목
    onAddItem(cat, ev) {
        const xmlid = ev.target.value;
        ev.target.value = "";
        if (!xmlid || cat.items.some((i) => i.xmlid === xmlid)) {
            return;
        }
        const menu = this.menuByXmlid[xmlid];
        cat.items.push({ xmlid, label: (menu && menu.name) || xmlid });
    }

    removeItem(cat, ii) {
        cat.items.splice(ii, 1);
    }

    /** 편집본에서 해당 xmlid 메뉴가 이 DB에 실제로 살아있는지 */
    isMenuAlive(xmlid) {
        const m = this.menuByXmlid[xmlid];
        return Boolean(m && m.actionID);
    }

    // 앱 순서
    setAppOrderMode(mode) {
        this.state.draft.appOrderMode = mode;
        if (mode === "custom" && !this.state.draft.appOrder.length) {
            this.state.draft.appOrder = this.draftOrderedApps.map((a) => a.xmlid);
        }
    }

}

registry.category("actions").add("escon_mainmenu.home", EsconMainMenu);
