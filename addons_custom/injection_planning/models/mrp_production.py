import logging

import pytz

from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)


class MrpProductionPlanning(models.Model):
    _inherit = "mrp.production"

    planning_run_id = fields.Many2one(
        "injection.planning.run", string="생산계획", index=True,
    )
    # [R144 관찰 #7] 실제 장착 금형(actual)은 현장이 장착할 때 채워지므로, 계획이 정한 금형을 따로 보여준다.
    planning_mold_id = fields.Many2one("injection.mold", string="계획 금형", related="planning_line_id.mold_id",
                                       readonly=True, store=False)
    planning_workcenter_id = fields.Many2one("mrp.workcenter", string="계획 사출기", related="planning_line_id.workcenter_id",
                                             readonly=True, store=False)
    planning_line_id = fields.Many2one(
        "injection.planning.line", string="생산계획 라인", index=True,
        readonly=True, copy=False,
        help="이 제조오더를 만든 계획 라인. 사출 능력에서 소요시간을 계산하는 원천이다. "
             "복사되지 않는다 — 시편·단위 MO 가 부모의 원천을 물려받으면 부모 수량의 "
             "소요를 상속한다.",
    )

    def _injection_plan_source_matches(self):
        """이 MO 와 계획 원천이 **같은 대상**인가.

        [아스트라 10:01 #2] 「`planning_line_id` **일반 create/write 로 아무 계획행을
        붙이거나, 다른 회사/품목/계획 run 의 행을 붙이는 경로**를 검증하십시오.
        단순 readonly 화면만으로 보호되지 않습니다. capability 도 **active/회사/정확
        설비금형 원천 확인**이 필요합니다.」
        """
        self.ensure_one()
        line = self.planning_line_id
        if not line:
            return False
        if self.planning_run_id and line.planning_run_id != self.planning_run_id:
            # [아스트라 10:14 #3] 「`planning_run_id` 와 line.run 일치 … 확인」
            return False                # 다른 계획의 행을 붙였다
        return (line.product_id == self.product_id
                and line.planning_run_id.company_id.id in
                (self.company_id.id, False)
                and (not line.workcenter_id.company_id
                     or line.workcenter_id.company_id == self.company_id))

    @api.constrains("planning_line_id", "planning_run_id", "product_id", "company_id")
    def _check_planning_line_source(self):
        for mo in self.filtered("planning_line_id"):
            if not mo._injection_plan_source_matches():
                raise ValidationError(_(
                    "계획 원천이 이 제조오더와 맞지 않습니다(품목·회사). "
                    "다른 계획 행을 연결할 수 없습니다: %s",
                    mo.planning_line_id.display_name or mo.planning_line_id.id))

    # ── 확정 시점에 **얼린** 소요 원천 ────────────────────────────────────
    # [아스트라 10:14 #4] 「**이미 생성된 MO 의 `date_start` 등 변경으로 실제
    # compute 가 호출될 때**는 생성 함수의 검증이 자동 재실행된다고 볼 수 없습니다.
    # 이 경로에서 **확정 원천 보존 또는 명시적 재검증**을 구현하고…」
    #
    # 총 소요시간이 아니라 **능력(시간당 개수)과 교체시간**을 얼린다. 총시간을
    # 얼리면 MO 수량을 바꿔도 소요가 따라오지 않아 10:01 #1(분할·부분생산 수량)
    # 지적을 되살린다. 능력만 얼리면 **마스터가 나중에 바뀌어도 흔들리지 않고**,
    # 수량 변경에는 정상적으로 반응한다.
    planning_hourly_capacity = fields.Float(
        string="확정 시간당 생산능력", readonly=True, copy=False, digits=(16, 6),
        help="생성 시점에 검증된 사출기·금형 능력(시간당 개수). 이후 능력 마스터가 "
             "바뀌어도 이 제조오더의 소요 계산은 이 값을 쓴다. 0 이면 아직 확정되지 "
             "않은 것으로 보아 원천을 다시 찾고, 없으면 명시적으로 거부한다.")
    planning_changeover_hours = fields.Float(
        string="확정 교체시간(시간)", readonly=True, copy=False,
        help="이 제조오더 구간 안에서 실제로 쓰는 금형 교체시간. 교체가 전날 창에서 "
             "끝났으면 0 이다.")

    # 위 세 값은 **생성 때 한 번** 정해지고 이후 바뀌지 않는다. `readonly` 는 화면만
    # 막으므로(ORM 은 그대로 통과) write 에서 실제로 막는다.
    _PLAN_SOURCE_FIELDS = (
        "planning_line_id", "planning_hourly_capacity", "planning_changeover_hours")

    def write(self, vals):
        """확정된 계획 원천의 **임의 연결·해제·변조**를 거부한다.

        [아스트라 10:01 #2] 「`planning_line_id` **일반 create/write 로 아무 계획행을
        붙이거나** …」 / [10:14 #3] 「**동일 회사·품목의 다른 행 임의 연결/해제**」
        """
        touched = [f for f in self._PLAN_SOURCE_FIELDS if f in vals]
        if touched:
            for mo in self:
                for field in touched:
                    new = vals[field]
                    if field == "planning_line_id":
                        current = mo.planning_line_id.id or False
                        new = int(new) if new else False
                        changed = current != new
                    else:
                        current = mo[field] or 0.0
                        changed = float_compare(
                            current, new or 0.0, precision_digits=6) != 0
                    if changed and (current or new):
                        raise UserError(_(
                            "제조오더의 계획 소요 원천(%(field)s)은 생성 이후 바꿀 수 "
                            "없습니다. 소요가 달라져야 한다면 계획을 다시 계산해 "
                            "제조오더를 새로 생성하십시오. (%(mo)s)",
                            field=self._fields[field].string, mo=mo.display_name))
        return super().write(vals)

    def _injection_plan_capability(self):
        """이 MO 의 **검증된 사출 능력 원천**. 없으면 빈 recordset.

        `active` 한 조합만, 그리고 **그 설비·금형 정확히** 그 조합만 본다.
        """
        self.ensure_one()
        line = self.planning_line_id
        if not line or not line.workcenter_id or not line.mold_id:
            return self.env["injection.machine.mold.capability"]
        return self.env["injection.machine.mold.capability"].search([
            ("workcenter_id", "=", line.workcenter_id.id),
            ("mold_id", "=", line.mold_id.id),
            ("active", "=", True),
        ], limit=1)

    def _injection_plan_refuse(self, problem):
        """계획에 연결된 사출 MO 인데 **원천이 없다** — 지어내지 않고 거부한다.

        [아스트라 10:14 #3] 「원천 누락/불일치를 `None` 으로 처리해 **코어 60분
        fallback** 으로 돌리는 설계는 … 계획이 우연히 60분이면 통과합니다. …
        **명시적 거부**여야 합니다. 계획 연결 사출 MO 에서 달력/능력 누락을 명시적으로
        거부하는 반례를 넣고, **일반 MO 와 정상 라우팅 경로는 보존**하십시오.」

        그래서 거부는 **계획 라인이 붙은 사출 MO** 에만 적용한다. 계획과 무관한 MO 와
        작업지시(라우팅)가 있는 MO 는 이 함수에 들어오지 않는다.
        """
        self.ensure_one()
        raise UserError(_(
            "사출 계획에 연결된 제조오더인데 소요시간의 원천이 없습니다: %(problem)s\n"
            "· %(product)s %(qty).2f %(uom)s (%(machine)s / %(mold)s)\n"
            "기준정보(사출기·금형 능력, 사출기 작업달력)를 바로잡은 뒤 계획을 다시 "
            "계산하십시오. 표준 60분 리드타임으로 대신 채우지 않습니다.",
            problem=problem,
            product=self.product_id.display_name,
            qty=self.product_qty, uom=self.product_uom_id.name or "-",
            machine=self.planning_line_id.workcenter_id.name or "-",
            mold=self.planning_line_id.mold_id.display_name or "-"))

    def _injection_plan_expected_finish(self, date_start):
        """계획 소요시간을 **정상 계산 훅**으로 돌려준다.

        [아스트라 20260912-01] 「`mrp.production._compute_date_finished` 는
        `_calculate_expected_finished_date(date_finished)` 가 False 이고
        `workorder.duration_expected` 합이 없으면 **60분 fallback** 을 사용합니다.
        … 단순 종료 write 가 아니라 **계산의 정상 원천과 훅**에 사출계획 소요를
        연결해야 합니다.」

        그래서 **계획 end 를 복사하지 않습니다.** 사출기·금형 능력(`hourly_capacity`
        = 3600/사이클 × 캐비티)과 수량에서 **생산시간**을 구하고, **교체시간은 따로**
        더한 뒤, 사출기 **작업달력** 위에 배치해 종료를 계산합니다.

        `None` 은 오직 **이 계산이 관여하지 않는 MO** 일 때만 돌려줍니다. 관여 대상인데
        원천이 없으면 `None` 이 아니라 **명시적으로 거부**합니다(10:14 #3).
        """
        self.ensure_one()
        line = self.planning_line_id
        if not line:
            return None                 # 계획과 무관한 MO — 코어 정상 경로
        generated_operation = (len(self.workorder_ids) == 1
            and 'injection_cost_generated' in self.workorder_ids.operation_id._fields
            and self.workorder_ids.operation_id.injection_cost_generated)
        if self.workorder_ids and not generated_operation:
            return None                 # 라우팅이 있으면 그 정본을 그대로 둔다
        if not self._injection_plan_source_matches():
            # 연결 제약(`_check_planning_line_source`)을 지나 여기까지 왔다면
            # 데이터가 사후에 어긋난 것이다. 조용히 60분으로 넘기지 않는다.
            self._injection_plan_refuse(_("계획 라인의 품목·회사가 제조오더와 다릅니다"))
        # [아스트라 10:14 #4] 확정 시점에 **얼린 능력**을 먼저 쓴다. 마스터가 나중에
        # 바뀌거나 보관처리돼도 이 제조오더의 소요는 흔들리지 않는다.
        rate = self.planning_hourly_capacity
        changeover_hours = self.planning_changeover_hours
        if rate <= 0:
            # 아직 얼리기 전(생성 중)이다 — 지금 원천을 검증한다.
            capability = self._injection_plan_capability()
            if not capability or capability.hourly_capacity <= 0:
                self._injection_plan_refuse(_(
                    "이 사출기·금형의 사용 가능한 능력(사이클·캐비티)이 없습니다"))
            rate = capability.hourly_capacity
            changeover_hours = line.changeover_in_span_hours or 0.0
        # [아스트라 10:01 #1] 「현재 `quantity = line.planned_qty or self.product_qty`
        # 는 **MO 를 분할/부분생산/수량변경해도 원계획 전체 수량**으로 계산합니다.」
        # 그래서 **MO 자신의 수량**을 씁니다. 능력은 품목 재고단위 기준이므로
        # MO 단위에서 재고단위로 환산합니다. (능력을 얼려도 수량엔 정상 반응한다)
        quantity = self.product_uom_id._compute_quantity(
            self.product_qty, self.product_id.uom_id, round=False)
        if quantity <= 0:
            self._injection_plan_refuse(_("제조오더 수량이 0 이하입니다"))
        # **생산시간**과 **교체시간**을 분리해 센다 (교체는 생산이 아니다).
        # **이 라인 구간 안에서 실제로 쓴** 교체시간만 더한다. 교체가 전날 창에서
        # 끝났으면 0 이다 — 처음엔 작업 전체 교체시간을 더해 **이중 계상**했고,
        # 기존 「계획 종료와 설비 달력이 맞지 않습니다」 가드가 그것을 잡았다.
        total_hours = (changeover_hours or 0.0) + quantity / rate
        return self._injection_plan_place(total_hours, date_start)

    def _injection_plan_place(self, total_hours, date_start):
        """소요시간을 **사출기 작업달력 위에** 올려 종료를 구한다."""
        self.ensure_one()
        line = self.planning_line_id
        start = self.date_start or date_start
        if not start:
            return None                 # 시작이 아직 없다 — 코어가 정할 차례다
        if total_hours <= 0:
            self._injection_plan_refuse(_("계산된 소요시간이 0 입니다"))
        calendar = (line.workcenter_id.resource_calendar_id
                    or self.company_id.resource_calendar_id)
        if not calendar:
            # [아스트라 10:01 #3] 「캘린더가 없으면 현재 `start+hours` 를 반환하는
            # 경로는 **'달력 원천 없음 명시 보류'와 다릅니다.**」 — 그리고 10:14 #3
            # 에서 `None` 반환(=코어 60분)도 명시 보류가 아니라고 지적됐다.
            self._injection_plan_refuse(_("사출기·회사의 작업 달력이 없습니다"))
        # 작업달력 위에 올린다 — 휴게·휴무를 건너뛴 실제 종료다.
        aware = pytz.UTC.localize(fields.Datetime.to_datetime(start))
        planned = calendar.plan_hours(total_hours, aware, compute_leaves=True)
        if not planned:
            self._injection_plan_refuse(_(
                "작업 달력에 이 소요시간을 배치할 근무시간이 없습니다"))
        return planned.astimezone(pytz.UTC).replace(tzinfo=None)

    def _calculate_expected_finished_date(self, date_start):
        expected = self._injection_plan_expected_finish(date_start)
        if expected is not None:
            return expected
        return super()._calculate_expected_finished_date(date_start)

