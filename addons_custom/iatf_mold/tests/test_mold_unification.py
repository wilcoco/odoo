from odoo import Command
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install")
class TestMoldMasterUnification(TransactionCase):
    """금형 마스터 단일화 (18.0.2.0.0): iatf.mold 폐지 → injection.mold 하나.

    ① 별도 IATF 금형 모델이 없다 — 현장·계획이 쓰는 금형에 SQ 기록이 직접 붙는다
    ② 생산이 자동으로 바꾸는 값은 금형 대장 결재를 풀지 않는다, 기준값은 푼다
    ③ 폐기 = 생산계획의 retired — 사용 중 금형 목록에서 빠진다
    ④ 코드 없이 만들면 예전 대장 채번, 코드가 있으면 그 코드를 쓴다
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        groups = "base.group_user,iatf_mold.group_mold_user"
        cls.author = new_test_user(cls.env, login="mold-unify-author", groups=groups)
        cls.approver = new_test_user(cls.env, login="mold-unify-approver", groups=groups)
        cls.Mold = cls.env["injection.mold"]

    def test_no_separate_iatf_mold_model(self):
        self.assertNotIn("iatf.mold", self.env, "IATF 금형 대장이 별도 모델로 남아 있으면 이중 입력이 생긴다")
        for model in ("iatf.mold.check", "iatf.mold.temp.log", "iatf.mold.tryout",
                      "iatf.mold.maintenance", "iatf.mold.check.snapshot"):
            self.assertEqual(self.env[model]._fields["mold_id"].comodel_name, "injection.mold", model)
        self.assertEqual(self.env["mrp.production"]._fields["mold_id"].comodel_name, "injection.mold")

    def test_sq_records_attach_to_planning_mold(self):
        """생산계획·사출기-금형 조합이 쓰는 금형 그 자체에 점검·시사출이 붙는다."""
        mold = self.Mold.create({"code": "U-MLD-001", "name": "U-통합금형", "cavity_count": 2,
                                 "grade": "a", "check_cycle_days": 1, "clean_cycle_days": 180,
                                 "preheat_temp_min": 40.0, "preheat_temp_max": 60.0,
                                 "mold_temp_min": 50.0, "mold_temp_max": 70.0})
        self.assertTrue(mold.is_standard_ready, mold.standard_missing)
        tryout = self.env["iatf.mold.tryout"].create({"mold_id": mold.id, "reason": "new"})
        temp = self.env["iatf.mold.temp.log"].create({"mold_id": mold.id, "log_type": "preheat",
                                                       "temperature": 65.0})
        self.assertIn(tryout, mold.tryout_ids)
        self.assertEqual(temp.spec_result, "ng", "예열 상한 60℃ 초과")
        self.assertIn(mold, self.Mold.search([("state", "=", "active"), ("code", "=", "U-MLD-001")]),
                      "생산계획이 찾는 사용 중 금형과 같은 레코드")

    def _approved_mold(self):
        mold = self.Mold.with_user(self.author).create({
            "code": "U-MLD-APR", "name": "U-결재금형", "grade": "b",
            "approval_line_ids": [Command.create({"sequence": 10, "user_id": self.approver.id})]})
        mold.action_submit_approval()
        mold.with_user(self.approver).action_approve_approval()
        self.assertEqual(mold.approval_state, "approved")
        return mold

    def test_operational_writes_keep_approval(self):
        mold = self._approved_mold()
        mold.write({"current_shots": mold.current_shots + 10})
        mold.write({"x_planning_reservation_seq": mold.x_planning_reservation_seq + 1})
        mold.action_maintenance()
        mold.action_activate()
        self.assertEqual(mold.approval_state, "approved",
                         "샷 누적·계획 예약·운영 상태 전환은 대장 승인을 풀지 않는다")

    def test_standard_change_resets_approval(self):
        mold = self._approved_mold()
        mold.write({"check_cycle_days": 7})
        self.assertNotEqual(mold.approval_state, "approved", "관리기준이 바뀌면 다시 결재받는다")

    def test_dispose_maps_to_planning_retired(self):
        mold = self.Mold.create({"code": "U-MLD-DSP", "name": "U-폐기금형"})
        mold.action_dispose()
        self.assertEqual(mold.state, "retired")
        self.assertNotIn(mold, self.Mold.search([("state", "=", "active")]))

    def test_code_auto_numbering_only_when_blank(self):
        auto = self.Mold.create({"name": "U-코드없음"})
        self.assertTrue(auto.code and auto.code != "New", "코드 없이 만들면 MD- 채번")
        manual = self.Mold.create({"code": "U-MLD-KEEP", "name": "U-코드지정"})
        self.assertEqual(manual.code, "U-MLD-KEEP")

    def test_new_mold_registration_can_start_in_draft(self):
        mold = self.Mold.create({"code": "U-MLD-DRF", "name": "U-이관금형", "state": "draft"})
        self.assertFalse(mold.is_tryout_missing, "T/O 전 등록 상태는 누락으로 세지 않는다")
        self.assertNotIn(mold, self.Mold.search([("state", "=", "active")]),
                         "등록 상태 금형은 생산계획 배정 대상이 아니다")
        mold.action_activate()
        self.assertTrue(mold.is_tryout_missing)
