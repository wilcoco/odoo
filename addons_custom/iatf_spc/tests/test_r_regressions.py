"""제3자 재검토(2026-09-10) R06·R07 회귀 — 부분군 수기/자동 혼재, 완성군 기준."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSubgroupR06(TransactionCase):

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "R-SPC품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "R-SPC", "product_id": product.id,
            "characteristic_name": "두께", "subgroup_size": 5})
        self.SG = self.env["iatf.spc.subgroup"]

    def test_r06_manual_values_are_counted(self):
        """자동 표본 1개 뒤 수기로 x2~x5 를 채우면 통계에 들어가야 한다.

        `sample_count` 는 자동 주입이 관리하는 숫자라 수기 입력으로는 올라가지 않는다.
        그것만 믿으면 사람이 넣은 값이 통계에서 통째로 빠진다.
        """
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "sample_count": 1})
        self.assertEqual(sg.sg_mean, 10.0)
        sg.write({"x2": 12.0, "x3": 8.0, "x4": 10.0, "x5": 10.0})
        self.assertEqual(sg.sg_mean, 10.0, "수기 입력분이 평균에 반영되지 않았다")
        self.assertEqual(sg.sg_range, 4.0)
        self.assertTrue(sg.is_complete)

    def test_r06_next_free_slot_skips_manual_values(self):
        """다음 자동 주입은 수기로 채운 칸을 건너뛴다 — 덮어쓰지 않는다."""
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "sample_count": 1})
        sg.write({"x2": 12.0})
        self.assertEqual(sg._next_free_slot(), 3, "x2 가 채워졌는데 그 칸을 가리킨다")
        self.assertEqual(sg._filled_count(), 2)

    def test_r07_incomplete_subgroup_is_flagged(self):
        sg = self.SG.create({"study_id": self.study.id, "x1": 20.0, "sample_count": 1})
        self.assertFalse(sg.is_complete)


@tagged("post_install", "-at_install")
class TestStudyCompletenessR07(TransactionCase):
    """R07 — 미완성 부분군이 관리한계·공정능력을 왜곡하던 문제."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "R-SPC품2"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "R-SPC2", "product_id": product.id,
            "characteristic_name": "두께", "subgroup_size": 5})
        self.SG = self.env["iatf.spc.subgroup"]

    def _complete(self, seq, vals):
        return self.SG.create(dict({"study_id": self.study.id, "sequence": seq,
                                    "sample_count": 5}, **vals))

    def test_r07_incomplete_subgroup_excluded_from_limits(self):
        """완성군(평균10·범위4) 과 1개만 모인 군(20) 을 함께 분석해도 결과가 왜곡되지 않는다.

        재검토 재현: 전체 평균 15 / 평균범위 2 가 나왔다 — 1개짜리 군의 범위 0 이
        평균 범위를 반토막 내고, 평균은 20 쪽으로 끌려갔다.
        """
        self._complete(10, {"x1": 8.0, "x2": 12.0, "x3": 10.0, "x4": 10.0, "x5": 10.0})
        self.SG.create({"study_id": self.study.id, "sequence": 20,
                        "x1": 20.0, "sample_count": 1})
        self.study.action_calculate()
        self.assertEqual(self.study.grand_mean, 10.0, "미완성군이 평균을 끌어갔다")
        self.assertEqual(self.study.mean_range, 4.0, "미완성군의 범위 0 이 섞였다")
        self.assertEqual(self.study.incomplete_subgroup_count, 1)

    def test_r07_no_complete_subgroup_blocks_analysis(self):
        """완성군이 하나도 없으면 계산하지 않는다 — 0 으로 채운 한계는 착각만 준다."""
        self.SG.create({"study_id": self.study.id, "sequence": 10,
                        "x1": 20.0, "sample_count": 1})
        with self.assertRaises(UserError):
            self.study.action_calculate()