class MrpWorkorderPlanningChangeover(models.Model):
    """[R144 결함 #3] 계획 연결 MO 의 **수동 라우팅 공정** 작업지시에 확정 교체시간을 더한다.

    UAT 실측(2026-09-15): BOM 에 수동 공정("사출성형", 사이클 1분)이 있으면 MO 종료가 작업지시
    소요(생산분만)로 계산돼, 계획 라인 첫 구간에 포함된 금형 교체(0.5h)가 빠지고 `_validate_created_mo`
    가 "소요시간이 계획보다 짧습니다" 로 거부 → 교체 라인은 MO 없이 초안 잔류. 교체는 라우팅이 아니라
    계획의 사실이므로, 계획 연결 MO 이고 작업지시가 하나뿐이며 그 사출기가 계획 사출기와 같을 때만
    라우팅 소요에 교체시간을 더한다. (원가 연계 자동 공정은 injection_worksite 가 별도로 처리하며
    super 를 부르지 않으므로 이중 계상되지 않는다.)
    """
    _inherit = "mrp.workorder"

    def _get_duration_expected(self, alternative_workcenter=False, ratio=1):
        duration = super()._get_duration_expected(alternative_workcenter=alternative_workcenter, ratio=ratio)
        mo = self.production_id
        line = mo.planning_line_id
        if not line or len(mo.workorder_ids) > 1:
            return duration
        if self.workcenter_id and line.workcenter_id and self.workcenter_id != line.workcenter_id:
            return duration
        changeover = mo.planning_changeover_hours or line.changeover_in_span_hours or 0.0
        return duration + changeover * 60.0
