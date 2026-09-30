/** @odoo-module **/
/* [R136] 4단 캐스케이드 클릭 시나리오: 회사 전체 → 생산 → 사출 계획 → 문서 폼.
 * 실행: tests/test_factory_flow_tour.py (HttpCase.start_tour) — 슬롯 배정 후. 사출 계획(injection.planning.run) 이 최소 1건 있어야 한다. */
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("cams_ops_dashboard_factory_flow_tour", {
    url: "/odoo/action-cams_ops_dashboard.action_factory_flow",
    steps: () => [
        {
            content: "L0 회사 전체 리본이 뜬다",
            trigger: ".ff .ff-ribbon .ff-area[data-pid='CO.PROD']",
            run: "click",
        },
        {
            content: "L1 생산 영역의 프로세스 카드 — 사출 계획(연결됨) 클릭",
            trigger: ".ff .ff-cards .ff-process[data-pid='CO.PROD.INJ_PLAN']",
            run: "click",
        },
        {
            content: "L2 세부 내역 표에 문서 행이 있고 breadcrumb 이 3단이다",
            trigger: ".ff .ff-crumbs .ff-crumb[data-level='2'].ff-crumb--current",
            run: () => {},
        },
        {
            content: "첫 문서의 '원본 열기'",
            trigger: ".ff .ff-table .ff-row:first-child .ff-row__open",
            run: "click",
        },
        {
            content: "L3 Odoo 원본 폼으로 이동했다",
            trigger: ".o_form_view",
            run: () => {},
        },
    ],
});