@tagged("post_install", "-at_install")
class TestZeroSampleAstra1(TransactionCase):
    """아스트라 재검토 ① — 유효 측정 0 과 미입력을 구분한다."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "A-SPC품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "A-SPC", "product_id": product.id,
            "characteristic_name": "편차", "subgroup_size": 5})
        self.SG = self.env["iatf.spc.subgroup"]

    def test_explicit_zero_is_a_measurement(self):
        """유효 측정 0 은 측정값이다 — 빈칸으로 보고 덮으면 안 된다.

        Float 은 미입력과 0.0 을 구분하지 못하므로, 0 을 살리려면 표본 수를 말해야 한다.
        `sample_count=1` 이 "첫 칸은 실제로 입력했다" 는 뜻이다.
        """
        sg = self.SG.create({"study_id": self.study.id, "x1": 0.0, "sample_count": 1})
        self.assertEqual(sg._filled_set(), {1})
        self.assertEqual(sg._next_free_slot(), 2, "유효 측정 0 인 칸을 빈칸으로 봤다")
        self.assertEqual(sg._get_values(), [0.0])
        self.assertEqual(sg.sg_mean, 0.0)
        self.assertFalse(sg.is_complete)

    def test_empty_subgroup_is_not_complete(self):
        """아무것도 입력하지 않은 부분군이 '0 이 n 개' 로 완성군이 되면 안 된다."""
        sg = self.SG.create({"study_id": self.study.id})
        self.assertEqual(sg._get_values(), [])
        self.assertFalse(sg.is_complete)
        self.assertEqual(sg.sg_mean, 0.0)
        self.assertEqual(sg.sg_range, 0.0)

    def test_middle_gap_is_preserved(self):
        """중간 빈칸 — x5 만 넣으면 x1~x4 의 0 이 표본으로 섞이지 않는다."""
        sg = self.SG.create({"study_id": self.study.id, "x5": 12.0})
        self.assertEqual(sg._filled_set(), {5})
        self.assertEqual(sg._get_values(), [12.0])
        self.assertEqual(sg.sg_mean, 12.0)
        self.assertEqual(sg._next_free_slot(), 1, "앞의 빈칸부터 채워야 한다")

    def test_manual_and_auto_mix(self):
        """수기 + 자동 혼합 — 자동은 빈칸만 쓰고, 통계는 입력분 전부를 센다."""
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "sample_count": 1})
        sg.write({"x2": 14.0, "sample_count": 2})      # 자동이 다음 빈칸을 채움
        self.assertEqual(sg._filled_set(), {1, 2})
        self.assertEqual(sg._next_free_slot(), 3)
        sg.write({"x3": 0.0, "sample_count": 3})       # 수기로 유효 0 입력
        self.assertEqual(sorted(sg._get_values()), [0.0, 10.0, 14.0])
        self.assertEqual(sg._filled_count(), 3)
        self.assertEqual(sg._next_free_slot(), 4)

    def test_nonzero_value_counts_even_without_sample_count(self):
        """표본 수를 안 올려도 값이 든 칸은 통계에 들어간다 — 수기 입력 구제."""
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "x2": 12.0})
        self.assertEqual(sg._filled_set(), {1, 2})
        self.assertEqual(sg.sg_mean, 11.0)


@tagged("post_install", "-at_install")
class TestAstraRepro1Mask(TransactionCase):
    """아스트라 독립재현 ① — 입력 칸(구간)과 입력 수(개수)를 섞지 않는다."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "A1-마스크품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "A1-마스크", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 5, "state": "collecting"})

    def _sg(self, **vals):
        return self.env["iatf.spc.subgroup"].create(
            dict({"study_id": self.study.id, "sequence": 10}, **vals))

    def test_mask_is_written_on_create(self):
        sg = self._sg(sample_count=1, x1=10.0, x5=15.0)
        self.assertEqual(sg.filled_mask, "1,5")

    def test_ui_payload_of_untouched_zero_slots_is_not_input(self):
        """폼이 함께 보내는, 값이 그대로인 빈 칸은 입력으로 세지 않는다."""
        sg = self._sg(sample_count=1, x1=10.0)
        sg.write({f: 0.0 for f in ("x2", "x3", "x4", "x5")})
        self.assertEqual(sg._filled_set(), {1})
        self.assertEqual(sg._get_values(), [10.0])

    def test_deliberate_zero_edit_counts_as_input(self):
        """값을 실제로 0 으로 고친 칸은 측정값 0 이다."""
        sg = self._sg(sample_count=2, x1=10.0, x2=4.0)
        sg.write({"x2": 0.0})
        self.assertEqual(sg._filled_set(), {1, 2})
        self.assertEqual(sg._get_values(), [10.0, 0.0])

    def test_sample_count_still_declares_a_leading_range(self):
        """사람이 '앞에서부터 3 칸' 이라고 말하면 그 안의 0 은 측정값이다."""
        sg = self._sg(x1=10.0)
        sg.write({"sample_count": 3})
        self.assertEqual(sg._filled_set(), {1, 2, 3})
        self.assertEqual(sg._get_values(), [10.0, 0.0, 0.0])

    def test_record_measurement_marks_only_that_slot(self):
        sg = self._sg(sample_count=1, x1=10.0, x5=15.0)
        sg._record_measurement(sg._next_free_slot(), 12.0, origin="t:1")
        self.assertEqual(sorted(sg._filled_set()), [1, 2, 5])
        self.assertEqual(sg.sample_count, 1, "구간 값이 개수로 덮여 썼다")
        self.assertIn("t:1", (sg.origins or "").split(","))

    def test_legacy_row_without_mask_uses_old_rule(self):
        """이 변경 이전 자료(입력 칸을 알 수 없음)는 예전 규칙으로 읽는다."""
        sg = self._sg(sample_count=2, x1=10.0, x2=12.0)
        self.env.cr.execute(
            "UPDATE iatf_spc_subgroup SET filled_mask = NULL WHERE id = %s", (sg.id,))
        sg.invalidate_recordset()
        self.assertFalse(sg.filled_mask)
        self.assertEqual(sg._filled_set(), {1, 2})


