from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestPlanningAudit(TransactionCase):
    """계획 엔진 정독 감사 배터리 승격본 — UoM 원단위 정밀·진행 MO 차감·
    사출품 직접 수요·풀캐퍼 정책 고정."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # [R135] 이 시험은 기존 풀 캐퍼 정책(14h×100=1400, 200 미배정)을 검증한다. 새 설치는
        # post_init_hook 이 교체 인식 방식을 기본으로 두므로 여기서 명시적으로 기존 방식을 고정한다.
        cls.env["injection.planning.run"]._get_config().write({"sequencing_mode": "legacy"})
        cls.kg = cls.env.ref("uom.product_uom_kgm")
        cls.g = cls.env.ref("uom.product_uom_gram")
        cls.unit = cls.env.ref("uom.product_uom_unit")
        # The 1400-piece assertion below requires two explicit 8-hour shifts.
        # Creating another config does not replace an existing active company
        # config, especially when this suite is run on a reused synthetic DB.
        config = cls.env["injection.planning.run"]._get_config()
        config.write({"day_shift_hours": 8.0, "night_shift_hours": 8.0,
                      "day_shift_start": 8.0, "night_shift_start": 20.0})
        # 설비 달력의 휴게·휴무를 섞지 않는다 — 이 시험은 UoM·중복 계획을 본다.
        cal = cls.env["resource.calendar"].create({
            "name": "T-연속가동", "tz": config.get_shift_timezone(),
            "attendance_ids": [(5, 0, 0)] + [
                (0, 0, {"name": "연속-%s" % day, "dayofweek": str(day),
                        "hour_from": 0.0, "hour_to": 24.0}) for day in range(7)]})
        cls.wc = cls.env["mrp.workcenter"].create({
            "name": "T-사출기", "resource_calendar_id": cal.id})
        cls.resin = cls.env["product.product"].create({
            "name": "T-수지", "uom_id": cls.kg.id, "uom_po_id": cls.kg.id, "is_storable": True})
        cls.mb = cls.env["product.product"].create({
            "name": "T-마스터배치", "uom_id": cls.kg.id, "uom_po_id": cls.kg.id, "is_storable": True})
        cls.injection_department = cls.env["hr.department"].create({
            "name": "T-사출팀",
        })
        cls.injection_management_number = cls.env[
            "escon.bom.management.number"
        ].create({
            "name": "TEST-INJECTION",
            "department_id": cls.injection_department.id,
        })

    def _make_inj(self, name, code):
        inj = self.env["product.product"].create({"name": name, "is_storable": True})
        # worksite 미설치 환경(계획 단독 CI)엔 필드가 없음 — capability 보유로도 사출품 판정됨
        if "is_injection_part" in inj.product_tmpl_id._fields:
            inj.product_tmpl_id.is_injection_part = True
        # 원단위는 g 등록 관례 — kg(정밀도 2자리) 등록 시 0.784→0.78 로 저장되는 함정
        self.env["mrp.bom"].with_context(allow_managed_bom_create=True).create({
            "product_tmpl_id": inj.product_tmpl_id.id,
            "product_qty": 1,
            "bom_purpose": "injection",
            "source_type": "injection_process",
            "management_number_id": self.injection_management_number.id,
            "bom_state": "active",
            "active": True,
            "bom_line_ids": [
                (0, 0, {"product_id": self.resin.id, "product_qty": 784, "product_uom_id": self.g.id}),
                (0, 0, {"product_id": self.mb.id, "product_qty": 8, "product_uom_id": self.g.id}),
            ]})
        mold = self.env["injection.mold"].create({"name": name + "금형", "code": code, "product_id": inj.id})
        self.env["injection.machine.mold.capability"].create({
            "workcenter_id": self.wc.id, "mold_id": mold.id,
            "cycle_time": 36.0, "defect_rate": 0.0, "initial_scrap": 0, "active": True})
        return inj

    def _run(self, demand_product, qty, date="2026-08-20"):
        d = self.env["production.demand"].create({
            "demand_date": date, "product_id": demand_product.id,
            "quantity": qty, "source": "manual"})
        run = self.env["injection.planning.run"].create({
            "plan_date_from": date, "plan_date_to": date,
            "demand_ids": [(6, 0, [d.id])]})
        run.action_calculate_plan()
        return run

    def test_full_chain_uom_and_dedup(self):
        inj = self._make_inj("T-사출품", "TM-1")
        fin = self.env["product.product"].create({"name": "T-완제품", "is_storable": True})
        self.env["mrp.bom"].create({
            "product_tmpl_id": fin.product_tmpl_id.id, "product_qty": 1,
            "bom_line_ids": [(0, 0, {"product_id": inj.id, "product_qty": 2,
                                     "product_uom_id": self.unit.id})]})
        run = self._run(fin, 250)
        planned = sum(run.line_ids.mapped("planned_qty"))
        # 풀캐퍼 정책은 100/h×16h=1600 을 요구하지만, 빈 호기에 금형을 **설치**하는
        # 2시간(금형 기본값)이 가동시간에서 먼저 빠진다. 실제로 넣을 수 있는 것은
        # 14h×100 = 1400 이고 나머지 200 은 미배정으로 드러난다. (독립검토 PR06)
        # 예전에는 설치 시간을 0 으로 세어 1600 을 전량 배정한 것으로 계산했다.
        self.assertEqual(planned, 1400, "설치 2h 제외 14h×100/h")
        self.assertAlmostEqual(sum(run.unassigned_ids.mapped("qty")), 200.0, places=0,
                               msg="조합에 적힌 초기불량 0 이 설정 기본값 20 으로 되살아났다")
        reqs = {r.material_id.id: r.required_qty for r in run.material_requirement_ids}
        self.assertAlmostEqual(reqs[self.resin.id], planned * 0.784, places=2,
                               msg="g→kg 원단위 정밀 (반올림 왜곡 금지)")
        self.assertAlmostEqual(reqs[self.mb.id], planned * 0.008, places=3,
                               msg="마스터배치 0.00 결함 회귀 방지")
        details = []
        for line in run.line_ids:
            vals = run._get_mo_vals(line, self.env['mrp.bom']._bom_find(inj)[inj])
            details.append({'line': line.read(['planned_qty', 'start_time', 'end_time',
                'changeover_hours', 'changeover_in_span_hours']), 'mo_vals': vals})
        class ProbeRollback(Exception):
            pass
        try:
            with self.env.cr.savepoint():
                line = run.line_ids[0]
                vals = run._get_mo_vals(line, self.env['mrp.bom']._bom_find(inj)[inj])
                probe = self.env['mrp.production'].create(vals)
                probe.action_confirm()
                details.append({'probe': probe.read(['product_qty', 'date_start', 'date_finished',
                    'planning_hourly_capacity', 'planning_changeover_hours', 'workorder_ids']),
                    'hook': probe._injection_plan_expected_finish(probe.date_start)})
                raise ProbeRollback()
        except ProbeRollback:
            pass
        run.generate_manufacturing_orders()
        self.assertEqual(len(run.mo_ids), len(run.line_ids), str(details))
        # 진행 MO 차감 — 같은 수요 재계획 시 이중 계획 0
        run2 = self._run(fin, 250)
        self.assertEqual(sum(run2.line_ids.mapped("planned_qty")), 0,
                         "진행 MO 미차감 이중 계획 결함 회귀 방지")

    def test_injection_direct_demand_not_lost(self):
        inj2 = self._make_inj("T-사출품2", "TM-2")
        run = self._run(inj2, 300, date="2026-08-25")
        self.assertGreater(sum(run.line_ids.mapped("planned_qty")), 0,
                           "원재료 BOM 보유 사출품의 직접 수요 소실 결함 회귀 방지")

    def test_material_po_portal_exposure(self):
        # UAT 이슈 #1 회귀 방지: 포털 협력사의 원재료 발주는 포털 노출+알림,
        # 비포털 협력사는 종전과 동일
        portal_vendor = self.env["res.partner"].create({"name": "T-원재료사"})
        if "is_supplier_portal" not in portal_vendor._fields:
            self.skipTest("supplier_portal_purchase 미설치 — 가드 경로만 유효")
        portal_vendor.is_supplier_portal = True
        plain_vendor = self.env["res.partner"].create({"name": "T-첨가제사"})
        self.env["product.supplierinfo"].create({
            "partner_id": portal_vendor.id,
            "product_tmpl_id": self.resin.product_tmpl_id.id, "price": 1.5})
        self.env["product.supplierinfo"].create({
            "partner_id": plain_vendor.id,
            "product_tmpl_id": self.mb.product_tmpl_id.id, "price": 9.0})
        inj3 = self._make_inj("T-사출품3", "TM-3")
        run = self._run(inj3, 300, date="2026-08-26")
        run.action_create_material_po()
        pos = self.env["purchase.order"].search(
            [("injection_planning_run_id", "=", run.id)])
        portal_po = pos.filtered(lambda p: p.partner_id == portal_vendor)
        plain_po = pos.filtered(lambda p: p.partner_id == plain_vendor)
        self.assertTrue(portal_po and plain_po, "공급사별 발주 생성")
        self.assertTrue(portal_po.auto_generated, "포털 협력사 발주는 포털 노출")
        self.assertEqual(portal_po.portal_state, "new")
        self.assertTrue(self.env["supplier.portal.notification"].search_count([
            ("partner_id", "=", portal_vendor.id),
            ("purchase_order_id", "=", portal_po.id),
            ("notification_type", "=", "new_po")]), "포털 알림 발송")
        self.assertFalse(plain_po.auto_generated, "비포털 협력사는 종전과 동일")
