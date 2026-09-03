from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestMoldTempLog(TransactionCase):
    """금형 예열/온도 측정 이력 (SQ 4_6·4_7).

    ① 정상 기록 생성 — 부위·방식이 남는다
    ② 기준 없음 판정 — 마스터에 상·하한이 없으면 '부적합' 이 아니라 '기준 없음'
    ③ 상·하한 벗어난 값의 합부 판정 — 예열/가동중 각각의 기준과 대조
    """

    def setUp(self):
        super().setUp()
        self.mold = self.env["iatf.mold"].create({
            "name": "T-온도금형", "mold_type": "injection",
            "preheat_temp_min": 60.0, "preheat_temp_max": 90.0,
            "mold_temp_min": 40.0, "mold_temp_max": 70.0,
        })
        self.Log = self.env["iatf.mold.temp.log"]

    def _log(self, **vals):
        base = {"mold_id": self.mold.id, "log_type": "preheat",
                "point": "fixed", "method": "ir", "temperature": 75.0}
        base.update(vals)
        return self.Log.create(base)

    # ───────── ① 정상 기록 생성 ─────────

    def test_create_records_point_and_method(self):
        log = self._log(temperature=75.0, point="moving", method="contact")
        self.assertEqual(log.spec_result, "ok")
        self.assertEqual(log.point, "moving", "측정 부위가 기록에 남는다 (크리아 4_7)")
        self.assertEqual(log.method, "contact")
        self.assertEqual(log.spec_min, 60.0)
        self.assertEqual(log.spec_max, 90.0)
        self.mold.invalidate_recordset()
        self.assertEqual(self.mold.temp_log_count, 1)
        self.assertIn(log, self.mold.temp_log_ids)
        self.assertIn("이동측", log.display_name)

    def test_point_and_method_are_required(self):
        """부위·방식 없는 측정은 저장되지 않는다.

        무엇을 어디서 쟀는지 없는 온도값은 증빙이 되지 못한다.
        """
        for missing in ("point", "method"):
            with self.assertRaises(Exception, msg="%s 는 필수" % missing):
                with self.env.cr.savepoint():
                    self._log(**{missing: False})

    # ───────── ② 기준 없음 판정 ─────────

    def test_no_spec_is_not_pass_and_not_fail(self):
        """기준이 없으면 '기준 없음'. 0℃ 상하한으로 읽어 전부 부적합으로 만들지 않는다."""
        bare = self.env["iatf.mold"].create({"name": "T-기준없음", "mold_type": "injection"})
        log = self._log(mold_id=bare.id, temperature=75.0)
        self.assertEqual(log.spec_result, "no_spec")
        self.assertEqual(log.spec_min, 0.0)
        self.assertEqual(log.spec_max, 0.0)
        self.assertIn(
            log, self.Log.search([("spec_result", "=", "no_spec")]),
            "'기준 없음' 목록으로 회수할 수 있어야 한다",
        )

    def test_spec_result_follows_master(self):
        """마스터 기준을 고치면 판정이 따라 바뀐다 — 값이 굳으면 안 된다."""
        log = self._log(temperature=95.0)
        self.assertEqual(log.spec_result, "ng", "상한 90 초과")
        self.mold.preheat_temp_max = 100.0
        log.invalidate_recordset()
        self.assertEqual(log.spec_result, "ok", "기준이 넓어지면 적합으로 바뀐다")

    # ───────── ③ 상·하한 벗어난 값의 합부 판정 ─────────

    def test_preheat_judgement(self):
        self.assertEqual(self._log(temperature=75.0).spec_result, "ok")
        self.assertEqual(self._log(temperature=60.0).spec_result, "ok", "하한값 자체는 적합")
        self.assertEqual(self._log(temperature=90.0).spec_result, "ok", "상한값 자체는 적합")
        self.assertEqual(self._log(temperature=59.9).spec_result, "ng", "하한 미달")
        self.assertEqual(self._log(temperature=90.1).spec_result, "ng", "상한 초과")

    def test_operating_uses_its_own_spec(self):
        """가동중 온도는 예열이 아니라 금형온도 기준(40~70)과 대조한다."""
        self.assertEqual(
            self._log(log_type="operating", temperature=55.0).spec_result, "ok")
        self.assertEqual(
            self._log(log_type="operating", temperature=75.0).spec_result, "ng",
            "예열 기준(60~90)으로 재면 적합이지만 금형온도 기준으로는 부적합")
        self.assertEqual(
            self._log(log_type="preheat", temperature=75.0).spec_result, "ok",
            "같은 온도라도 예열 기준으로는 적합")

    def test_log_type_switch_reevaluates(self):
        log = self._log(log_type="preheat", temperature=75.0)
        self.assertEqual(log.spec_result, "ok")
        log.log_type = "operating"
        self.assertEqual(log.spec_result, "ng", "구분을 바꾸면 다른 기준으로 다시 판정")

    def test_one_sided_spec(self):
        """하한만 있는 금형 — 상한 0 을 '0℃ 초과 금지' 로 읽지 않는다."""
        one = self.env["iatf.mold"].create({
            "name": "T-하한만", "mold_type": "injection", "preheat_temp_min": 60.0,
        })
        self.assertEqual(self._log(mold_id=one.id, temperature=1000.0).spec_result, "ok")
        self.assertEqual(self._log(mold_id=one.id, temperature=59.0).spec_result, "ng")

    def test_ng_logs_are_searchable(self):
        """기준 이탈 목록이 나와야 '지속 모니터링' 증빙이 된다."""
        ng = self._log(temperature=120.0)
        ok = self._log(temperature=70.0)
        found = self.Log.search([("spec_result", "=", "ng")])
        self.assertIn(ng, found)
        self.assertNotIn(ok, found)

    def test_mold_delete_blocked_while_log_exists(self):
        log = self._log()
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                self.mold.unlink()
        log.unlink()

    def test_check_temp_in_spec_rejects_unknown_kind(self):
        """판정 진입점을 오용하면 조용히 통과시키지 말고 터뜨린다."""
        with self.assertRaises(ValueError):
            self.mold.check_temp_in_spec(75.0, "nozzle")