@tagged("post_install", "-at_install")
class TestInputSlotValidation(TransactionCase):
    """아스트라 후속 — 입력 칸 정본과 군 크기가 실제로 존재하는 칸만 가리키는지."""

    def setUp(self):
        super().setUp()
        self.product = self.env["product.product"].create({"name": "V-검증품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "V-검증", "product_id": self.product.id,
            "characteristic_name": "치수", "subgroup_size": 5, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]

    def test_subgroup_size_beyond_ten_is_refused(self):
        """칸이 10 개뿐인데 n=12 면 어떤 부분군도 완성군이 될 수 없다."""
        with self.assertRaises(ValidationError):
            self.env["iatf.spc.study"].create({
                "title": "V-과대", "product_id": self.product.id,
                "characteristic_name": "치수", "subgroup_size": 12})
        with self.assertRaises(ValidationError):
            self.study.write({"subgroup_size": 11})

    def test_sample_count_beyond_subgroup_size_is_refused(self):
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "sample_count": 6})

    def test_mask_pointing_at_a_missing_slot_is_refused(self):
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "filled_mask": "1,7"})
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0})
        with self.assertRaises(ValidationError):
            sg.write({"filled_mask": "1,0"})

    def test_garbage_mask_is_refused(self):
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "filled_mask": "1,x"})

    def test_duplicate_slot_in_mask_is_refused(self):
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "filled_mask": "1,1,2"})

    def test_value_outside_the_subgroup_size_is_not_marked(self):
        """n=5 인데 x7 에 값이 있으면 예전처럼 통계에서 빠진다(mask 도 오염되지 않는다)."""
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "x7": 99.0})
        self.assertEqual(sg._filled_set(), {1})
        self.assertEqual(sg._get_values(), [10.0])
        self.assertEqual(sg.filled_mask, "1")


