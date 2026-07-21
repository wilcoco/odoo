from odoo import api, fields, models, _
from odoo.exceptions import UserError
import math


class IatfSpcStudy(models.Model):
    _name = "iatf.spc.study"
    _description = "SPC Study (IATF 16949 §9.1.1.1)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="연구 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    title = fields.Char(string="제목", required=True, tracking=True)
    analysis_date = fields.Date(string="분석일", default=fields.Date.today, tracking=True)
    chart_type = fields.Selection(
        [
            ("xbar_r", "X-bar R Chart"),
            ("xbar_s", "X-bar S Chart"),
            ("imr", "Individual & Moving Range (I-MR)"),
            ("p_chart", "p Chart (proportion defective)"),
            ("np_chart", "np Chart"),
            ("c_chart", "c Chart (count of defects)"),
            ("u_chart", "u Chart"),
        ],
        string="관리도 유형", required=True, default="xbar_r", tracking=True,
    )

    # ── Product / Process ──
    product_id = fields.Many2one("product.product", string="제품")
    part_number = fields.Char(string="부품 번호")
    characteristic_name = fields.Char(string="특성", required=True)
    unit = fields.Char(string="측정 단위")
    process_name = fields.Char(string="공정", help="회사양식 process")
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    machine_name = fields.Char(string="설비")
    gage_name = fields.Char(string="게이지 / 측정기")
    sample_size = fields.Integer(string="표본 크기 (총)", help="회사양식 sampleSize")

    # ── Specification ──
    usl = fields.Float(string="USL (상한 규격)")
    lsl = fields.Float(string="LSL (하한 규격)")
    nominal = fields.Float(string="목표값")

    # ── Subgroup config ──
    subgroup_size = fields.Integer(string="부분군 크기 (n)", default=5)

    # ── Data ──
    subgroup_ids = fields.One2many("iatf.spc.subgroup", "study_id", string="부분군")
    plc_last_record_id = fields.Integer(
        string="PLC 수집 위치", readonly=True, copy=False,
        help="마지막으로 수집한 injection.production.record id — 재실행 멱등 기준")
    subgroup_count = fields.Integer(compute="_compute_stats", store=True)

    # ── Calculated results ──
    grand_mean = fields.Float(string="X̄̄ (Grand Mean)", digits=(16, 4), readonly=True)
    mean_range = fields.Float(string="R̄ (Mean Range)", digits=(16, 4), readonly=True)
    ucl_xbar = fields.Float(string="UCL (X-bar)", digits=(16, 4), readonly=True)
    lcl_xbar = fields.Float(string="LCL (X-bar)", digits=(16, 4), readonly=True)
    ucl_range = fields.Float(string="UCL (Range)", digits=(16, 4), readonly=True)
    lcl_range = fields.Float(string="LCL (Range)", digits=(16, 4), readonly=True)

    # ── Process Capability ──
    std_dev = fields.Float(string="σ (Std Dev)", digits=(16, 6), readonly=True)
    cp = fields.Float(string="Cp", digits=(16, 3), readonly=True)
    cpk = fields.Float(string="Cpk", digits=(16, 3), readonly=True)
    pp = fields.Float(string="Pp", digits=(16, 3), readonly=True)
    ppk = fields.Float(string="Ppk", digits=(16, 3), readonly=True)

    capability_status = fields.Selection(
        [
            ("capable", "적합 (Cpk ≥ 1.33)"),
            ("marginal", "한계 (1.00 ≤ Cpk < 1.33)"),
            ("not_capable", "부적합 (Cpk < 1.00)"),
            ("not_calculated", "미산출"),
        ],
        string="공정능력 상태", default="not_calculated", readonly=True,
    )

    ooc_count = fields.Integer(string="관리이탈 포인트", readonly=True)

    responsible_id = fields.Many2one("res.users", string="담당자",
                                      default=lambda self: self.env.user, tracking=True)
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("collecting", "데이터 수집 중"),
            ("analyzed", "분석 완료"),
            ("closed", "종료"),
        ],
        string="상태", default="draft", tracking=True,
    )
    notes = fields.Text(string="비고 / 결론")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    # d2 constants for subgroup sizes 2-10
    D2_TABLE = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326,
                6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970, 10: 3.078}
    A2_TABLE = {2: 1.880, 3: 1.023, 4: 0.729, 5: 0.577,
                6: 0.483, 7: 0.419, 8: 0.373, 9: 0.337, 10: 0.308}
    D3_TABLE = {2: 0, 3: 0, 4: 0, 5: 0, 6: 0, 7: 0.076, 8: 0.136, 9: 0.184, 10: 0.223}
    D4_TABLE = {2: 3.267, 3: 2.575, 4: 2.282, 5: 2.114,
                6: 2.004, 7: 1.924, 8: 1.864, 9: 1.816, 10: 1.777}

    @api.depends("subgroup_ids")
    def _compute_stats(self):
        for rec in self:
            rec.subgroup_count = len(rec.subgroup_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.spc.study") or _("New")
        return super().create(vals_list)

    def action_start_collecting(self):
        self.write({"state": "collecting"})

    def action_calculate(self):
        for study in self:
            study._calculate_control_limits()
            study._calculate_capability()
            study._count_ooc()
        self.write({"state": "analyzed"})

    def action_close(self):
        self.write({"state": "closed"})

    def action_reset_draft(self):
        self.write({"state": "draft"})

    def _calculate_control_limits(self):
        self.ensure_one()
        subgroups = self.subgroup_ids.sorted("sequence")
        if not subgroups:
            return

        n = self.subgroup_size or 5
        means = []
        ranges = []
        for sg in subgroups:
            vals = sg._get_values()
            if vals:
                means.append(sum(vals) / len(vals))
                ranges.append(max(vals) - min(vals))

        if not means:
            return

        x_dbar = sum(means) / len(means)
        r_bar = sum(ranges) / len(ranges) if ranges else 0.0

        a2 = self.A2_TABLE.get(n, 0.577)
        d3 = self.D3_TABLE.get(n, 0)
        d4 = self.D4_TABLE.get(n, 2.114)

        self.write({
            "grand_mean": x_dbar,
            "mean_range": r_bar,
            "ucl_xbar": x_dbar + a2 * r_bar,
            "lcl_xbar": x_dbar - a2 * r_bar,
            "ucl_range": d4 * r_bar,
            "lcl_range": d3 * r_bar,
        })

    def _calculate_capability(self):
        self.ensure_one()
        n = self.subgroup_size or 5
        d2 = self.D2_TABLE.get(n, 2.326)
        r_bar = self.mean_range

        if r_bar and d2:
            sigma_within = r_bar / d2
        else:
            sigma_within = 0.0

        # Overall std dev from all individual values
        all_vals = []
        for sg in self.subgroup_ids:
            all_vals.extend(sg._get_values())

        if len(all_vals) > 1:
            mean_all = sum(all_vals) / len(all_vals)
            sigma_overall = math.sqrt(sum((v - mean_all) ** 2 for v in all_vals) / (len(all_vals) - 1))
        else:
            sigma_overall = 0.0

        usl = self.usl
        lsl = self.lsl
        x_dbar = self.grand_mean

        cp = cpk = pp = ppk = 0.0

        if sigma_within > 0 and usl and lsl:
            cp = (usl - lsl) / (6 * sigma_within)
            cpu = (usl - x_dbar) / (3 * sigma_within)
            cpl = (x_dbar - lsl) / (3 * sigma_within)
            cpk = min(cpu, cpl)

        if sigma_overall > 0 and usl and lsl:
            pp = (usl - lsl) / (6 * sigma_overall)
            ppu = (usl - x_dbar) / (3 * sigma_overall)
            ppl = (x_dbar - lsl) / (3 * sigma_overall)
            ppk = min(ppu, ppl)

        if cpk >= 1.33:
            status = "capable"
        elif cpk >= 1.0:
            status = "marginal"
        elif cpk > 0:
            status = "not_capable"
        else:
            status = "not_calculated"

        self.write({
            "std_dev": sigma_within,
            "cp": cp,
            "cpk": cpk,
            "pp": pp,
            "ppk": ppk,
            "capability_status": status,
        })

    def _count_ooc(self):
        self.ensure_one()
        ooc = 0
        for sg in self.subgroup_ids:
            vals = sg._get_values()
            if vals:
                sg_mean = sum(vals) / len(vals)
                sg_range = max(vals) - min(vals)
                is_ooc = (
                    sg_mean > self.ucl_xbar or sg_mean < self.lcl_xbar
                    or sg_range > self.ucl_range
                )
                sg.is_ooc = is_ooc
                if is_ooc:
                    ooc += 1
            else:
                sg.is_ooc = False
        self.ooc_count = ooc
        if ooc > 0:
            self._auto_create_spc_nc(ooc)

    def _auto_create_spc_nc(self, ooc_count):
        """SPC 관리 이탈 → NC 자동 생성 → CAPA 루프 (L4-2)"""
        NC = self.env.get("iatf.nonconformity")
        if NC is None:
            return
        existing = NC.search([
            ("title", "like", "SPC 관리이탈: %s" % self.name),
            ("state", "!=", "closed"),
        ], limit=1)
        if existing:
            return
        nc = NC.create({
            "title": _("SPC 관리이탈: %s — %s") % (self.name, self.characteristic_name),
            "nc_type": "process",
            "severity": "major" if ooc_count >= 3 else "minor",
            "problem_description": (
                "<p>SPC 분석 관리이탈 감지<br/>"
                "연구: %s<br/>특성: %s<br/>"
                "관리이탈 포인트: %d건<br/>"
                "Cpk: %.3f<br/>"
                "공정능력: %s</p>"
            ) % (self.name, self.characteristic_name, ooc_count,
                 self.cpk, dict(self._fields["capability_status"].selection).get(self.capability_status, "")),
            "product_id": self.product_id.id if self.product_id else False,
        })
        self.message_post(body=_(
            "SPC 관리이탈 %d건 → 부적합 %s 자동 생성됨. CAPA 진행 필요.") % (ooc_count, nc.name))

    def action_collect_plc_measurements(self):
        """PLC 실측중량(injection.production.record)을 부분군으로 자동 수집.
        재실행 멱등(마지막 수집 id 이후만), 부분군 크기 미달 잔여분은 다음 수집으로 이월."""
        from odoo.exceptions import UserError
        if "injection.production.record" not in self.env:
            raise UserError(_("사출 현장 모듈(injection_worksite)이 설치되지 않아 PLC 수집을 사용할 수 없습니다."))
        Record = self.env["injection.production.record"]
        Subgroup = self.env["iatf.spc.subgroup"]
        for study in self:
            if not study.product_id:
                raise UserError(_("제품을 먼저 지정하세요."))
            domain = [
                ("id", ">", study.plc_last_record_id or 0),
                ("product_id", "=", study.product_id.id),
                ("measured_weight", ">", 0),
            ]
            if "weight_is_measured" in Record._fields:
                domain.append(("weight_is_measured", "=", True))
            records = Record.search(domain, order="id")
            n = study.sample_size if 2 <= (study.sample_size or 0) <= 10 else 5
            seq = (max(study.subgroup_ids.mapped("sequence")) if study.subgroup_ids else 0) + 10
            created = 0
            i = 0
            while i + n <= len(records):
                chunk = records[i:i + n]
                vals = {"study_id": study.id, "sequence": seq,
                        "sample_date": chunk[-1].create_date,
                        "notes": _("PLC 자동수집 #%s~%s") % (chunk[0].id, chunk[-1].id)}
                for k, rec in enumerate(chunk, start=1):
                    vals["x%d" % k] = rec.measured_weight
                Subgroup.create(vals)
                study.plc_last_record_id = chunk[-1].id
                seq += 10
                created += 1
                i += n
            study.message_post(body=_(
                "PLC 실측 수집: 부분군 %(c)d개 생성 (크기 %(n)d), 잔여 %(r)d건 이월")
                % {"c": created, "n": n, "r": len(records) - i})
        return True
