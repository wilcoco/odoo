import logging
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# ERP(오라클) 자동차 생산계획 수신.
#   원천(버퍼) = T_ZM_PLN2 (일자별: 기준일 YMD + D00~D12 = 당일+12일 계획수량)
#   정본       = production.demand (source='oracle') — 장부는 하나 원칙.
# 접속정보는 시스템 파라미터(erp_plan_sync.dsn/user/password)에만 둔다 — 코드/git 에 자격증명 금지.
# 멱등: 스테이징 unique(기준일·차수·라인·품번·FNO·계획일), 재수신 시 수량 갱신.
# 품번 매칭: ITM == product.default_code. 미매칭은 보완 큐(unmatched)로 남기고 계속.

DAY_COLS = ["D00", "D01", "D02", "D03", "D04", "D05", "D06",
            "D07", "D08", "D09", "D10", "D11", "D12"]


class ErpPlanSync(models.Model):
    _name = "erp.plan.sync"
    _description = "ERP 생산계획 수신 배치"
    _order = "id desc"
    _inherit = ["mail.thread"]

    name = fields.Char(default="신규", readonly=True)
    ymd = fields.Char(string="기준일(YMD)", help="비우면 ERP의 최신 기준일 자동")
    fetched_at = fields.Datetime(string="수신 시각", readonly=True)
    erp_loaded_at = fields.Char(string="ERP 적재 시각(LDATE)", readonly=True)
    row_count = fields.Integer(string="원본 행수", readonly=True)
    line_created = fields.Integer(string="신규 계획라인", readonly=True)
    line_updated = fields.Integer(string="갱신 계획라인", readonly=True)
    unmatched_count = fields.Integer(string="품번 미매칭", readonly=True)
    demand_created = fields.Integer(string="수요 생성", readonly=True)
    demand_updated = fields.Integer(string="수요 갱신", readonly=True)
    state = fields.Selection([("draft", "대기"), ("fetched", "수신 완료"), ("pushed", "수요 반영")],
                             default="draft", tracking=True)
    line_ids = fields.One2many("erp.plan.line", "sync_id", string="계획 라인")

    @api.model
    def _connect(self):
        get = self.env["ir.config_parameter"].sudo().get_param
        dsn = get("erp_plan_sync.dsn")
        user = get("erp_plan_sync.user")
        password = get("erp_plan_sync.password")
        if not (dsn and user and password):
            raise UserError(_(
                "ERP 접속정보가 없습니다. 시스템 매개변수에 erp_plan_sync.dsn / "
                "erp_plan_sync.user / erp_plan_sync.password 를 설정하세요. "
                "(자격증명은 DB 설정에만 — 코드/저장소에 넣지 않습니다)"))
        try:
            import oracledb
        except ImportError:
            raise UserError(_("python 패키지 oracledb 가 필요합니다 (pip install oracledb)."))
        return oracledb.connect(user=user, password=password, dsn=dsn)

    def action_fetch(self):
        """T_ZM_PLN2 에서 기준일 계획을 수신해 스테이징(멱등)으로 적재."""
        Line = self.env["erp.plan.line"]
        Product = self.env["product.product"]
        for sync in self:
            conn = self._connect()
            try:
                cur = conn.cursor()
                ymd = sync.ymd
                if not ymd:
                    cur.execute("SELECT MAX(YMD) FROM T_ZM_PLN2")
                    ymd = cur.fetchone()[0]
                cur.execute(
                    "SELECT DIV, YMD, CHASU, LINE, FR, CSRT, ALC, ITM, FNO, "
                    + ", ".join(DAY_COLS) + ", LDATE "
                    "FROM T_ZM_PLN2 WHERE YMD = :ymd", ymd=ymd)
                rows = cur.fetchall()
            finally:
                conn.close()
            base_date = datetime.strptime(ymd, "%Y%m%d").date()
            created = updated = 0
            unmatched_items = set()
            ldate = ""
            product_cache = {}
            for r in rows:
                div, _ymd, chasu, line_code, fr, csrt, alc, itm, fno = r[:9]
                day_qtys = r[9:9 + len(DAY_COLS)]
                ldate = str(r[9 + len(DAY_COLS)] or "")
                itm = (itm or "").strip()
                if itm not in product_cache:
                    product_cache[itm] = Product.search([("default_code", "=", itm)], limit=1)
                product = product_cache[itm]
                if not product:
                    unmatched_items.add(itm)
                for offset, qty in enumerate(day_qtys):
                    if not qty:
                        continue
                    plan_date = base_date + timedelta(days=offset)
                    key = [("ymd", "=", ymd), ("chasu", "=", chasu),
                           ("line_code", "=", line_code or ""), ("itm", "=", itm),
                           ("fno", "=", fno or 0), ("plan_date", "=", plan_date)]
                    existing = Line.search(key, limit=1)
                    vals = {"qty": qty, "product_id": product.id if product else False,
                            "state": "unmatched" if not product else (
                                existing.state if existing and existing.state == "pushed" else "matched"),
                            "div": div, "fr": fr, "csrt": csrt, "alc": alc,
                            "erp_loaded_at": ldate, "sync_id": sync.id}
                    if existing:
                        existing.write(vals)
                        updated += 1
                    else:
                        Line.create(dict(vals, ymd=ymd, chasu=chasu,
                                         line_code=line_code or "", itm=itm,
                                         fno=fno or 0, plan_date=plan_date))
                        created += 1
            sync.write({
                "name": "ERP계획 %s" % ymd, "ymd": ymd,
                "fetched_at": fields.Datetime.now(), "erp_loaded_at": ldate,
                "row_count": len(rows), "line_created": created, "line_updated": updated,
                "unmatched_count": Line.search_count([("sync_id", "=", sync.id), ("state", "=", "unmatched")]),
                "state": "fetched",
            })
            if unmatched_items:
                sync.message_post(body=_("품번 미매칭 %d종 (보완 큐 확인): %s") % (
                    len(unmatched_items), ", ".join(sorted(unmatched_items)[:20])))
        return True

    def action_push_demands(self):
        """매칭된 계획라인 → production.demand (source=oracle) 생성/갱신 — 멱등."""
        Demand = self.env["production.demand"]
        for sync in self:
            created = updated = 0
            for line in sync.line_ids.filtered(lambda l: l.state in ("matched", "pushed") and l.product_id):
                if line.demand_id:
                    if line.demand_id.state in ("draft", "confirmed") and line.demand_id.quantity != line.qty:
                        line.demand_id.quantity = line.qty
                        updated += 1
                else:
                    line.demand_id = Demand.create({
                        "demand_date": line.plan_date, "product_id": line.product_id.id,
                        "quantity": line.qty, "demand_type": "daily", "source": "oracle",
                        "notes": "ERP %s 차수%s 라인%s" % (line.ymd, line.chasu, line.line_code),
                    })
                    created += 1
                line.state = "pushed"
            sync.write({"demand_created": created, "demand_updated": updated, "state": "pushed"})
        return True

    @api.model
    def cron_daily_sync(self):
        """일일 자동 수신 (ERP 새벽 적재 후). 기본 비활성 — 운영 전환 시 활성화."""
        sync = self.create({})
        sync.action_fetch()
        sync.action_push_demands()
        return True