@tagged("post_install", "-at_install")
class TestSampleCountCheckedBeforeAllocation(TransactionCase):
    """아스트라 독립재현 2026-09-10 18:48 — 범위 검사가 할당보다 **먼저** 와야 한다.

    예전에는 `set(range(1, sample_count + 1))` 을 먼저 만들고 잘라 냈고, 범위 검사는
    `@api.constrains` 라 create 가 끝난 뒤에야 돌았다. 큰 정수 하나로 그 사이에
    거대한 집합을 실제로 할당하게 만들 수 있었다.

    **거대한 값을 실제로 할당시키지 않는다.** 조기 ValidationError 와 '집합을 만드는
    헬퍼가 불리지 않았다' 는 것으로 확인한다.
    """

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "A-조기검사품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "A-조기검사", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 5, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]

    def _watch_allocation(self):
        """집합을 만드는 헬퍼가 불리면 표시를 남긴다."""
        calls = []
        original = type(self.SG)._marked_from_vals

        def spy(inner_self, vals, base):
            calls.append(vals.get("sample_count"))
            return original(inner_self, vals, base)

        self.patch(type(self.SG), "_marked_from_vals", spy)
        return calls

    def test_huge_sample_count_is_refused_before_any_set_is_built(self):
        calls = self._watch_allocation()
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "sample_count": 10 ** 9})
        self.assertEqual(calls, [], "범위를 벗어난 값으로 집합을 만드는 헬퍼가 불렸다")

    def test_huge_sample_count_on_write_is_refused_before_allocation(self):
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0})
        calls = self._watch_allocation()
        with self.assertRaises(ValidationError):
            sg.write({"sample_count": 10 ** 9})
        self.assertEqual(calls, [])
        sg.invalidate_recordset()
        self.assertEqual(sg.sample_count, 0)

    def test_non_integer_sample_count_is_refused(self):
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "sample_count": "abc"})

    def test_valid_sample_count_still_goes_through_the_helper(self):
        calls = self._watch_allocation()
        sg = self.SG.create({"study_id": self.study.id, "sample_count": 3})
        self.assertEqual(calls, [3])
        self.assertEqual(sg.filled_mask, "1,2,3")


@tagged("post_install", "-at_install")
class TestLegacyExcludedFromNewAnalysis(TransactionCase):
    """아스트라 후속 — 근거불명 과거 군은 **새 분석**에서만 뺀다.

    원자료와 이미 저장된 보고값은 보존한다. 재분석은 사용자가 명시 실행한다.
    """

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "L-분석품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "L-분석", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 3, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]

    def _sg(self, seq, a, b, c, legacy=False):
        sg = self.SG.create({
            "study_id": self.study.id, "sequence": seq,
            "sample_count": 3, "x1": a, "x2": b, "x3": c})
        if legacy:
            # 이 변경 이전에 저장된 기록 — 어느 칸을 입력했는지 알 수 없다
            self.env.cr.execute(
                "UPDATE iatf_spc_subgroup SET filled_mask = NULL WHERE id = %s", (sg.id,))
            sg.invalidate_recordset()
            sg.modified(["filled_mask"])
            sg.flush_recordset()
        return sg

    def test_legacy_subgroup_is_complete_but_not_analyzable(self):
        legacy = self._sg(10, 10.0, 11.0, 12.0, legacy=True)
        self.assertTrue(legacy.is_complete, "원자료 판정 자체는 그대로여야 한다")
        self.assertFalse(legacy.basis_known)
        self.assertFalse(legacy.is_analyzable)
        self.assertEqual(legacy._get_values(), [10.0, 11.0, 12.0],
                         "원자료를 읽는 방식까지 바꾸면 안 된다")

    def test_control_limits_ignore_legacy_subgroups(self):
        self._sg(10, 10.0, 10.0, 10.0, legacy=True)   # 근거불명 — 빠져야 한다
        self._sg(20, 20.0, 22.0, 24.0)
        self._sg(30, 20.0, 22.0, 24.0)
        self.study.action_calculate()
        self.assertAlmostEqual(self.study.grand_mean, 22.0, places=4,
                               msg="근거불명 군이 관리한계 계산에 들어갔다")
        self.assertEqual(self.study.unknown_basis_subgroup_count, 1)
        self.assertIn("근거불명", self.study.excluded_reason_note)

    def test_note_says_nothing_was_excluded_when_all_are_sound(self):
        self._sg(10, 20.0, 22.0, 24.0)
        self._sg(20, 20.0, 22.0, 24.0)
        self.study.action_calculate()
        self.assertEqual(self.study.unknown_basis_subgroup_count, 0)
        self.assertIn("제외 없음", self.study.excluded_reason_note)

    def test_only_legacy_groups_means_a_clear_refusal(self):
        self._sg(10, 10.0, 11.0, 12.0, legacy=True)
        with self.assertRaises(UserError) as caught:
            self.study.action_calculate()
        self.assertIn("입력 칸 미기록", str(caught.exception))

    def test_stored_ooc_of_a_legacy_group_is_not_overwritten(self):
        legacy = self._sg(10, 10.0, 10.0, 10.0, legacy=True)
        legacy.is_ooc = True                 # 예전 분석이 남긴 보고값
        self._sg(20, 20.0, 22.0, 24.0)
        self._sg(30, 20.0, 22.0, 24.0)
        self.study.action_calculate()
        legacy.invalidate_recordset()
        self.assertTrue(legacy.is_ooc, "이미 저장된 보고값을 새 분석이 덮어썼다")


