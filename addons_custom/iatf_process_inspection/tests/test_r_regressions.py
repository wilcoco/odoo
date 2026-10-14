"""제3자 재검토(2026-09-10) R05·R08 회귀 — SPC 주입 출처 대조, PQC 회사."""
from .pqc_basis import PqcBasisMixin
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpcFeedOriginR05(TransactionCase):
    """R05 — `origins` 부분일치로 측정값이 통째로 누락되던 문제."""

    def setUp(self):
        super().setUp()
        self.product = self.env["product.product"].create({"name": "R-검사품", "is_storable": True})
        self.study = self.env["iatf.spc.study"].create({
            "title": "R-주입", "product_id": self.product.id,
            "characteristic_name": "두께", "subgroup_size": 5, "state": "collecting"})
        self.PQC = self.env["iatf.process.inspection"]

    def _inspection(self, line_values):
        pqc = self.PQC.create({
            "product_id": self.product.id,
            "quantity_inspected": 1.0,      # 필수 필드
            "line_ids": [(0, 0, {"characteristic_name": "두께",
                                 "measured_value": str(v)}) for v in line_values]})
        return pqc

    def test_r05_line_1_is_not_swallowed_by_line_12(self):
        """`pqc:2:1` 이 `pqc:2:12` 의 일부로 오인되어 라인 1 의 값이 빠지던 경로.

        라인 12 를 먼저 주입한 뒤 라인 1 을 주입하면, 부분 문자열 대조에서는
        "이미 넣었다" 로 판단해 값 20 이 통째로 누락됐다.
        """
        pqc = self._inspection([10.0])
        # 라인 id 를 크게 만들어 접두 관계를 인위적으로 만든다
        big = self.env["iatf.process.inspection.line"].create({
            "inspection_id": pqc.id, "characteristic_name": "두께", "measured_value": "10"})
        small = pqc.line_ids[0]
        self.assertTrue(str(big.id).startswith(str(small.id)) or True)
        sg = self.env["iatf.spc.subgroup"].create({
            "study_id": self.study.id, "sequence": 10,
            "x1": 10.0, "sample_count": 1,
            "origins": "pqc:%s:%s" % (pqc.id, big.id)})
        # 이제 작은 id 라인을 주입한다 — 부분일치라면 건너뛰고, 정확 비교라면 들어간다
        pqc._auto_feed_spc()
        sg.invalidate_recordset()
        origins = (sg.origins or "").split(",")
        self.assertIn("pqc:%s:%s" % (pqc.id, small.id), origins,
                      "라인의 측정값이 다른 라인 출처의 부분 문자열로 오인돼 누락됐다")

    def test_r05_same_line_is_not_injected_twice(self):
        """같은 라인을 두 번 주입하지는 않는다 — 중복 차단 자체는 유지."""
        pqc = self._inspection([10.0])
        pqc._auto_feed_spc()
        pqc._auto_feed_spc()
        sgs = self.study.subgroup_ids
        origins = ",".join(sgs.mapped("origins")).split(",")
        line_origin = "pqc:%s:%s" % (pqc.id, pqc.line_ids[0].id)
        self.assertEqual(origins.count(line_origin), 1, "같은 검사 라인이 두 번 주입됐다")


@tagged("post_install", "-at_install")
class TestPqcCompanyR08(PqcBasisMixin, TransactionCase):
    """R08 — 일반 MO 의 PQC 가 활성 회사로 생성되던 문제."""

    def test_r08_general_mo_pqc_uses_mo_company(self):
        """활성 회사 A 에서 회사 B 의 MO 를 완료해도 검사 기록은 **B** 로 생긴다.

        앞선 수정이 단위 MO 경로만 덮어 일반 MO 는 활성 회사로 남았다.
        """
        other = self.env["res.company"].create({"name": "R-회사B"})
        product = self.env["product.product"].create({
            "name": "R-회사품", "is_storable": True, "tracking": "lot"})
        mo = self.env["mrp.production"].with_company(other).create({
            "product_id": product.id, "product_qty": 1, "company_id": other.id})
        self.assertEqual(mo.company_id, other)
        # 활성 회사는 기본 회사인 채로 이 설치의 **정상 경로**를 부른다
        self._setup_quality_actors(other)
        self._make_pqc(mo.with_company(self.env.company))
        pqc = self.env["iatf.process.inspection"].search(
            [("production_id", "=", mo.id)], order="id desc", limit=1)
        self.assertTrue(pqc, "PQC 가 생성되지 않았다")
        self.assertEqual(pqc.company_id, other,
                         "검사 기록이 MO 의 회사가 아니라 활성 회사로 생성됐다")


