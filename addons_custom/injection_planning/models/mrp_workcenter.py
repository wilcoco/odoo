from odoo import fields, models


class MrpWorkcenter(models.Model):
    _inherit = "mrp.workcenter"

    # 확정(제조지시 생성) 때마다 1 씩 오른다. 값 자체를 쓰는 곳은 없다 — **행을 바꾸는
    # 것 자체가 목적**이다. Repeatable Read 에서는 다른 트랜잭션이 이 행을 바꿔 커밋했다면
    # 뒤이은 `SELECT ... FOR UPDATE` 가 직렬화 오류를 내고, 그래야 요청 전체가 새 스냅샷으로
    # 다시 실행된다. 잠금만 걸고 낡은 스냅샷을 그대로 읽으면 같은 창에 두 번 확정된다.
    # (N-CROSSPLAN-CONFIRM)
    x_planning_reservation_seq = fields.Integer(
        string="계획 예약 버전", default=0, copy=False, readonly=True,
        help="계획 확정이 이 설비를 잡을 때마다 오른다. 동시 확정을 직렬화하기 위한 값이다.",
    )
    x_clamping_force_ton = fields.Float(
        string="형체력 (톤)",
        help="사출기 형체력(톤). 배정 시 금형의 요구 형체력 이상인 사출기만 적합 판정. "
             "0이면 적합성 필터 미적용(등록 전 방어).",
    )
