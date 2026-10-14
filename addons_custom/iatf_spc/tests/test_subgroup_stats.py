from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSubgroupStats(TransactionCase):
    """부분군 통계 — 입력 표본 수 (제3자 검토 2026-09-10 Q14).

    이전 `_get_values` 의 `v != 0.0 or True` 는 항상 참이라, x1 하나만 넣은 부분군의
    x2~x5(0) 가 평균에 들어가 10.0 측정 하나가 평균 2.0 / 범위 10 으로 왜곡됐다.
    """

    def setUp(self):
        super().setUp()
        product = self.env["product.product"].create({"name": "T-SPC 품목"})
        self.study = self.env["iatf.spc.study"].create({
            "title": "T-SPC", "product_id": product.id,
            "characteristic_name": "두께", "subgroup_size": 5,
        })
        self.SG = self.env["iatf.spc.subgroup"]

    def test_single_auto_sample_is_not_averaged_with_zeros(self):
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "sample_count": 1})
        self.assertEqual(sg.sg_mean, 10.0, "10 하나면 평균 10 이어야지 2 가 아니다")
        self.assertEqual(sg.sg_range, 0.0)

    def test_partial_fill_uses_only_entered_samples(self):
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "x2": 12.0, "sample_count": 2})
        self.assertEqual(sg.sg_mean, 11.0)
        self.assertEqual(sg.sg_range, 2.0)
        sg.write({"x3": 8.0, "sample_count": 3})
        self.assertEqual(sg.sg_mean, 10.0)
        self.assertEqual(sg.sg_range, 4.0)

    def test_manual_full_subgroup_keeps_zero_as_a_value(self):
        """표본 수를 밝힌 완성군에서는 0 도 값이다.

        이 시험의 이전 판은 "sample_count 가 없으면 n 개 전부 입력된 것으로 본다" 를
        전제로 했다. 그 전제가 곧 **아무것도 입력하지 않은 부분군을 '0 이 n 개' 인
        완성군으로 만들던** 규칙이다 (아스트라 재검토 ①). 이제 0 을 값으로 세려면
        표본 수로 "여기까지 입력했다" 를 밝혀야 한다.
        """
        sg = self.SG.create({"study_id": self.study.id, "sample_count": 5,
                             "x1": 0.0, "x2": 2.0, "x3": 4.0, "x4": 0.0, "x5": 4.0})
        self.assertEqual(sg.sg_mean, 2.0)
        self.assertEqual(sg.sg_range, 4.0)
        self.assertTrue(sg.is_complete)

    def test_zeros_without_stated_count_are_not_measurements(self):
        """표본 수를 밝히지 않으면 0 인 칸은 미입력으로 본다 — 빈 부분군 구제."""
        sg = self.SG.create({"study_id": self.study.id,
                             "x1": 0.0, "x2": 2.0, "x3": 4.0, "x4": 0.0, "x5": 4.0})
        self.assertEqual(sorted(sg._get_values()), [2.0, 4.0, 4.0])
        self.assertFalse(sg.is_complete, "0 두 칸이 미입력이므로 완성군이 아니다")

    def test_stats_recompute_when_sample_count_changes(self):
        """표본 수가 유효 측정 0 을 통계에 넣고 빼는 스위치다.

        `x2=0.0` 은 '측정해서 0 이었다' 일 수도, '아직 안 적었다' 일 수도 있다.
        Float 만으로는 구분되지 않으므로 표본 수가 그것을 말한다. (아스트라 재검토 ①)
        """
        sg = self.SG.create({"study_id": self.study.id, "x1": 10.0, "x2": 0.0, "sample_count": 1})
        self.assertEqual(sg.sg_mean, 10.0, "표본 1개라고 했으면 x2 의 0 은 미입력이다")
        sg.sample_count = 2
        self.assertEqual(sg.sg_mean, 5.0, "표본 수를 늘리면 x2(0) 가 값으로 들어간다")