@tagged("post_install", "-at_install")
class TestAnalysisEligibilityCannotBeForged(TransactionCase):
    """아스트라 275 리뷰 Q275-04·05 — 자격 표시를 손으로 바꿔 제외를 우회할 수 없다."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "E-자격품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "E-자격", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 3, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]

    def _legacy(self, seq, a, b, c, count=3):
        sg = self.SG.create({
            "study_id": self.study.id, "sequence": seq,
            "sample_count": count, "x1": a, "x2": b, "x3": c})
        self.env.cr.execute(
            "UPDATE iatf_spc_subgroup SET filled_mask = NULL WHERE id = %s", (sg.id,))
        sg.invalidate_recordset()
        sg.modified(["filled_mask"])
        sg.flush_recordset()
        return sg

    def _sound(self, seq, a, b, c):
        return self.SG.create({
            "study_id": self.study.id, "sequence": seq,
            "sample_count": 3, "x1": a, "x2": b, "x3": c})

    # ── Q275-04 ──
    def test_writing_the_eligibility_flags_is_refused(self):
        legacy = self._legacy(10, 10.0, 11.0, 12.0)
        for vals in ({"basis_known": True}, {"is_analyzable": True},
                     {"analysis_state": "analyzed"}, {"is_complete": True}):
            with self.assertRaises(ValidationError):
                legacy.write(vals)

    def test_calculation_re_derives_eligibility_from_the_raw_data(self):
        """저장 컬럼을 SQL 로 직접 뒤집어도 계산은 원자료로 다시 판정한다."""
        legacy = self._legacy(10, 100.0, 100.0, 100.0)
        self._sound(20, 20.0, 22.0, 24.0)
        self._sound(30, 20.0, 22.0, 24.0)
        self.env.cr.execute(
            "UPDATE iatf_spc_subgroup SET basis_known = true, is_analyzable = true "
            "WHERE id = %s", (legacy.id,))
        legacy.invalidate_recordset()
        self.assertTrue(legacy.is_analyzable, "시험 전제: 저장값은 뒤집혀 있다")
        self.study.action_calculate()
        self.assertAlmostEqual(self.study.grand_mean, 22.0, places=4,
                               msg="저장된 자격 표시를 믿고 근거불명 군을 분석에 넣었다")
        self.assertEqual(self.study.unknown_basis_subgroup_count, 1)

    # ── Q275-05 ──
    def test_rewriting_the_same_value_does_not_confirm_the_basis(self):
        """미상 자료를 같은 값으로 다시 저장한다고 근거가 생기지는 않는다."""
        legacy = self._legacy(10, 10.0, 0.0, 0.0, count=3)
        self.assertFalse(legacy.basis_known)
        legacy.write({"x1": 10.0})
        legacy.invalidate_recordset()
        self.assertFalse(legacy.filled_mask, "단순 저장이 추정 집합을 근거로 승격시켰다")
        self.assertFalse(legacy.basis_known)
        self.assertEqual(legacy.analysis_state, "excluded_unknown")

    def test_auto_injection_refuses_a_basis_unknown_subgroup(self):
        legacy = self._legacy(10, 10.0, 0.0, 0.0, count=1)
        with self.assertRaises(ValidationError):
            legacy._record_measurement(2, 12.0, origin="t:1")

    def test_explicit_confirmation_promotes_and_records_who(self):
        legacy = self._legacy(10, 10.0, 11.0, 12.0)
        legacy.action_confirm_input_slots()
        legacy.invalidate_recordset()
        self.assertEqual(legacy.filled_mask, "1,2,3")
        self.assertTrue(legacy.basis_known)
        self.assertEqual(legacy.basis_confirmed_by_id, self.env.user)
        self.assertTrue(legacy.basis_confirmed_at)

    def test_confirmation_is_refused_when_nothing_was_stated(self):
        legacy = self._legacy(10, 0.0, 0.0, 0.0, count=0)
        with self.assertRaises(UserError):
            legacy.action_confirm_input_slots()

    def test_confirmation_is_refused_on_an_already_recorded_subgroup(self):
        sound = self._sound(10, 20.0, 22.0, 24.0)
        with self.assertRaises(UserError):
            sound.action_confirm_input_slots()

    # ── Q275-06 ──
    def test_analysis_state_separates_past_from_present(self):
        legacy = self._legacy(10, 100.0, 100.0, 100.0)
        sound = self._sound(20, 20.0, 22.0, 24.0)
        self._sound(30, 20.0, 22.0, 24.0)
        legacy.sudo().write({"is_ooc": True})     # 예전 분석이 남긴 보고값
        self.study.action_calculate()
        legacy.invalidate_recordset()
        self.assertEqual(legacy.analysis_state, "excluded_unknown")
        self.assertEqual(sound.analysis_state, "analyzed")
        self.assertTrue(legacy.is_ooc, "과거 판정을 지웠다")
        self.assertEqual(self.study.ooc_count, 0,
                         "과거 이탈이 이번 분석 건수에 섞였다")


@tagged("post_install", "-at_install")
class TestInputBasisEvidenceIsServerOwned(TransactionCase):
    """아스트라 305 품질 리뷰 (1)(4) — 근거와 확인 증거는 서버가 확정한다."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "S-근거품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "S-근거", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 3, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]

    def _legacy(self, seq=10):
        sg = self.SG.create({"study_id": self.study.id, "sequence": seq,
                             "sample_count": 3, "x1": 10.0, "x2": 11.0, "x3": 12.0})
        self.env.cr.execute(
            "UPDATE iatf_spc_subgroup SET filled_mask = NULL WHERE id = %s", (sg.id,))
        sg.invalidate_recordset()
        sg.modified(["filled_mask"])
        sg.flush_recordset()
        return sg

    def test_writing_filled_mask_directly_is_refused(self):
        legacy = self._legacy()
        with self.assertRaises(ValidationError):
            legacy.write({"filled_mask": "1,2,3"})
        legacy.invalidate_recordset()
        self.assertFalse(legacy.basis_known, "직접 쓴 mask 로 근거가 생겼다")

    def test_forging_the_confirmation_evidence_is_refused(self):
        legacy = self._legacy()
        with self.assertRaises(ValidationError):
            legacy.write({"basis_confirmed_by_id": self.env.user.id})
        with self.assertRaises(ValidationError):
            legacy.write({"basis_confirmed_at": "2026-09-09 00:00:00"})

    def test_creating_a_subgroup_with_a_handed_mask_is_refused(self):
        """조용히 버리지 않고 거절한다 — 무엇이 무시됐는지 모르는 편이 더 나쁘다."""
        with self.assertRaises(ValidationError):
            self.SG.create({"study_id": self.study.id, "sequence": 20,
                            "filled_mask": "1,2,3"})

    def test_confirmation_recomputes_only_that_rows_statistics(self):
        """(4) 확인은 **그 행의** 통계를 다시 계산한다. 연구의 저장 결과는 그대로다.

        입력 칸이 정해져야 어떤 값이 통계에 들어가는지가 정해지므로, 그 행의 평균·범위가
        따라 바뀌는 것은 의도한 동작이다. 반면 연구의 관리한계·Cp 는 사용자가
        `action_calculate` 를 눌러야만 바뀐다.
        """
        legacy = self._legacy()
        sound_a = self.SG.create({"study_id": self.study.id, "sequence": 30,
                                  "sample_count": 3, "x1": 20.0, "x2": 22.0, "x3": 24.0})
        self.SG.create({"study_id": self.study.id, "sequence": 40,
                        "sample_count": 3, "x1": 20.0, "x2": 22.0, "x3": 24.0})
        self.study.action_calculate()
        before_mean = self.study.grand_mean
        before_ucl = self.study.ucl_xbar
        self.assertAlmostEqual(before_mean, 22.0, places=4)

        legacy.action_confirm_input_slots()
        legacy.invalidate_recordset()
        self.study.invalidate_recordset()

        self.assertTrue(legacy.basis_known)
        self.assertAlmostEqual(legacy.sg_mean, 11.0, places=4,
                               msg="확인 뒤에도 그 행의 통계가 옛 값이다")
        self.assertAlmostEqual(sound_a.sg_mean, 22.0, places=4)
        # 연구의 저장 결과는 사용자가 다시 계산하기 전까지 그대로다
        self.assertAlmostEqual(self.study.grand_mean, before_mean, places=4,
                               msg="확인만으로 연구의 분석 결과가 바뀌었다")
        self.assertAlmostEqual(self.study.ucl_xbar, before_ucl, places=4)

        self.study.action_calculate()
        self.assertAlmostEqual(self.study.grand_mean, (11.0 + 22.0 + 22.0) / 3.0,
                               places=4, msg="명시 재계산 뒤에도 반영되지 않았다")


