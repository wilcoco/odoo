"""선행 품질 게이트가 설치된 합본에서 **정상 경로** 기준정보를 갖춘다.

[아스트라 20260911-13] 「정상 경로 시험에 합성 기준정보를 갖추는 것 자체는 결함을
숨기는 일이 아닙니다. 다만 ... 상태를 SQL/write 로 강제합격시키지 않습니다.」

그래서 여기서는 **정상 업무 API** 만 쓴다 — 관리계획 작성 → 결재 상신 → 승인,
검사 준비 → 판정 → 결재 상신 → 승인. 상태를 직접 쓰지 않는다.

게이트가 설치되지 않은 환경에서는 **아무것도 하지 않는다**(그 환경엔 그 기준이 없다).
"""
from odoo import Command
from odoo.tests.common import new_test_user


class QualityBasisMixin:
    """합성 관리계획·검사를 정상 절차로 갖춰 주는 시험 보조."""

    _QUALITY_STAGES = ("first", "ipqc", "final")

    @classmethod
    def _quality_gate_installed(cls):
        """**게이트**가 설치됐는지 본다.

        `control_plan_id` 필드 유무로 보면 안 된다 — 그 필드는 `iatf_control_plan`
        이 얹는 것이라 게이트(`iatf_quality_precedence`) 없이도 존재한다.
        실제로 그렇게 짰다가 단독 환경에서 19건이 깨졌다.
        게이트가 정의하는 **메서드**로 판별한다.
        """
        return hasattr(cls.env["mrp.production"], "_quality_expected_groups")

    @classmethod
    def _setup_quality_actors(cls, company):
        """검사자·승인자·계획자. 게이트가 없으면 만들지 않는다."""
        cls._quality_actors = {}
        if not cls._quality_gate_installed():
            return
        common = "base.group_user,stock.group_stock_user,mrp.group_mrp_user,"
        env = cls.env["res.users"].with_context(
            no_reset_password=True, mail_create_nosubscribe=True, mail_notrack=True).env
        cls._quality_actors = {
            "inspector": new_test_user(
                env, login="qb-inspector-%s" % company.id,
                groups=common + "iatf_process_inspection.group_process_inspection_user",
                company_id=company.id, company_ids=[Command.set(company.ids)]),
            "approver": new_test_user(
                env, login="qb-approver-%s" % company.id,
                groups=common + "iatf_process_inspection.group_process_inspection_manager,"
                                "iatf_control_plan.group_cp_manager",
                company_id=company.id, company_ids=[Command.set(company.ids)]),
            "planner": new_test_user(
                env, login="qb-planner-%s" % company.id,
                groups=common + "iatf_control_plan.group_cp_user",
                company_id=company.id, company_ids=[Command.set(company.ids)]),
        }
        # 품질 경보 팀이 없으면 자동 품질검사가 팀 없이 만들어진다.
        Team = cls.env["quality.alert.team"]
        if not Team.sudo().search([("company_id", "in", (False, company.id))], limit=1):
            Team.sudo().create({"name": "QB 합성 품질팀", "company_id": company.id})

    def _approve_control_plan(self, mo):
        """이 MO 에 **승인된 관리계획**을 정상 절차로 붙인다.

        작성 → 결재 상신 → 승인. 상태를 직접 쓰지 않는다. 검사까지는 만들지
        않으므로, 검사 생성/누적 자체를 보는 시험이 그대로 쓸 수 있다.
        """
        if not self._quality_gate_installed():
            return False
        actors = getattr(self, "_quality_actors", None) or {}
        planner, approver = actors.get("planner"), actors.get("approver")
        if not (planner and approver):
            return False
        if mo.control_plan_id and mo.control_plan_id.sudo().state == "approved":
            return mo.control_plan_id
        company = mo.company_id
        if not mo.bom_id:
            # **양산 관리계획은 BOM 을 요구한다**(`_quality_validate_definition`).
            # BOM 없는 MO 에는 승인 관리계획이 있을 수 없으므로 합성 BOM 을 갖춘다.
            mo.write({"bom_id": self.env["mrp.bom"].sudo().create({
                "product_tmpl_id": mo.product_id.product_tmpl_id.id,
                "product_id": mo.product_id.id,
                "product_qty": 1.0, "type": "normal",
                "company_id": company.id}).id})
        plan = self.env["iatf.control.plan"].with_user(planner).create({
            "title": "합성 관측 기준 (고객 표준 아님)",
            "cp_type": "production",
            "company_id": company.id,
            "product_id": mo.product_id.id,
            "bom_id": mo.bom_id.id,
            "approval_line_ids": [Command.create(
                {"sequence": 10, "user_id": approver.id})],
            "line_ids": [Command.create({
                "characteristic_name": "합성 관측 항목 %s" % stage,
                "specification": "합성: 균열 없음",
                "evaluation_method": "합성: 육안 관측",
                "sample_size": "합성 1개",
                "sample_frequency": "합성 MO 마다",
                "reaction_plan": "보류 후 NC 발행; 처분은 별도 검토",
                "quality_stage": stage,
                "quality_frequency": "each_mo",
                "quality_sample_qty": 1,
            }) for stage in self._QUALITY_STAGES],
        })
        plan.action_submit_approval()
        plan.approval_request_id.with_user(approver).action_approve(
            expected_line_id=plan.approval_request_id.current_line_id.id)
        assert plan.state == "approved", "합성 관리계획이 승인되지 않았다"
        mo.write({"control_plan_id": plan.id})
        return plan

    def _ensure_quality_basis(self, mo):
        """이 MO 가 정상 완료될 수 있도록 승인된 관리계획·검사를 갖춘다.

        게이트가 없으면 **아무것도 하지 않는다**. 있으면 전부 정상 API 로 만든다."""
        if not self._quality_gate_installed():
            return False
        actors = getattr(self, "_quality_actors", None) or {}
        planner = actors.get("planner")
        approver = actors.get("approver")
        inspector = actors.get("inspector")
        if not (planner and approver and inspector):
            return False

        plan = self._approve_control_plan(mo)
        self.assertTrue(plan, "합성 관리계획을 갖추지 못했다")

        # 검사 준비는 **실제 생산 LOT** 를 요구한다. 추적 제품이면 먼저 지정한다.
        if mo.product_id.tracking != "none" and not mo.lot_producing_id:
            mo.lot_producing_id = self.env["stock.lot"].sudo().create({
                "name": "QB-LOT-%s" % mo.id, "product_id": mo.product_id.id,
                "company_id": company.id}).id
        mo.action_prepare_required_quality()
        for inspection in mo.pqc_inspection_ids.with_user(inspector):
            inspection.write({
                "inspector_id": inspector.id,
                "quantity_inspected": 1, "quantity_accepted": 1,
                "quantity_rejected": 0, "result": "pass"})
            inspection.line_ids.write(
                {"measured_value": "합성: 균열 없음", "result": "pass"})
            inspection.action_decide()
            inspection.write({"approval_line_ids": [Command.create(
                {"sequence": 10, "user_id": approver.id})]})
            inspection.action_submit_approval()
            inspection.approval_request_id.with_user(approver).action_approve(
                expected_line_id=inspection.approval_request_id.current_line_id.id)
        return True
