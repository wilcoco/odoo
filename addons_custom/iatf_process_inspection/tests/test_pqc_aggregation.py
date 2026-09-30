from freezegun import freeze_time

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from .pqc_basis import PqcBasisMixin


@tagged("post_install", "-at_install")
class TestPqcAggregation(PqcBasisMixin, TransactionCase):
    """PQC 자동 생성 — 일반 MO는 FQC 1건, 단위 MO(worksite 설치 시)는 생산 런 단위 묶음."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_quality_actors(cls.env.company)

    def test_normal_mo_fqc(self):
        # 합본의 품질 범위 추적은 **LOT 관리 기준**을 요구한다.
        product = self.env["product.product"].create({
            "name": "T-PQC품", "is_storable": True, "tracking": "lot"})
        mo = self.env["mrp.production"].create({"product_id": product.id, "product_qty": 1})
        PQC = self.env["iatf.process.inspection"]
        before = PQC.search_count([("production_id", "=", mo.id)])
        # 이 설치의 **정상 경로**로 만든다 (합본은 완료 전 준비, 단독은 완료 훅).
        self._make_pqc(mo)
        self.assertGreater(PQC.search_count([("production_id", "=", mo.id)]), before,
                           "정상 경로로도 공정검사가 생기지 않았다")
        self.assertIn("final", PQC.search([("production_id", "=", mo.id)]).mapped(
            "inspection_stage"), "최종검사(FQC)가 없다")

    def test_unit_mo_run_aggregation(self):
        """단위 MO 폭증 방지 — worksite 미설치 환경이면 skip (필드 부재)."""
        MO = self.env["mrp.production"]
        if "is_ip_unit_mo" not in MO._fields:
            self.skipTest("injection_worksite 미설치 — 단위 MO 경로 없음")
        # 합본의 품질 범위 추적은 **LOT 관리 기준**을 요구한다.
        product = self.env["product.product"].create({
            "name": "T-사출", "is_storable": True, "tracking": "lot"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": product.product_tmpl_id.id, "product_id": product.id,
            "product_qty": 1.0, "type": "normal", "company_id": self.env.company.id})
        plan = MO.create({"product_id": product.id, "product_qty": 100, "bom_id": bom.id})
        PQC = self.env["iatf.process.inspection"]
        mold = self.env["injection.mold"].create({
            "name": "T-사출금형", "code": "T-MOLD-%s" % plan.id,
            "product_id": product.id, "cavity_count": 1,
            "company_id": self.env.company.id,
        }) if "injection.mold" in self.env else False
        units = MO.create([{
            "product_id": product.id, "product_qty": 1, "bom_id": bom.id,
            "is_ip_unit_mo": True, "parent_planning_mo_id": plan.id,
        } for _ in range(3)])
        # 초안의 계획 수량은 생산 실적이 아니다. 완료 API로 재고 실적을 확정해야
        # qty_produced가 생기며 date_finished도 실제 완료일로 결정된다.
        for index, unit in enumerate(units):
            finished = "2026-07-19 10:00:00" if index < 2 else "2026-07-20 10:00:00"
            # 합본에서는 완료에 **승인 관리계획**이 필요하다. 게이트를 낮추지
            # 않고 정상 절차로 갖춘다(단독 설치에서는 아무 일도 하지 않는다).
            self._approve_control_plan(unit)
            # 합본의 초물은 **실제 금형**을 요구한다(사출 단위 MO 경로).
            if "actual_mold_id" in unit._fields and not unit.actual_mold_id:
                unit.actual_mold_id = mold.id
            if not unit.lot_producing_id:
                unit.lot_producing_id = self.env["stock.lot"].create({
                    "name": "T-사출-%s" % unit.id, "product_id": product.id,
                    "company_id": unit.company_id.id}).id
            with freeze_time(finished):
                unit.action_complete_unit_mo()
            self.assertEqual(unit.state, "done")
            self.assertEqual(unit.qty_produced, 1)
        # **여기서 합본과 단독의 계약이 갈린다.**
        #
        # 단독 `iatf_process_inspection` 의 설계는 「단위 MO 개별 검사서 없음 —
        # 하루 수천 타의 검사서 폭증 방지」다. 그런데 선행 게이트
        # (`iatf_quality_precedence`)가 설치되면 **단위 MO 를 완료하려면 그 단위의
        # 초물·공정·최종 검사가 있어야** 한다
        # (`injection_worksite` 가 완료 경로에서 `action_prepare_required_quality`
        #  를 부른다). 두 정책이 정면으로 다르다.
        #
        # **원래 계약을 지우지 않는다.** 게이트가 없으면 0 을 그대로 요구하고,
        # 게이트가 있으면 그 요구 때문에 생긴다는 것을 명시한다. 이 차이는
        # 아스트라에게 별도 보고한다 — 시험으로 덮을 일이 아니다.
        unit_checks = PQC.search_count([("production_id", "in", units.ids)])
        if self._quality_gate_installed():
            self.assertEqual(unit_checks, 3 * len(units),
                             "게이트가 요구하는 단위별 초물·공정·최종 검사가 없다")
        else:
            self.assertEqual(unit_checks, 0, "단위 MO 개별 검사서 없음")
        runs = PQC.search([("production_id", "=", plan.id)])
        self.assertEqual(len(runs), 2, "생산일별 1건 (19일·20일)")
        day1 = runs.filtered(lambda r: str(r.production_date) == "2026-07-19")
        self.assertEqual(day1.quantity_produced, 2, "같은 런 수량 누적")
        self.assertEqual(day1.article_stage, "first")
        # **생산량을 검사량으로 자동 간주하지 않는다.**
        self.assertEqual(day1.quantity_inspected, 0,
                         "만든 수를 검사한 수로 적어 놓았다")
        self.assertEqual(sorted(day1.run_unit_mo_ids or []), sorted(units[:2].ids),
                         "묶음이 어느 단위 실적을 셌는지 남지 않았다")

    def test_a_repeated_unit_completion_does_not_double_count(self):
        """[아스트라 20260912 05:1x] 「**반복 완료는 생산량/검사량을 중복 누적하지
        않아야** 하고, 이미 승인된 검사서에 후속 실적을 덧붙여 승인 범위를 조용히
        늘리면 안 됩니다.」"""
        MO = self.env["mrp.production"]
        if "is_ip_unit_mo" not in MO._fields:
            self.skipTest("injection_worksite 미설치 — 단위 MO 경로 없음")
        PQC = self.env["iatf.process.inspection"]
        product = self.env["product.product"].create({
            "name": "T-재호출", "is_storable": True, "tracking": "lot"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": product.product_tmpl_id.id, "product_id": product.id,
            "product_qty": 1.0, "type": "normal", "company_id": self.env.company.id})
        plan = MO.create({"product_id": product.id, "product_qty": 10,
                          "bom_id": bom.id})
        unit = MO.create({"product_id": product.id, "product_qty": 1,
                          "bom_id": bom.id, "is_ip_unit_mo": True,
                          "parent_planning_mo_id": plan.id})
        self._approve_control_plan(unit)
        if "actual_mold_id" in unit._fields and not unit.actual_mold_id:
            unit.actual_mold_id = self.env["injection.mold"].create({
                "name": "T-재호출금형", "code": "T-MOLD-R-%s" % plan.id,
                "product_id": product.id, "cavity_count": 1,
                "company_id": self.env.company.id}).id
        if not unit.lot_producing_id:
            unit.lot_producing_id = self.env["stock.lot"].create({
                "name": "T-재호출-%s" % unit.id, "product_id": product.id,
                "company_id": unit.company_id.id}).id
        with freeze_time("2026-07-21 10:00:00"):
            unit.action_complete_unit_mo()
        run = PQC.search([("production_id", "=", plan.id)])
        self.assertEqual(len(run), 1)
        self.assertEqual(run.quantity_produced, 1)

        # **같은 단위를 다시 완료 훅에 넣어도** 생산량이 늘지 않는다
        unit._create_pqc_inspection()
        run.invalidate_recordset()
        self.assertEqual(len(PQC.search([("production_id", "=", plan.id)])), 1,
                         "재호출이 묶음을 하나 더 만들었다")
        self.assertEqual(run.quantity_produced, 1, "재호출이 생산량을 중복 누적했다")
        self.assertEqual(run.quantity_inspected, 0, "검사량이 저절로 올랐다")

    def test_run_group_evidence_cannot_be_injected(self):
        """[아스트라 20260912 05:27] 「`run_unit_mo_ids` 는 readonly JSON 이지만
        **create/write/default 값 차단 및 원검사 스냅샷 필드 집합에 포함되지
        않았습니다. UI readonly 만으로 원천 근거를 보호할 수 없습니다.** 일반 검사
        작성 권한의 직접 create/write/default 주입·변조와 승인 후 변경을 막고,
        정상 내부 집계는 **위조 불가능한 내부 경로로 제한**하십시오.」
        """
        PQC = self.env["iatf.process.inspection"]
        product = self.env["product.product"].create({
            "name": "T-주입", "is_storable": True})
        base = {"company_id": self.env.company.id, "product_id": product.id,
                "inspection_stage": "ipqc", "quantity_inspected": 1}

        # ① 직접 create 주입 거부
        with self.assertRaises(UserError):
            PQC.create(dict(base, run_unit_mo_ids=[1, 2, 3]))
        # ② default_ 주입 거부
        with self.assertRaises(UserError):
            PQC.with_context(default_run_unit_mo_ids=[1, 2, 3]).create(dict(base))
        # ③ 정상 경로로 만든 뒤 직접 write 거부
        record = PQC.create(dict(base))
        self.assertFalse(record.run_unit_mo_ids)
        with self.assertRaises(UserError):
            record.write({"run_unit_mo_ids": [1, 2, 3]})
        # ④ 스냅샷 필드 집합에 포함된다 (원검사 근거 보호 대상)
        self.assertIn("run_unit_mo_ids", PQC._AUTO_SOURCE_FIELDS)

    def test_a_run_group_scope_cannot_be_edited_afterwards(self):
        """묶음 근거가 붙은 검사서의 범위는 사람이 직접 바꾸지 않는다."""
        MO = self.env["mrp.production"]
        if "is_ip_unit_mo" not in MO._fields:
            self.skipTest("injection_worksite 미설치 — 단위 MO 경로 없음")
        PQC = self.env["iatf.process.inspection"]
        product = self.env["product.product"].create({
            "name": "T-범위", "is_storable": True, "tracking": "lot"})
        bom = self.env["mrp.bom"].create({
            "product_tmpl_id": product.product_tmpl_id.id, "product_id": product.id,
            "product_qty": 1.0, "type": "normal", "company_id": self.env.company.id})
        plan = MO.create({"product_id": product.id, "product_qty": 5,
                          "bom_id": bom.id})
        unit = MO.create({"product_id": product.id, "product_qty": 1,
                          "bom_id": bom.id, "is_ip_unit_mo": True,
                          "parent_planning_mo_id": plan.id})
        self._approve_control_plan(unit)
        if "actual_mold_id" in unit._fields and not unit.actual_mold_id:
            unit.actual_mold_id = self.env["injection.mold"].create({
                "name": "T-범위금형", "code": "T-MOLD-S-%s" % plan.id,
                "product_id": product.id, "cavity_count": 1,
                "company_id": self.env.company.id}).id
        if not unit.lot_producing_id:
            unit.lot_producing_id = self.env["stock.lot"].create({
                "name": "T-범위-%s" % unit.id, "product_id": product.id,
                "company_id": unit.company_id.id}).id
        unit.action_complete_unit_mo()

        run = PQC.search([("production_id", "=", plan.id)])
        self.assertTrue(run.run_unit_mo_ids, "묶음 근거가 남지 않았다")
        with self.assertRaises(UserError):
            run.write({"quantity_produced": 999})
        with self.assertRaises(UserError):
            run.write({"production_id": unit.id})

    def _decided_inspection(self, name):
        """정상 절차로 판정까지 간 **개별** 검사 하나."""
        product = self.env["product.product"].create({
            "name": name, "is_storable": True, "tracking": "lot"})
        mo = self.env["mrp.production"].create({
            "product_id": product.id, "product_qty": 1})
        self._make_pqc(mo)
        inspection = self.env["iatf.process.inspection"].search(
            [("production_id", "=", mo.id)], limit=1)
        self.assertTrue(inspection, "검사가 만들어지지 않았다")
        inspection.write({"quantity_inspected": 1, "quantity_accepted": 1,
                          "quantity_rejected": 0, "result": "pass",
                          # 판정은 **실제 로그인한 검사자**가 한다 (가드가 옳다)
                          "inspector_id": self.env.user.id})
        inspection.line_ids.write({"measured_value": "합성 관측", "result": "pass"})
        inspection.action_decide()
        return inspection

    def _make_legacy_snapshot(self, inspection):
        """업데이트 **이전** 모양의 원천 스냅샷 — `run_unit_mo_ids` 키가 없다."""
        payload = inspection._auto_source_payload()
        source = {k: v for k, v in payload["source"].items()
                  if k != "run_unit_mo_ids"}
        self.assertNotIn("run_unit_mo_ids", source)
        inspection.with_context(
            _process_auto_evidence_token=self._token()).write({
                "auto_evidence_snapshot": dict(payload, source=source)})
        return inspection

    def _token(self):
        from odoo.addons.iatf_process_inspection.models.process_inspection import (
            _AUTO_EVIDENCE_TOKEN)
        return _AUTO_EVIDENCE_TOKEN

    def test_a_legacy_snapshot_without_the_new_key_still_matches(self):
        """[아스트라 20260912 06:30] 「44 단위 중 42 실패 … 차이는 **오직
        `run_unit_mo_ids` 키: 기존 원본에는 없음, 새 계산값에는 false**입니다.
        … **실제 철회로 판정하면 안 됩니다.**」

        제 회귀입니다. 보호 집합에 필드를 넣으면서 **이미 승인된 과거 근거의
        직렬화 모양까지** 바꿨습니다. 기존 원본·시각·사용자를 다시 쓰지 않고
        **비교만** 구버전 호환으로 고쳤습니다.
        """
        inspection = self._decided_inspection("T-구자료")
        self._make_legacy_snapshot(inspection)
        # 집계 근거가 없는 일반 검사다 — 구자료는 그대로 통과해야 한다
        self.assertFalse(inspection.run_unit_mo_ids)
        self.assertTrue(inspection._auto_source_matches(
            inspection.auto_evidence_snapshot.get("source")),
            "구자료가 철회로 판정됐다")
        inspection._remember_auto_evidence()        # 예외가 나면 안 된다

    def test_a_legacy_snapshot_is_still_strict_about_everything_else(self):
        """구버전 호환이 **다른 변조까지 봐 주지는 않는다.**"""
        inspection = self._decided_inspection("T-구자료변조")
        self._make_legacy_snapshot(inspection)
        # ① 다른 원천 필드가 바뀌면 여전히 차단된다
        inspection.with_context(
            _process_auto_evidence_token=self._token()).write(
                {"quantity_produced": 999})
        self.assertFalse(inspection._auto_source_matches(
            inspection.auto_evidence_snapshot.get("source")),
            "다른 필드가 바뀌었는데 통과했다")
        with self.assertRaises(UserError):
            inspection._remember_auto_evidence()

    def test_aggregate_evidence_inserted_after_approval_is_refused(self):
        """승인 **뒤에** 집계 근거가 생기면 구자료로 봐 주지 않는다."""
        inspection = self._decided_inspection("T-후삽입")
        self._make_legacy_snapshot(inspection)
        # 집계 근거를 뒤늦게 넣는다 (일반 경로로는 애초에 막히지만,
        #  서버 경로로 들어왔다 해도 **근거 비교에서** 걸려야 한다)
        inspection.with_context(
            _process_auto_evidence_token=self._token()).write(
                {"run_unit_mo_ids": [1, 2]})
        self.assertFalse(inspection._auto_source_matches(
            inspection.auto_evidence_snapshot.get("source")),
            "승인 뒤 집계 근거 후삽입이 통과했다")
        with self.assertRaises(UserError):
            inspection._remember_auto_evidence()

    def test_new_records_keep_the_key_and_stay_strict(self):
        """새 자료는 키를 갖고, 그 값이 바뀌면 차단된다."""
        inspection = self._decided_inspection("T-신규자료")
        self.assertIn("run_unit_mo_ids",
                      inspection.auto_evidence_snapshot.get("source"),
                      "새 스냅샷에 키가 없다")
        inspection._remember_auto_evidence()        # 그대로면 통과
        inspection.with_context(
            _process_auto_evidence_token=self._token()).write(
                {"run_unit_mo_ids": [7]})
        self.assertFalse(inspection._auto_source_matches(
            inspection.auto_evidence_snapshot.get("source")),
            "새 자료의 집계 근거가 바뀌었는데 통과했다")