@tagged("post_install", "-at_install")
class TestNoContextBackdoorForBasis(TransactionCase):
    """아스트라 445 품질 리뷰 (1) — context Boolean 으로 근거 가드를 열 수 없다."""

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "B-뒷문품"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "B-뒷문", "product_id": product.id,
            "characteristic_name": "치수", "subgroup_size": 3, "state": "collecting"})
        self.SG = self.env["iatf.spc.subgroup"]
        self.user = self.env["res.users"].create({
            "name": "B-SPC담당", "login": "b_spc_user",
            "groups_id": [(6, 0, [self.env.ref("base.group_user").id,
                                  self.env.ref("iatf_spc.group_spc_user").id])]})

    def _legacy(self):
        sg = self.SG.create({"study_id": self.study.id, "sequence": 10,
                             "sample_count": 3, "x1": 10.0, "x2": 11.0, "x3": 12.0})
        self.env.cr.execute(
            "UPDATE iatf_spc_subgroup SET filled_mask = NULL WHERE id = %s", (sg.id,))
        sg.invalidate_recordset()
        sg.modified(["filled_mask"])
        sg.flush_recordset()
        return sg

    def test_context_flag_does_not_open_the_write_guard(self):
        legacy = self._legacy()
        for vals in ({"filled_mask": "1,2,3"},
                     {"basis_confirmed_by_id": self.env.user.id},
                     {"basis_confirmed_at": "2026-09-09 00:00:00"}):
            with self.assertRaises(ValidationError):
                legacy.with_user(self.user).with_context(
                    iatf_spc_internal_write=True).write(vals)
        legacy.invalidate_recordset()
        self.assertFalse(legacy.basis_known)

    def test_context_defaults_do_not_open_the_create_guard(self):
        with self.assertRaises(ValidationError):
            self.SG.with_user(self.user).with_context(
                iatf_spc_internal_write=True,
                default_filled_mask="1,2,3").create(
                    {"study_id": self.study.id, "sequence": 20, "x1": 10.0})
        with self.assertRaises(ValidationError):
            self.SG.with_user(self.user).with_context(
                iatf_spc_internal_write=True).create({
                    "study_id": self.study.id, "sequence": 21,
                    "basis_confirmed_by_id": self.env.user.id})

    def test_the_normal_zero_measurement_contract_still_works(self):
        """정상 계약은 유지 — 자동 주입의 실측 0 이 살아 있어야 한다."""
        sg = self.SG.create({"study_id": self.study.id, "sequence": 30,
                             "sample_count": 1, "x1": 0.0})
        self.assertEqual(sg.filled_mask, "1")
        self.assertEqual(sg._get_values(), [0.0])
        sg._record_measurement(2, 5.0, origin="t:9")
        sg.invalidate_recordset()
        self.assertEqual(sorted(sg._filled_set()), [1, 2])
        self.assertEqual(sg._get_values(), [0.0, 5.0])