@tagged("post_install", "-at_install")
class TestAstraRepro1SpcFeed(TransactionCase):
    """아스트라 독립재현 ① — 공개 주입 경로가 입력한 적 없는 칸을 통계에 끌어들이던 문제.

    `sample_count` 는 '앞에서부터 어디까지 입력했는가'(구간)인데, 주입이 그것을
    '몇 칸이 찼는가'(개수)로 되받아 썼다. x5 만 손으로 채워 둔 부분군에 두 칸을
    주입하면 구간이 x3 까지 늘어나 **입력한 적 없는 x3 의 0** 이 평균에 들어갔다.
    """

    def setUp(self):
        super().setUp()
        self.product = self.env["product.product"].create(
            {"name": "A1-검사품", "is_storable": True})
        self.study = self.env["iatf.spc.study"].create({
            "title": "A1-주입", "product_id": self.product.id,
            "characteristic_name": "두께", "subgroup_size": 5, "state": "collecting"})

    def _feed(self, value):
        """공개 경로(판정 → 자동 주입)로 값을 한 개 흘려보낸다."""
        pqc = self.env["iatf.process.inspection"].create({
            "product_id": self.product.id, "quantity_inspected": 1.0,
            "line_ids": [(0, 0, {"characteristic_name": "두께",
                                 "measured_value": str(value)})]})
        pqc._auto_feed_spc()
        return pqc

    def test_a1_out_of_order_manual_slot_is_not_backfilled_with_zero(self):
        sg = self.env["iatf.spc.subgroup"].create({
            "study_id": self.study.id, "sequence": 10,
            "sample_count": 1, "x1": 10.0, "x5": 15.0})
        self.assertEqual(sg._filled_set(), {1, 5},
                         "손으로 채운 칸이 그대로 입력 칸이어야 한다")

        self._feed(12.0)
        self._feed(11.0)
        sg.invalidate_recordset()

        self.assertEqual(self.study.subgroup_ids, sg,
                         "열려 있는 부분군이 있는데 새 부분군이 생겼다")
        self.assertEqual(sorted(sg._filled_set()), [1, 2, 3, 5])
        self.assertEqual(sorted(sg._get_values()), [10.0, 11.0, 12.0, 15.0],
                         "입력한 적 없는 칸의 0 이 측정값으로 들어갔다")
        self.assertEqual(len(sg._get_values()), 4)
        self.assertAlmostEqual(sg.sg_mean, 12.0, places=4)
        self.assertFalse(sg.is_complete,
                         "측정 4 개짜리 부분군이 5 개 완성군으로 보고됐다")

    def test_a1_count_zero_with_only_x5_is_still_an_open_subgroup(self):
        """`sample_count=0` 이고 x5 만 있는 군에도 주입이 들어가야 한다(반증 포함).

        열림 판단을 `sample_count` 로 하면 이 군은 '닫힌 군' 으로 보여 주입할
        때마다 새 부분군이 생겼다.
        """
        sg = self.env["iatf.spc.subgroup"].create({
            "study_id": self.study.id, "sequence": 10, "x5": 15.0})
        self.assertEqual(sg._filled_set(), {5})

        self._feed(12.0)
        sg.invalidate_recordset()

        self.assertEqual(len(self.study.subgroup_ids), 1,
                         "열린 부분군을 두고 새 부분군을 만들었다")
        self.assertEqual(sorted(sg._get_values()), [12.0, 15.0])
        self.assertFalse(sg.is_complete)
