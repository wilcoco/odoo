/** @odoo-module **/
/*
 * [R136] 회사 운영 흐름 — 4단 캐스케이드(회사 전체 → 영역 → 프로세스 → 문서) client action.
 * 설계: docs/tasks/R136-CASCADE-DESIGN.md §1·§2·§4 (테스트 세션 구현, 2026-09-14).
 * 서버 호출은 `cams.factory.flow` 의 get_map / get_node / get_action 세 메서드뿐이다(rpc 직접 호출·sudo 없음).
 * 표시 규칙(§2): 퍼센트 없음 · 연결 상태 4종 구분 · late 별도 배지 · restricted 는 숫자·제목 없음 · 건수는 서버 total 그대로.
 */
import { Component, onMounted, onWillStart, onWillUnmount, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const POLL_MS = 60000; // 기존 ops_dashboard 와 같은 주기, 숨김 탭에서는 정지
const PAGE = 20;
const HASH_PREFIX = "#ff";

export const LINK_LABEL = {
    linked: "연결",
    not_wired: "어댑터 없음",
    not_installed: "모듈 없음",
    restricted: "권한 없음",
    aggregate: "하위 합계",
};
export const STATE_LABEL = {
    wait: "대기",
    progress: "진행",
    done: "완료",
    hold: "보류",
    cancel: "취소",
    unknown: "미확인",
};

/** 상태 건수 표시용: 서버 counts 를 그대로 옮긴다(재계산·퍼센트 없음). */
export function countPairs(counts) {
    if (!counts) {
        return [];
    }
    return ["wait", "progress", "hold", "done"].map((k) => ({ key: k, label: STATE_LABEL[k], value: counts[k] || 0 }));
}

/** 하위 연결 상태 분포(child_links) → 배지 목록. 0 인 항목은 표시하지 않는다. */
export function linkBadges(childLinks) {
    const out = [];
    for (const key of ["linked", "not_wired", "not_installed", "restricted"]) {
        const n = (childLinks || {})[key] || 0;
        if (n) {
            out.push({ key, label: LINK_LABEL[key], value: n });
        }
    }
    return out;
}

function parseHash(hash) {
    if (!hash || !hash.startsWith(HASH_PREFIX)) {
        return [];
    }
    return hash
        .slice(HASH_PREFIX.length)
        .split("/")
        .filter((p) => p);
}

/* ───────────── L0: 영역 리본 ───────────── */
export class AreaRibbon extends Component {
    static template = "cams_ops_dashboard.FactoryFlow.AreaRibbon";
    static props = { areas: Array, selected: { type: String, optional: true }, onSelect: Function };
    pairs(area) {
        return countPairs(area.status?.counts);
    }
    badges(area) {
        return linkBadges(area.status?.child_links);
    }
    restrictedNote(area) {
        const n = area.status?.child_links?.restricted || 0;
        return n ? `권한 제한 ${n} 노드 제외` : "";
    }
}

/* ───────────── L1: 프로세스 카드 ───────────── */
export class ProcessCards extends Component {
    static template = "cams_ops_dashboard.FactoryFlow.ProcessCards";
    static props = { processes: Array, edges: Array, selected: { type: String, optional: true }, onSelect: Function };
    pairs(p) {
        return countPairs(p.status?.counts);
    }
    link(p) {
        return p.status?.link || "not_wired";
    }
    linkLabel(p) {
        return LINK_LABEL[this.link(p)] || this.link(p);
    }
    /** 카드 사이 관계선: 맵 edge 만(FK 없는 선 없음). 이 영역 안의 프로세스끼리 잇는 edge 를 leaf 의 L2 조상으로 접는다. */
    get relations() {
        const ids = new Set(this.props.processes.map((p) => p.process_id));
        const toL2 = (leafId) => {
            const parts = leafId.split(".");
            return parts.length >= 3 ? parts.slice(0, 3).join(".") : leafId;
        };
        const seen = new Map();
        for (const e of this.props.edges || []) {
            const a = toL2(e.source_id);
            const b = toL2(e.target_id);
            if (a === b || !ids.has(a) || !ids.has(b)) {
                continue;
            }
            const key = `${a}>${b}`;
            const cur = seen.get(key) || { from: a, to: b, count: 0, kinds: new Set() };
            cur.count += 1;
            cur.kinds.add(e.kind);
            seen.set(key, cur);
        }
        return [...seen.values()].map((r) => ({ ...r, kinds: [...r.kinds].join("·") }));
    }
    nameOf(pid) {
        const p = this.props.processes.find((x) => x.process_id === pid);
        return p ? p.name : pid;
    }
}

/* ───────────── L2: 프로세스 상세(하위 트리 + 세부 내역 표) ───────────── */
export class NodeDetail extends Component {
    static template = "cams_ops_dashboard.FactoryFlow.NodeDetail";
    static props = {
        detail: { type: Object, optional: true },
        subtree: Array,
        page: Number,
        onPage: Function,
        onOpen: Function,
        onOpenList: Function,
        onSelectChild: Function,
    };
    get status() {
        return this.props.detail?.status || {};
    }
    get link() {
        return this.status.link || "not_wired";
    }
    get linkLabel() {
        return LINK_LABEL[this.link] || this.link;
    }
    get pairs() {
        return countPairs(this.status.counts);
    }
    get total() {
        // 건수는 서버 total 그대로(클라이언트 재계산 없음)
        return this.status.total ?? 0;
    }
    get pageCount() {
        return Math.max(1, Math.ceil(this.total / PAGE));
    }
    stateLabel(row) {
        return STATE_LABEL[row.state] || row.state;
    }
    childLink(n) {
        return n.status?.link || "not_wired";
    }
    childLinkLabel(n) {
        return LINK_LABEL[this.childLink(n)] || this.childLink(n);
    }
}

/* ───────────── 루트 ───────────── */
export class FactoryFlow extends Component {
    static template = "cams_ops_dashboard.FactoryFlow";
    static components = { AreaRibbon, ProcessCards, NodeDetail };
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            level: 0, // 0 회사 전체 · 1 영역 · 2 프로세스
            path: [], // [areaId, processId]
            map: null, // get_map(level=2)
            catalog: null, // get_map(level=4) — L2 하위 트리 이름·상태(지연 적재)
            node: null, // get_node(...)
            page: 0,
            filters: { date_from: "", date_to: "" },
            loading: false,
            initialLoading: true,
            error: null,
            lastUpdated: null,
        });
        this.onHashChange = () => this.applyHash(window.location.hash);
        onWillStart(async () => {
            const initial = parseHash(window.location.hash);
            await this.loadMap();
            if (initial.length) {
                await this.navigateTo(initial, { pushHash: false });
            }
        });
        onMounted(() => {
            window.addEventListener("hashchange", this.onHashChange);
            this.pollId = setInterval(() => {
                if (!document.hidden) {
                    this.refresh();
                }
            }, POLL_MS);
        });
        onWillUnmount(() => {
            window.removeEventListener("hashchange", this.onHashChange);
            clearInterval(this.pollId);
        });
    }

    /* ── 파생 ── */
    get map() {
        return this.state.map;
    }
    get areas() {
        if (!this.map) {
            return [];
        }
        return this.map.nodes.filter((n) => n.level === 1).sort((a, b) => (a.layout_order ?? 0) - (b.layout_order ?? 0));
    }
    get processes() {
        if (!this.map || !this.state.path[0]) {
            return [];
        }
        return this.map.nodes
            .filter((n) => n.level === 2 && n.parent_id === this.state.path[0])
            .sort((a, b) => (a.layout_order ?? 0) - (b.layout_order ?? 0));
    }
    get subtree() {
        const pid = this.state.path[1];
        if (!pid || !this.state.catalog) {
            return [];
        }
        return this.state.catalog.nodes
            .filter((n) => n.process_id !== pid && n.process_id.startsWith(pid + "."))
            .sort((a, b) => (a.layout_order ?? 0) - (b.layout_order ?? 0));
    }
    get crumbs() {
        const out = [{ pid: null, name: "회사 전체", level: 0 }];
        const names = new Map((this.map?.nodes || []).map((n) => [n.process_id, n.name]));
        this.state.path.forEach((pid, i) => out.push({ pid, name: names.get(pid) || pid, level: i + 1 }));
        return out;
    }
    get asOfLabel() {
        return this.map?.as_of ? `기준 ${this.map.as_of}` : "";
    }
    get lastUpdatedLabel() {
        return this.state.lastUpdated ? this.state.lastUpdated.toLocaleTimeString("ko-KR", { hour12: false }) : "";
    }
    get companyLabel() {
        const ids = this.map?.company_ids || [];
        return ids.length ? `회사 ${ids.length}개 범위` : "";
    }
    get filtersArg() {
        const f = {};
        if (this.state.filters.date_from) {
            f.date_from = this.state.filters.date_from;
        }
        if (this.state.filters.date_to) {
            f.date_to = this.state.filters.date_to;
        }
        return f;
    }

    /* ── 서버 호출(3 메서드만) ── */
    async loadMap() {
        this.state.loading = true;
        try {
            this.state.map = await this.orm.call("cams.factory.flow", "get_map", [2, this.filtersArg]);
            this.state.error = null;
            this.state.lastUpdated = new Date();
        } catch (error) {
            this.state.error = "회사 운영 흐름 데이터를 불러오지 못했습니다.";
            if (this.state.initialLoading) {
                this.notification.add(this.state.error, { type: "danger" });
            }
        } finally {
            this.state.loading = false;
            this.state.initialLoading = false;
        }
    }
    async loadCatalog() {
        if (this.state.catalog) {
            return;
        }
        try {
            this.state.catalog = await this.orm.call("cams.factory.flow", "get_map", [4, this.filtersArg]);
        } catch (error) {
            this.state.error = "하위 업무 목록을 불러오지 못했습니다.";
        }
    }
    async loadNode() {
        const pid = this.state.path[1];
        if (!pid) {
            this.state.node = null;
            return;
        }
        this.state.loading = true;
        try {
            this.state.node = await this.orm.call("cams.factory.flow", "get_node", [pid, this.filtersArg, PAGE, this.state.page * PAGE]);
            this.state.error = null;
            this.state.lastUpdated = new Date();
        } catch (error) {
            this.state.error = "세부 내역을 불러오지 못했습니다.";
        } finally {
            this.state.loading = false;
        }
    }
    async refresh() {
        if (this.state.loading) {
            return;
        }
        await this.loadMap();
        if (this.state.level === 2) {
            await this.loadNode();
        }
    }

    /* ── 탐색 ── */
    writeHash() {
        const hash = this.state.path.length ? `${HASH_PREFIX}/${this.state.path.join("/")}` : HASH_PREFIX;
        if (window.location.hash !== hash) {
            window.location.hash = hash;
        }
    }
    async applyHash(hash) {
        const parts = parseHash(hash);
        if (parts.join("/") === this.state.path.join("/")) {
            return;
        }
        await this.navigateTo(parts, { pushHash: false });
    }
    async navigateTo(path, { pushHash = true } = {}) {
        this.state.path = path.slice(0, 2);
        this.state.level = this.state.path.length;
        this.state.page = 0;
        if (this.state.level === 2) {
            await this.loadCatalog();
            await this.loadNode();
        } else {
            this.state.node = null;
        }
        if (pushHash) {
            this.writeHash();
        }
    }
    selectArea(pid) {
        return this.navigateTo([pid]);
    }
    selectProcess(pid) {
        return this.navigateTo([this.state.path[0], pid]);
    }
    goCrumb(level) {
        return this.navigateTo(this.state.path.slice(0, level));
    }
    up() {
        return this.navigateTo(this.state.path.slice(0, -1));
    }
    async setPage(page) {
        this.state.page = Math.max(0, page);
        await this.loadNode();
    }
    async onFilterChange(field, ev) {
        this.state.filters[field] = ev.target.value || "";
        this.state.catalog = null; // 필터가 바뀌면 하위 트리 상태도 다시 받는다
        await this.loadMap();
        if (this.state.level === 2) {
            await this.loadCatalog();
            await this.loadNode();
        }
    }
    /** L3/L4 하위 업무 클릭: 어댑터가 있으면 그 노드로, 없으면 안내만(숨기지 않음). */
    async selectChild(node) {
        const link = node.status?.link;
        if (link === "linked") {
            await this.navigateTo([this.state.path[0], node.process_id]);
        } else {
            this.notification.add(`${node.name}: ${LINK_LABEL[link] || "어댑터 없음"} — 원본 연결이 아직 없습니다.`, { type: "info" });
        }
    }

    /* ── L3: 원본 열기(서버가 호출 시점에 권한·domain 을 다시 확인) ── */
    async openDoc(row) {
        try {
            const action = await this.orm.call("cams.factory.flow", "get_action", [this.state.path[1], row.id, this.filtersArg]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add("원본 문서를 열 수 없습니다(권한 또는 연결 없음).", { type: "danger" });
        }
    }
    async openList() {
        try {
            const action = await this.orm.call("cams.factory.flow", "get_action", [this.state.path[1], false, this.filtersArg]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add("목록을 열 수 없습니다(권한 또는 연결 없음).", { type: "danger" });
        }
    }
}

registry.category("actions").add("cams_ops_dashboard.factory_flow", FactoryFlow);
