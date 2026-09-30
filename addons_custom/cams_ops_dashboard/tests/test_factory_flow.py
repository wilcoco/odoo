"""[R136 2차] 서버 어댑터 — 지도 정본 일치, 계층 무결성, 집계=드릴다운 domain, 모듈 부재/권한 제한/회사 격리."""
import json
import os

from odoo.exceptions import UserError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.tools import file_open


@tagged("post_install", "-at_install")
class TestFactoryFlow(TransactionCase):

    def setUp(self):
        super().setUp()
        self.flow = self.env["cams.factory.flow"]

    def test_shipped_map_equals_docs_copy_and_is_valid(self):
        with file_open("cams_ops_dashboard/data/r136_canonical_map.json", "r") as h:
            shipped = json.load(h)
        docs = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "tasks", "R136-CANONICAL-MAP.json")
        if os.path.exists(docs):
            with open(docs, encoding="utf-8") as h:
                self.assertEqual(shipped, json.load(h), "모듈 안 지도와 docs 정본이 다르다")
        ids = [n["process_id"] for n in shipped["nodes"]]
        self.assertEqual(len(ids), len(set(ids)))
        by = {n["process_id"]: n for n in shipped["nodes"]}
        for n in shipped["nodes"]:
            if n["parent_id"] is not None:
                self.assertIn(n["parent_id"], by)
                self.assertEqual(n["level"], by[n["parent_id"]]["level"] + 1)

    def test_map_reports_states_and_never_percentages(self):
        result = self.flow.get_map(level=2)
        self.assertEqual(len([n for n in result["nodes"] if n["level"] == 1]), 8)
        links = {n["status"]["link"] for n in result["nodes"] if n["level"] == 2}
        self.assertTrue(links <= {"linked", "not_installed", "restricted", "not_wired"}, links)
        self.assertNotIn("rate", json.dumps(result))

    def test_wired_node_count_equals_drilldown_domain(self):
        Demand = self.env["production.demand"]
        product = self.env["product.product"].create({"name": "FF-완제품", "type": "consu"})
        for k in range(3):
            Demand.create({"demand_date": "2026-10-0%d" % (k + 1), "product_id": product.id, "quantity": 1.0, "source": "manual"})
        node = self.flow.get_node("CO.SALES.PLAN_RECV", filters={"date_from": "2026-10-01", "date_to": "2026-10-31"})
        self.assertEqual(node["status"]["link"], "linked")
        self.assertEqual(node["status"]["total"], Demand.search_count(node["status"]["domain"]))
        self.assertEqual(node["status"]["total"], 3)
        self.assertEqual(len(node["rows"]), 3)
        action = self.flow.get_action("CO.SALES.PLAN_RECV", filters={"date_from": "2026-10-01", "date_to": "2026-10-31"})
        self.assertEqual(action["domain"], node["status"]["domain"], "집계와 드릴다운의 domain 이 다르다")
        # UAT 결함(2026-09-15): views 없이 view_mode 만 주면 웹클라이언트 doAction 이 실패한다
        self.assertEqual(action["views"], [[False, "list"], [False, "form"]])
        doc = self.flow.get_action("CO.SALES.PLAN_RECV", res_id=node["rows"][0]["id"])
        self.assertEqual(doc["views"], [[False, "form"]]); self.assertEqual(doc["res_id"], node["rows"][0]["id"])

    def test_missing_model_is_not_installed_not_zero(self):
        self.flow.ADAPTERS["CO.MD.CHANGE"] = dict(model="cams.flow.nonexistent.model", date="write_date", state_field="state", state_map={})
        try:
            node = self.flow.get_node("CO.MD.CHANGE")
            self.assertEqual(node["status"]["link"], "not_installed")
            self.assertIsNone(node["status"]["counts"])
            with self.assertRaises(UserError):
                self.flow.get_action("CO.MD.CHANGE")
        finally:
            self.flow.ADAPTERS.pop("CO.MD.CHANGE", None)

    def test_user_without_access_sees_restricted_not_zero(self):
        outsider = self.env["res.users"].create({
            "name": "FF-외부", "login": "ff_outsider", "email": "ff_outsider@example.com",
            "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])]})
        node = self.flow.with_user(outsider).get_node("CO.SALES.PLAN_RECV")
        self.assertEqual(node["status"]["link"], "restricted")
        self.assertIsNone(node["status"]["counts"])
        self.assertEqual(node["rows"], [])

    def test_other_company_records_are_not_counted(self):
        company_b = self.env["res.company"].create({"name": "FF-회사B"})
        product = self.env["product.product"].create({"name": "FF-부품", "type": "consu"})
        Demand = self.env["production.demand"]
        Demand.create({"demand_date": "2026-11-01", "product_id": product.id, "quantity": 1.0, "source": "manual"})
        if "company_id" in Demand._fields:
            Demand.with_company(company_b).create({"demand_date": "2026-11-02", "product_id": product.id, "quantity": 1.0,
                                                   "source": "manual", "company_id": company_b.id})
            # 회사 범위 = env.companies(회사 전환기의 허용 회사). 새 회사를 만들면 관리자 env 에도 허용되므로 명시적으로 고정한다.
            filters = {"date_from": "2026-11-01", "date_to": "2026-11-30"}
            only_a = self.flow.with_context(allowed_company_ids=[self.env.company.id])
            self.assertEqual(only_a.get_node("CO.SALES.PLAN_RECV", filters=filters)["status"]["total"], 1,
                             "다른 회사의 수요가 집계에 섞였다")
            both = self.flow.with_context(allowed_company_ids=[self.env.company.id, company_b.id])
            self.assertEqual(both.get_node("CO.SALES.PLAN_RECV", filters=filters)["status"]["total"], 2,
                             "허용 회사 둘을 켜면 둘 다 보여야 한다")

    def test_extended_adapters_answer_with_state_not_zero(self):
        for pid in ("CO.MAT.SUPPLY_PLAN", "CO.MAT.RECEIPT", "CO.SALES.CLAIM", "CO.EQ.MAINT", "CO.EQ.GAGE", "CO.ADM.APPROVAL"):
            st = self.flow.get_node(pid)["status"]
            self.assertIn(st["link"], ("linked", "not_installed"), pid)
            if st["link"] == "linked":
                self.assertEqual(st["total"], self.env[st["model"]].search_count(st["domain"]), pid)
        receipt = self.flow.get_node("CO.MAT.RECEIPT")["status"]
        if receipt["link"] == "linked":
            self.assertIn("무발주", receipt["note"], "부분 연결은 note 로 드러나야 한다")
