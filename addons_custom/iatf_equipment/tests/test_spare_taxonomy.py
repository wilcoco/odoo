"""예비부품 분류체계·적용표 테스트.

레거시 구조가 만들어낸 세 가지 문제를 새 구조가 실제로 막는지 확인한다.
  ① 4계층을 코드 한 칸에 담아 계층을 강제할 수 없었던 것
  ② 잎(기종)과 가지(묶음 노드)가 한 표에 섞여 묶음에도 부품이 달렸던 것
  ③ 분류 트리가 1:N 을 강제해 부품 하나가 설비 하나만 가리킬 수 있었던 것
"""

from odoo.exceptions import ValidationError, UserError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSpareTaxonomy(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Category = cls.env["iatf.spare.category"]
        cls.Spare = cls.env["iatf.equipment.spare"]
        cls.Application = cls.env["iatf.spare.application"]
        cls.Equipment = cls.env["iatf.equipment"]

        # 레거시 'AIAA' = 생산기술 : 사출 : 사출성형기 : UBE-2200T
        cls.division = cls.Category.create(
            {"name": "생산기술", "code": "A", "level": "division"})
        cls.process = cls.Category.create(
            {"name": "사출", "code": "I", "level": "process",
             "parent_id": cls.division.id})
        cls.group = cls.Category.create(
            {"name": "사출성형기", "code": "A", "level": "group",
             "parent_id": cls.process.id})
        cls.model = cls.Category.create(
            {"name": "UBE-2200T", "code": "A", "level": "model",
             "parent_id": cls.group.id})

        cls.machine_1 = cls.Equipment.create(
            {"name": "사출 1호기", "node_type": "equipment",
             "category_id": cls.model.id})
        cls.machine_2 = cls.Equipment.create(
            {"name": "사출 2호기", "node_type": "equipment",
             "category_id": cls.model.id})

    def _spare(self, name="유압 실린더 씰", **kw):
        vals = {"name": name, "category_id": self.model.id}
        vals.update(kw)
        return self.Spare.create(vals)

    # ── ① 정상 기록 생성 ──────────────────────────────────────────

    def test_tree_is_created_and_path_is_built(self):
        self.assertEqual(self.model.complete_name,
                         "생산기술 : 사출 : 사출성형기 : UBE-2200T")

    def test_full_code_reproduces_the_legacy_four_char_code(self):
        """자리별로 저장하지만 표시는 레거시 'AIAA' 와 같아야 한다."""
        self.assertEqual(self.division.full_code, "A")
        self.assertEqual(self.process.full_code, "AI")
        self.assertEqual(self.group.full_code, "AIA")
        self.assertEqual(self.model.full_code, "AIAA")

    def test_full_code_follows_a_renamed_parent_code(self):
        """상위 자리 코드를 고치면 하위 전체 코드가 따라 움직인다.

        레거시는 코드가 한 칸이라 상위 자리를 바꾸려면 하위 행을 전부 다시
        써야 했다. 계층을 쪼갠 이유 중 하나가 이것이다.
        """
        self.process.code = "J"
        self.assertEqual(self.model.full_code, "AJAA")

    def test_spare_created_on_a_leaf(self):
        spare = self._spare()
        self.assertEqual(spare.category_id, self.model)
        self.assertEqual(self.model.spare_count, 1)

    # ── ② 잎·가지 구분 ────────────────────────────────────────────

    def test_leaf_flag_is_only_true_for_a_childless_model_node(self):
        self.assertTrue(self.model.is_leaf)
        for branch in (self.division, self.process, self.group):
            self.assertFalse(branch.is_leaf,
                             f"{branch.name} 은 묶음인데 부품을 받는다고 나온다")

    def test_part_cannot_hang_on_a_branch_node(self):
        """레거시의 A000·AA00 문제. 묶음 노드에 부품을 달 수 없어야 한다."""
        for branch in (self.division, self.process, self.group):
            with self.assertRaises(ValidationError, msg=f"{branch.name} 에 부품이 달렸다"):
                self._spare(category_id=branch.id)

    def test_branch_cannot_grow_children_once_it_holds_parts(self):
        """부품이 달린 노드에 자식이 생기면 잎이면서 가지가 된다."""
        self._spare()
        with self.assertRaises(ValidationError):
            self.Category.create({"name": "변형", "code": "B", "level": "model",
                                  "parent_id": self.model.id})

    def test_leaf_holding_parts_cannot_be_promoted_to_a_branch(self):
        """부품을 단 채로 계층만 '설비군' 으로 올려 묶음이 되는 우회를 막는다.

        부품 쪽 검사는 부품이 움직일 때만 돈다. 분류만 고치면 그 검사를 안 거친다.
        """
        self._spare()
        # 계층만 바꾸면 부모-자식 단계 검사에 먼저 걸린다. 부모까지 같이 옮겨
        # 단계 검사는 통과시키고 잎 검사만 남긴다 — 이게 실제로 뚫리는 경로다.
        with self.assertRaises(ValidationError):
            self.model.write({"parent_id": self.process.id, "level": "group",
                              "code": "Z"})

    # ── ③ 계층 강제 (코드 한 칸으로는 못 하던 것) ─────────────────

    def test_level_cannot_be_skipped(self):
        """부문 밑에 바로 설비군을 매달 수 없다."""
        with self.assertRaises(ValidationError):
            self.Category.create({"name": "건너뜀", "code": "X", "level": "group",
                                  "parent_id": self.division.id})

    def test_level_cannot_be_inverted(self):
        """공정 밑에 부문이 올 수 없다."""
        with self.assertRaises(ValidationError):
            self.Category.create({"name": "거꾸로", "code": "X", "level": "division",
                                  "parent_id": self.process.id})

    def test_root_must_be_a_division(self):
        with self.assertRaises(ValidationError):
            self.Category.create({"name": "뿌리 아님", "code": "X", "level": "process"})

    def test_cycle_is_rejected(self):
        # ORM 이 parent_path 를 갱신하면서 먼저 UserError("Recursion Detected.") 를
        # 던진다. 우리 @api.constrains 는 그 뒤에 오는 백스톱이라 여기서는 안 보인다.
        # 막히는지가 요점이므로 상위 클래스로 받는다 (ValidationError ⊂ UserError).
        with self.assertRaises(UserError):
            self.division.parent_id = self.model
            self.env.flush_all()

    def test_duplicate_code_under_same_parent_is_rejected(self):
        with self.assertRaises(Exception):
            self.Category.create({"name": "중복", "code": "A", "level": "group",
                                  "parent_id": self.process.id})
            self.env.flush_all()

    def test_same_code_under_different_parents_is_fine(self):
        """'A' 는 자리마다 다른 뜻이다. 전역 유일이면 트리를 못 만든다."""
        other_process = self.Category.create(
            {"name": "조립", "code": "B", "level": "process",
             "parent_id": self.division.id})
        twin = self.Category.create(
            {"name": "조립기", "code": "A", "level": "group",
             "parent_id": other_process.id})
        self.assertEqual(twin.full_code, "ABA")
        self.assertEqual(self.group.full_code, "AIA")

    # ── ④ 다대다 적용표 (1:N 강제 해소) ───────────────────────────

    def test_one_part_applies_to_many_machines(self):
        """같은 부품이 설비 두 대에 들어가도 부품 행은 하나다."""
        spare = self._spare()
        self.Application.create({"spare_id": spare.id, "equipment_id": self.machine_1.id})
        self.Application.create({"spare_id": spare.id, "equipment_id": self.machine_2.id})
        self.assertEqual(spare.equipment_count, 2)
        self.assertEqual(self.Spare.search_count([("name", "=", spare.name)]), 1,
                         "설비마다 부품 행이 복제됐다 — 레거시 1:N 구조로 돌아갔다")

    def test_one_machine_holds_many_parts(self):
        seal = self._spare("유압 씰")
        heater = self._spare("히터 밴드")
        for part in (seal, heater):
            self.Application.create({"spare_id": part.id,
                                     "equipment_id": self.machine_1.id})
        self.assertEqual(self.machine_1.spare_count, 2)

    def test_same_pair_cannot_be_registered_twice(self):
        spare = self._spare()
        self.Application.create({"spare_id": spare.id, "equipment_id": self.machine_1.id})
        with self.assertRaises(Exception):
            self.Application.create({"spare_id": spare.id,
                                     "equipment_id": self.machine_1.id})
            self.env.flush_all()

    def test_application_qty_must_be_positive(self):
        spare = self._spare()
        with self.assertRaises(ValidationError):
            self.Application.create({"spare_id": spare.id,
                                     "equipment_id": self.machine_1.id,
                                     "qty_per_unit": 0})

    def test_classification_and_application_are_independent(self):
        """분류는 한 자리, 적용은 여러 개. 둘은 대체 관계가 아니다."""
        spare = self._spare()
        other_model = self.Category.create(
            {"name": "LS-1300T", "code": "B", "level": "model",
             "parent_id": self.group.id})
        other_machine = self.Equipment.create(
            {"name": "사출 3호기", "node_type": "equipment",
             "category_id": other_model.id})
        # 분류는 UBE 인데 LS 설비에도 들어갈 수 있다 — 적용표가 그걸 적는다.
        self.Application.create({"spare_id": spare.id,
                                 "equipment_id": other_machine.id})
        self.assertEqual(spare.category_id, self.model)
        self.assertEqual(spare.equipment_count, 1)

    # ── ⑤ 설비↔기종 다리 (레거시 겹침 0건 문제) ──────────────────

    def test_category_spares_are_applied_to_the_machine(self):
        seal = self._spare("유압 씰")
        heater = self._spare("히터 밴드")
        self.machine_1.action_apply_category_spares()
        applied = self.machine_1.spare_application_ids.mapped("spare_id")
        self.assertEqual(set(applied.ids), {seal.id, heater.id})

    def test_applying_twice_does_not_duplicate(self):
        self._spare()
        self.machine_1.action_apply_category_spares()
        self.machine_1.action_apply_category_spares()
        self.assertEqual(self.machine_1.spare_count, 1,
                         "두 번 눌렀더니 적용표에 중복이 생겼다")

    def test_machine_cannot_point_at_a_branch_node(self):
        """설비가 묶음 노드를 가리키면 일괄 적용이 조용히 0건이 된다.

        폼 domain 은 화면만 막는다. 가져오기·API 로 들어온 값도 막아야 한다.
        """
        with self.assertRaises(ValidationError):
            self.machine_1.category_id = self.group

    def test_machine_without_a_model_is_refused(self):
        """기종이 없으면 무엇을 가져올지 알 수 없다. 조용히 넘어가면 안 된다."""
        loose = self.Equipment.create({"name": "미분류 설비", "node_type": "equipment"})
        with self.assertRaises(UserError):
            loose.action_apply_category_spares()

    # ── ⑥ 상하한 합부 (기존 부족 판정이 그대로 사는지) ───────────

    def test_shortage_is_judged_against_the_minimum(self):
        spare = self._spare(quantity_required=5.0, quantity_on_hand=2.0)
        self.assertEqual(spare.qty_source, "manual")
        self.assertTrue(spare.is_short)
        self.assertAlmostEqual(spare.shortage_qty, 3.0, places=2)

    def test_exactly_at_the_minimum_is_not_short(self):
        spare = self._spare(quantity_required=5.0, quantity_on_hand=5.0)
        self.assertFalse(spare.is_short, "기준선과 같은 값이 부족으로 잡혔다")
        self.assertAlmostEqual(spare.shortage_qty, 0.0, places=2)

    def test_uncounted_part_is_not_reported_as_short(self):
        """수량 근거가 없는 부품을 '부족' 이라고 말하면 없는 사실을 만드는 것이다."""
        spare = self._spare(quantity_required=5.0)
        self.assertEqual(spare.qty_source, "none")
        self.assertFalse(spare.is_short)

    # ── ⑦ 데이터 오염 ─────────────────────────────────────────────

    def test_no_demo_records_shipped(self):
        """분류를 미리 깔지 않는다. 회사 실제 체계와 다른 트리가 증빙에 섞인다."""
        self.assertEqual(
            self.Category.with_context(active_test=False).search_count(
                [("id", "not in", (self.division + self.process
                                   + self.group + self.model).ids)]),
            0, "모듈이 분류 데이터를 함께 설치하고 있다")
