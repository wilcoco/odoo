"""478 #30 — 레이아웃 검사: 미측정이 합격으로 집계되지 않는다."""
from odoo import Command
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLayoutGuards(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.product = cls.env["product.product"].create({"name": "478A 레이아웃 품목"})
        cls.Inspection = cls.env["iatf.layout.inspection"]

    def _inspection(self, **line):
        values = dict(characteristic_name="치수1", nominal="10", tolerance="±0.1")
        values.update(line)
        return self.Inspection.create({
            "title": "478A 레이아웃 시험",
            "product_id": self.product.id,
            "line_ids": [Command.create(values)],
        })

    def _decided(self):
        """판정 완료 상태의 정상 기록 하나."""
        rec = self._inspection(measured_value="10.02", result="pass")
        rec.result = "pass"
        rec.action_start()
        rec.action_decide()
        return rec

    def test_unmeasured_is_pending_not_pass(self):
        rec = self._inspection()
        self.assertEqual(rec.line_ids.result, "pending", "새 항목은 미판정이어야 한다")
        self.assertEqual(rec.pass_count, 0)
        self.assertEqual(rec.pending_count, 1)
        rec.result = "pass"
        rec.action_start()
        with self.assertRaises(UserError):
            rec.action_decide()

    def test_measured_pass_counts_and_decide(self):
        rec = self._inspection(measured_value="10.02", result="pass")
        self.assertEqual((rec.pass_count, rec.pending_count), (1, 0))
        rec.result = "pass"
        rec.action_start()
        rec.action_decide()
        self.assertEqual(rec.state, "decided")

    def test_pass_without_measurement_rejected(self):
        """측정값 없는 '합격' 은 **저장**에서 막힌다 (511 §2·§6(b)).

        전에는 저장을 허용하고 판정 시점에만 막았습니다. 사양은 저장 거부를
        요구합니다(아스트라 A-30-S01). 저장 가드와 판정 가드는 **두 층**이므로
        둘 다 확인합니다.
        """
        # 1층 — 저장 거부
        with self.assertRaises(ValidationError):
            self._inspection(result="pass")
        # 2층 — 설정을 끄면 저장은 되지만 판정은 여전히 막힌다
        self.env["ir.config_parameter"].sudo().set_param(
            "quality.layout_pass_needs_measurement", "0")
        rec = self._inspection(result="pass")
        rec.result = "pass"
        rec.action_start()
        with self.assertRaises(UserError):
            rec.action_decide()

    def test_clearing_measurement_of_a_pass_line_rejected(self):
        """정상 합격 행의 측정값을 나중에 지우는 길도 막는다."""
        rec = self._inspection(measured_value="10.02", result="pass")
        with self.assertRaises(ValidationError):
            rec.line_ids.measured_value = ""

    def test_na_line_needs_no_measurement(self):
        """해당없음은 측정값이 없어도 저장된다 (정상 대조)."""
        rec = self._inspection(result="na")
        self.assertTrue(rec.id)

    def test_fail_line_blocks_overall_pass(self):
        rec = self._inspection(measured_value="10.5", result="fail")
        rec.result = "pass"
        rec.action_start()
        with self.assertRaises(UserError):
            rec.action_decide()
        rec.result = "fail"
        rec.action_decide()
        self.assertEqual(rec.state, "decided")

    def test_locked_after_decide_and_reopen_needs_reason(self):
        rec = self._inspection(measured_value="10.02", result="pass")
        rec.result = "pass"
        rec.action_start()
        rec.action_decide()
        with self.assertRaises(UserError):
            rec.result = "fail"
        with self.assertRaises(UserError):
            rec.action_reopen()
        rec.action_reopen(reason="측정 오기 정정")
        self.assertEqual(rec.state, "inspecting")

    def test_close_requires_decided(self):
        rec = self._inspection(measured_value="10.02", result="pass")
        rec.result = "pass"
        with self.assertRaises(UserError):
            rec.action_close()

    # ── 아스트라 A-01 반례 회귀 ──────────────────────────────────
    def test_same_state_in_vals_does_not_unlock(self):
        """상태를 같은 값으로 함께 써도 잠금은 풀리지 않는다."""
        rec = self._decided()
        with self.assertRaises(UserError):
            rec.write({"result": "fail"})
        with self.assertRaises(UserError):
            rec.write({"state": "decided", "result": "fail"})
        with self.assertRaises(UserError):
            rec.write({"state": rec.state, "line_ids": [(5, 0, 0)]})

    def test_action_start_cannot_revert_decided(self):
        """판정 완료를 '검사 시작' 으로 되돌릴 수 없다."""
        rec = self._decided()
        with self.assertRaises(UserError):
            rec.action_start()
        rec.action_reopen(reason="측정 오기재 정정")
        self.assertEqual(rec.state, "inspecting")

    def test_child_line_cannot_be_edited_after_decide(self):
        """항목을 직접 고쳐 잠금을 지나갈 수 없다."""
        rec = self._decided()
        line = rec.line_ids[:1]
        with self.assertRaises(UserError):
            line.write({"result": "fail"})
        with self.assertRaises(UserError):
            line.unlink()
        with self.assertRaises(UserError):
            self.env["iatf.layout.inspection.line"].create({
                "inspection_id": rec.id, "characteristic_name": "추가 항목",
            })

    # ── 아스트라 A-01-R1 / R2 반례 회귀 ──────────────────────────
    def test_state_only_reversal_is_blocked(self):
        """상태만 되돌려 잠금을 푸는 길을 막는다."""
        rec = self._decided()
        with self.assertRaises(UserError):
            rec.write({"state": "inspecting"})
        self.assertEqual(rec.state, "decided")
        # 정상 경로: 종료는 허용, 재검토는 사유와 함께
        rec.action_close()
        self.assertEqual(rec.state, "closed")
        with self.assertRaises(UserError):
            rec.write({"state": "inspecting"})
        rec.action_reopen(reason="측정 오기재 정정")
        self.assertEqual(rec.state, "inspecting")
        rec.line_ids.measured_value = "10.03"

    def test_line_cannot_be_moved_into_decided_inspection(self):
        """열린 검사의 항목을 판정 완료 검사로 옮길 수 없다."""
        decided = self._decided()
        open_one = self._inspection(measured_value="9.99", result="pass")
        line = open_one.line_ids[:1]
        with self.assertRaises(UserError):
            line.write({"inspection_id": decided.id})
        # 정상 대조: 열린 검사끼리는 옮길 수 있다
        other_open = self._inspection(measured_value="10.01", result="pass")
        line.write({"inspection_id": other_open.id})
        self.assertEqual(line.inspection_id, other_open)

    def test_empty_state_write_is_blocked(self):
        """상태를 빈값으로 써서 잠금을 비우는 길도 막는다."""
        rec = self._decided()
        with self.assertRaises(UserError):
            rec.write({"state": False})
        self.assertEqual(rec.state, "decided")
        with self.assertRaises(UserError):
            rec.write({"state": ""})
        self.assertEqual(rec.state, "decided")
