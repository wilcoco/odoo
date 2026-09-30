from datetime import date, timedelta

from odoo import api, fields, models, _


PERIODICITY = [
    ("daily", "매일"),
    ("weekly", "매주"),
    ("monthly", "매월"),
    ("quarterly", "분기"),
    ("yearly", "매년"),
    ("adhoc", "수시(수동 생성)"),
]

WEEKDAYS = [("0", "월"), ("1", "화"), ("2", "수"), ("3", "목"),
            ("4", "금"), ("5", "토"), ("6", "일")]


class OpsTaskDef(models.Model):
    """업무 정의 — '무엇을, 어느 역할이, 어떤 주기로, 어떻게(매뉴얼)' 하는지의 마스터.

    cron 이 주기에 맞춰 업무 건(ops.task)을 자동 생성한다(멱등: 정의×기간 유일)."""

    _name = "ops.task.def"
    _description = "운영 업무 정의"
    _order = "role_id, sequence, id"
    _inherit = ["mail.thread"]

    name = fields.Char(string="업무명", required=True, tracking=True)
    role_id = fields.Many2one("ops.role", string="담당 역할", required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    periodicity = fields.Selection(PERIODICITY, string="주기", required=True,
                                   default="monthly", tracking=True)
    weekday = fields.Selection(WEEKDAYS, string="요일(매주)", default="0",
                               help="매주 주기일 때 생성 요일")
    day_of_month = fields.Integer(string="생성일(매월/분기/매년)", default=1,
                                  help="매월·분기(1,4,7,10월)·매년(1월) 주기의 생성 일자. "
                                       "말일보다 크면 말일로 처리.")
    due_days = fields.Integer(string="기한(일)", default=3,
                              help="생성일로부터 완료 기한까지의 일수")

    requires_approval = fields.Boolean(string="승인 필요", default=True,
                                       help="완료 보고 후 승인자의 승인까지 요구")
    approver_role_id = fields.Many2one("ops.role", string="승인 역할",
                                       help="비우면 운영관리자 그룹이 승인")

    manual_html = fields.Html(string="업무 매뉴얼",
                              help="초보자가 이 화면만 보고 수행할 수 있게 절차를 기술")
    menu_path = fields.Char(string="Odoo 메뉴 경로",
                            help="예: 실제원가(관리) > MO 실제원가")
    doc_ref = fields.Char(string="관련 문서", help="예: docs/월마감_체크리스트.md")
    menu_action_id = fields.Many2one("ir.actions.act_window", string="바로가기 액션",
                                     help="설정 시 업무 건에서 '화면 열기' 버튼 제공")

    task_ids = fields.One2many("ops.task", "task_def_id", string="발생 업무")
    open_count = fields.Integer(compute="_compute_counts", string="미결")

    def _compute_counts(self):
        Task = self.env["ops.task"]
        for d in self:
            d.open_count = Task.search_count([
                ("task_def_id", "=", d.id), ("state", "in", ("todo", "done"))])

    # ── 기간 키/예정일 계산 ──
    def _period_info(self, today):
        """오늘이 이 정의의 생성일이면 (period_key, scheduled_date), 아니면 (None, None)."""
        self.ensure_one()
        if self.periodicity == "daily":
            return today.isoformat(), today
        if self.periodicity == "weekly":
            if str(today.weekday()) == (self.weekday or "0"):
                y, w, _d = today.isocalendar()
                return f"{y}-W{w:02d}", today
            return None, None
        # 말일 보정
        import calendar
        last = calendar.monthrange(today.year, today.month)[1]
        gen_day = min(max(self.day_of_month or 1, 1), last)
        if self.periodicity == "monthly":
            if today.day == gen_day:
                return f"{today.year}-{today.month:02d}", today
            return None, None
        if self.periodicity == "quarterly":
            if today.month in (1, 4, 7, 10) and today.day == gen_day:
                q = (today.month - 1) // 3 + 1
                return f"{today.year}-Q{q}", today
            return None, None
        if self.periodicity == "yearly":
            if today.month == 1 and today.day == gen_day:
                return str(today.year), today
            return None, None
        return None, None  # adhoc

    def _current_period_key(self, today):
        """오늘이 속한 기간의 키(생성일 무관) — '지금 생성' 백필용."""
        self.ensure_one()
        if self.periodicity == "daily":
            return today.isoformat()
        if self.periodicity == "weekly":
            y, w, _d = today.isocalendar()
            return f"{y}-W{w:02d}"
        if self.periodicity == "monthly":
            return f"{today.year}-{today.month:02d}"
        if self.periodicity == "quarterly":
            return f"{today.year}-Q{(today.month - 1) // 3 + 1}"
        if self.periodicity == "yearly":
            return str(today.year)
        return fields.Datetime.now().strftime("adhoc-%Y%m%d%H%M%S")

    def _create_task(self, period_key, scheduled):
        self.ensure_one()
        Task = self.env["ops.task"]
        if self.periodicity != "adhoc" and Task.search_count([
                ("task_def_id", "=", self.id), ("period_key", "=", period_key)]):
            return Task  # 멱등
        return Task.create({
            "task_def_id": self.id,
            "period_key": period_key,
            "scheduled_date": scheduled,
            "due_date": scheduled + timedelta(days=max(self.due_days or 0, 0)),
        })

    @api.model
    def _cron_generate_tasks(self):
        """매일 실행 — 오늘이 생성일인 정의들의 업무 건 생성(멱등)."""
        today = fields.Date.context_today(self)
        created = 0
        for d in self.search([("active", "=", True), ("periodicity", "!=", "adhoc")]):
            key, sched = d._period_info(today)
            if key and d._create_task(key, sched):
                created += 1
        return created

    def action_generate_now(self):
        """현재 기간 업무 건을 즉시 생성(누락 백필·수시 업무 발행)."""
        today = fields.Date.context_today(self)
        tasks = self.env["ops.task"]
        for d in self:
            key = d._current_period_key(today)
            t = d._create_task(key, today)
            tasks |= t
        return {
            "type": "ir.actions.act_window", "name": _("생성된 업무"),
            "res_model": "ops.task", "view_mode": "list,form",
            "domain": [("id", "in", tasks.ids)],
        }