class ErpPlanLine(models.Model):
    _name = "erp.plan.line"
    _description = "ERP 생산계획 라인 (스테이징)"
    _order = "plan_date, itm"

    sync_id = fields.Many2one("erp.plan.sync", string="수신 배치", ondelete="set null")
    div = fields.Char(string="사업장")
    ymd = fields.Char(string="기준일", required=True, index=True)
    chasu = fields.Integer(string="차수")
    line_code = fields.Char(string="라인")
    fr = fields.Char(string="FR")
    csrt = fields.Char(string="차종")
    alc = fields.Char(string="ALC")
    itm = fields.Char(string="품번(ITM)", required=True, index=True)
    fno = fields.Integer(string="FNO")
    plan_date = fields.Date(string="계획일", required=True, index=True)
    qty = fields.Float(string="계획수량")
    product_id = fields.Many2one("product.product", string="매칭 품목")
    demand_id = fields.Many2one("production.demand", string="생성 수요", readonly=True)
    erp_loaded_at = fields.Char(string="ERP 적재시각")
    state = fields.Selection(
        [("matched", "매칭"), ("unmatched", "품번 미매칭"), ("pushed", "수요 반영")],
        default="matched", index=True)

    _sql_constraints = [(
        "erp_plan_key_uniq",
        "unique(ymd, chasu, line_code, itm, fno, plan_date)",
        "같은 기준일·차수·라인·품번·계획일 라인이 이미 있습니다 (재수신은 갱신 처리).")]

    def action_rematch(self):
        """보완 큐: 품목 마스터 등록 후 재매칭."""
        Product = self.env["product.product"]
        for line in self:
            product = Product.search([("default_code", "=", line.itm)], limit=1)
            if product:
                line.write({"product_id": product.id, "state": "matched"})
        return True
