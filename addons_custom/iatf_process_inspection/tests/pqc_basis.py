"""합본에서는 **공정검사 생성이 완료 전 준비로 옮겨간다.** 그 차이를 흡수한다.

`iatf_quality_precedence` 가 설치되면 `_create_pqc_inspection()` 은 **기존 검사를
반환**할 뿐 새로 만들지 않는다(완료 뒤에 초안을 덧붙이면 그 묶음이 조용히 무효가
되기 때문이다 — `iatf_quality_precedence/models/production.py:358-361`).
그래서 그 설치에서 검사를 만드는 **정상 경로**는 승인 관리계획 + 완료 전 준비
(`action_prepare_required_quality`)다.

**게이트를 낮추지 않는다.** 시험이 보려던 것(검사가 생기는가 / 어느 회사로
생기는가 / 런 단위로 묶이는가)은 그대로 두고, 이 설치의 정상 경로를 쓴다.
게이트가 없는 단독 설치에서는 원래대로 `_create_pqc_inspection()` 을 부른다.
"""
try:                                  # 합본에서만 있다. 단독 설치에서는 필요 없다.
    from odoo.addons.iatf_incoming_inspection.tests.quality_basis import (
        QualityBasisMixin)
except ImportError:                   # pragma: no cover - 설치 구성에 따름
    class QualityBasisMixin:          # noqa: D101 - 게이트 없는 환경의 빈 껍데기
        @classmethod
        def _quality_gate_installed(cls):
            return False

        @classmethod
        def _setup_quality_actors(cls, company):
            cls._quality_actors = {}

        def _approve_control_plan(self, mo):
            return False


class PqcBasisMixin(QualityBasisMixin):
    """이 설치의 **정상 경로**로 공정검사를 만든다."""

    def _make_pqc(self, mo):
        PQC = self.env["iatf.process.inspection"]
        if not self._quality_gate_installed():
            mo._create_pqc_inspection()
            return PQC.search([("production_id", "=", mo.id)])
        self.assertTrue(self._approve_control_plan(mo),
                        "합성 승인 관리계획을 갖추지 못했다")
        # 검사 준비는 **확정 후**다(초안에 준비하면 범위가 아직 정해지지 않았다).
        if mo.state == "draft":
            mo.action_confirm()
        if mo.product_id.tracking != "none" and not mo.lot_producing_id:
            mo.lot_producing_id = self.env["stock.lot"].sudo().create({
                "name": "PQC-LOT-%s" % mo.id, "product_id": mo.product_id.id,
                "company_id": mo.company_id.id}).id
        mo.action_prepare_required_quality()
        return PQC.search([("production_id", "=", mo.id)])
