import logging
from collections import defaultdict
from datetime import datetime, time

import pytz

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PARAM_HORIZON = "supplier_portal_purchase.forecast_horizon_days"
DEFAULT_HORIZON = 28


class SupplierDemandForecast(models.Model):
    """협력사 소요 전망 스냅샷 (비구속).

    생산 수요 원장(production.demand — 정본)을 BOM 전개해 협력사 공급품목의
    일자별 소요를 계산하고, 우리 보유재고·입고예정과 함께 협력사 포탈에 노출한다.
    수요를 새로 만들지 않는다 — 원장을 읽기만 하는 파생 스냅샷(cron 주기 갱신).
    확정 발주가 아니며 구속력이 없다(포탈 화면에 명시).
    """
    _name = "supplier.demand.forecast"
    _description = "협력사 소요 전망(비구속)"
    _order = "partner_id, product_id, date"

    partner_id = fields.Many2one("res.partner", string="협력사", required=True, index=True)
    product_id = fields.Many2one("product.product", string="공급 품목", required=True, index=True)
    date = fields.Date(string="소요일", required=True)
    qty_required = fields.Float(string="일 소요량")
    cum_required = fields.Float(string="누적 소요")
    qty_onhand = fields.Float(string="우리 보유재고", help="스냅샷 시점 보유량(품목 공통)")
    qty_incoming = fields.Float(string="소요일까지 입고 예정", help="해당 소요일 말까지 예정된 입고량. 확정 입고가 아닙니다.")
    qty_shortfall = fields.Float(
        string="누적 부족(예상)",
        help="누적 소요 − (보유+입고예정). 0보다 크면 이 날짜까지 추가 납품 필요 신호")
    snapshot_at = fields.Datetime(string="스냅샷 시각", index=True)
    company_id = fields.Many2one("res.company", required=True, index=True, default=lambda self: self.env.company)

    _sql_constraints = [("company_product_date_unique", "unique(company_id, partner_id, product_id, date)",
                         "회사·업체·품목·소요일별 전망은 하나만 게시할 수 있습니다.")]

    # ─────────────────────────────────────────────
    # 계산
    # ─────────────────────────────────────────────
    @api.model
    def _get_horizon_days(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(PARAM_HORIZON)
        try:
            days = int(raw)
            return days if days > 0 else DEFAULT_HORIZON
        except (TypeError, ValueError):
            return DEFAULT_HORIZON

    @api.model
    def _finished_demand_by_date(self, date_from, date_to):
        """(완제품, 일자) → 수요량. 같은 날 일별 행이 있으면 일별 합만 쓰고,
        없으면 시간대별 합을 쓴다(이중 계상 방지). test 소스는 제외."""
        demands = self.env["production.demand"].sudo().search([
            ("demand_date", ">=", date_from),
            ("demand_date", "<=", date_to),
            ("state", "in", ("draft", "confirmed")),
            ("source", "!=", "test"),
            ("company_id", "=", self.env.company.id),
        ])
        daily = defaultdict(float)
        hourly = defaultdict(float)
        for d in demands:
            key = (d.product_id, d.demand_date)
            if d.demand_type == "hourly":
                hourly[key] += d.quantity
            else:
                daily[key] += d.quantity
        result = dict(daily)
        for key, qty in hourly.items():
            if key not in result:
                result[key] = qty
        return result

    @api.model
    def _primary_supplier(self, product, date=None):
        """품목의 대표 공급 협력사(supplierinfo 최우선 순번). 없으면 False."""
        date = date or fields.Date.context_today(self)
        seller = product.product_tmpl_id.seller_ids.filtered(lambda s:
            (not s.company_id or s.company_id == self.env.company)
            and (not s.product_id or s.product_id == product)
            and (not s.date_start or s.date_start <= date)
            and (not s.date_end or s.date_end >= date))[:1]
        return seller.partner_id.commercial_partner_id if seller else False

    def _need_date_cutoff(self, date):
        # This ledger has dates, not a confirmed intraday BR deadline. Preserve
        # its daily granularity; don't invent an hour or a daily/hour precedence.
        timezone = pytz.timezone(self.env.company.partner_id.tz or "UTC")
        return timezone.localize(datetime.combine(date, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _cron_generate_all_forecasts(self):
        for company in self.env.user.company_ids:
            self.with_company(company).with_context(allowed_company_ids=company.ids).cron_generate_forecast()
        return True

    def _snapshot_needs_refresh(self):
        """Report changed source data, not an invented business expiry threshold."""
        if not self or any(not row.snapshot_at for row in self):
            return True
        oldest = min(self.mapped("snapshot_at"))
        company = self[:1].company_id
        domains = (
            ("production.demand", [("company_id", "=", company.id), ("write_date", ">", oldest)]),
            ("stock.move", [("company_id", "=", company.id), ("product_id", "in", self.product_id.ids),
                            ("write_date", ">", oldest)]),
            ("stock.quant", [("company_id", "=", company.id), ("product_id", "in", self.product_id.ids),
                             ("write_date", ">", oldest)]),
        )
        return any(self.env[model].sudo().search_count(domain, limit=1) for model, domain in domains)

    @api.model
    def cron_generate_forecast(self):
        """소요 전망 재계산·게시 (cron·수동 공용 진입점)."""
        company = self.env.company
        self.env.cr.execute("SELECT pg_advisory_xact_lock(%s, %s)", (736102, company.id))
        self = self.with_context(allowed_company_ids=company.ids).with_company(company)
        Bom = self.env["mrp.bom"].sudo().with_company(company)
        today = fields.Date.context_today(self)
        horizon = self._get_horizon_days()
        date_to = fields.Date.add(today, days=horizon)

        demand_map = self._finished_demand_by_date(today, date_to)

        # (협력사, 부품, 일자) → 소요량 — BOM 전개 결과 집계
        req = defaultdict(float)
        bom_cache = {}
        explode_cache = {}
        for (fg_product, demand_date), fg_qty in demand_map.items():
            if fg_product.id not in bom_cache:
                bom_cache[fg_product.id] = Bom._bom_find(fg_product, company_id=company.id).get(fg_product)
            bom = bom_cache[fg_product.id]
            if not bom:
                continue
            # 같은 완제품은 1개 기준 전개를 캐시하고 수량은 비례 적용
            if fg_product.id not in explode_cache:
                factor = (bom.product_uom_id._compute_quantity(
                    bom.product_qty, fg_product.uom_id) or 1.0)
                _boms, lines = bom.explode(fg_product, 1.0)
                per_unit = []
                for line, data in lines:
                    comp = line.product_id
                    # 사급(구매) 품목만 — 자가생산 중간품은 하위 전개 라인이 담당
                    qty = line.product_uom_id._compute_quantity(
                        data["qty"], comp.uom_id) / factor
                    per_unit.append((comp, qty))
                explode_cache[fg_product.id] = per_unit
            for comp, unit_qty in explode_cache[fg_product.id]:
                supplier = self._primary_supplier(comp, demand_date)
                if not supplier or not supplier.is_supplier_portal:
                    continue
                req[(supplier, comp, demand_date)] += unit_qty * fg_qty

        # 품목별 보유/입고예정(스냅샷 공통) + 누적 부족 계산 → 라인 생성
        snapshot_at = datetime.utcnow()
        vals_list = []
        by_partner_product = defaultdict(list)
        for (supplier, comp, d), qty in req.items():
            by_partner_product[(supplier, comp)].append((d, qty))
        for (supplier, comp), rows in by_partner_product.items():
            warehouses = self.env["stock.warehouse"].search([("company_id", "=", company.id)])
            comp = comp.with_company(company).with_context(allowed_company_ids=company.ids,
                location=warehouses.lot_stock_id.ids)
            onhand = comp.qty_available if warehouses else 0.0
            cum = 0.0
            for d, qty in sorted(rows, key=lambda r: r[0]):
                incoming = comp.with_context(to_date=self._need_date_cutoff(d)).incoming_qty if warehouses else 0.0
                available = onhand + incoming
                cum += qty
                vals_list.append({
                    "partner_id": supplier.id,
                    "product_id": comp.id,
                    "date": d,
                    "qty_required": qty,
                    "cum_required": cum,
                    "qty_onhand": onhand,
                    "qty_incoming": incoming,
                    "qty_shortfall": max(0.0, cum - available),
                    "snapshot_at": snapshot_at,
                    "company_id": company.id,
                })

        # 전체 교체 게시 (파생 스냅샷 — 이력은 두지 않는다)
        self.sudo().search([("company_id", "=", company.id)]).unlink()
        if vals_list:
            self.sudo().create(vals_list)
        _logger.info("협력사 소요 전망 갱신: %d개 라인 (기간 %d일, 협력사 %d곳)",
                     len(vals_list), horizon,
                     len({v["partner_id"] for v in vals_list}))
        return True
