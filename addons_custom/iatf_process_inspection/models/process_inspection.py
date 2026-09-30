import math

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import SQL

_AUTO_EVIDENCE_TOKEN = object()


class IatfProcessInspection(models.Model):
    _name = "iatf.process.inspection"
    _description = "공정검사 / 최종검사 (IATF 16949 §8.6)"
    _inherit = ["iatf.approval.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "create_date desc"

    name = fields.Char(
        string="검사 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    inspection_stage = fields.Selection(
        [
            ("ipqc", "공정검사 (IPQC)"),
            ("final", "최종검사 (FQC)"),
            ("oqc", "출하검사 (OQC)"),
        ],
        string="검사 단계", required=True, default="ipqc", tracking=True,
    )
    # ── 회사양식: 초/중/종물 + 교대 + 생산일 ──
    article_stage = fields.Selection(
        [
            ("first", "초물"),
            ("middle", "중물"),
            ("last", "종물"),
        ],
        string="검사 차수", tracking=True,
        help="초물(생산 개시)/중물(생산 중)/종물(생산 종료) 검사 — 회사양식 inspectionType",
    )
    shift = fields.Char(string="교대조", help="예: 주간/야간 또는 1/2/3교대")
    production_date = fields.Date(string="생산일")
    run_unit_mo_ids = fields.Json(
        string="묶음에 센 단위 실적", readonly=True, copy=False,
        help="이 런 묶음 검사서가 생산량으로 이미 센 사출 단위 MO. 같은 단위를 "
             "다시 완료해도 중복 누적하지 않기 위한 근거다.")
    inspection_date = fields.Datetime(string="검사 일시", default=fields.Datetime.now, required=True)

    # ── 제조/출하 참조 ──
    production_id = fields.Many2one("mrp.production", string="제조 오더", tracking=True)
    picking_id = fields.Many2one("stock.picking", string="출하 전표", tracking=True)
    workorder_id = fields.Many2one("mrp.workorder", string="작업지시", tracking=True)
    workcenter_id = fields.Many2one("mrp.workcenter", string="작업장")
    product_id = fields.Many2one("product.product", string="제품", required=True, tracking=True)
    part_number = fields.Char(string="부품 번호")
    lot_id = fields.Many2one("stock.lot", string="로트/시리얼")

    # ── 수량 ──
    quantity_produced = fields.Float(string="생산 수량")
    quantity_inspected = fields.Float(string="검사 수량", required=True)
    quantity_accepted = fields.Float(string="합격 수량")
    quantity_rejected = fields.Float(string="불합격 수량")
    defect_rate = fields.Float(string="불량률 (%)", compute="_compute_defect_rate", store=True)

    # ── 검사 기준 ──
    inspection_type = fields.Selection(
        [
            ("full", "전수 검사"),
            ("sampling", "샘플링 검사"),
            ("spc", "SPC 샘플링"),
        ],
        string="검사 유형", default="sampling", tracking=True,
    )
    sampling_plan = fields.Char(string="샘플링 계획")
    sample_size = fields.Integer(string="샘플 크기")
    accept_number = fields.Integer(string="합격 판정 개수")

    # ── 검사 항목 ──
    line_ids = fields.One2many("iatf.process.inspection.line", "inspection_id", string="검사 항목")

    # ── 항목별 판정 요약 (회사양식: 외관/치수/기능) ──
    visual_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="외관 판정", tracking=True,
    )
    dimension_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="치수 판정", tracking=True,
    )
    function_result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="기능 판정", tracking=True,
    )

    # ── 판정 ──
    result = fields.Selection(
        [
            ("pass", "합격"),
            ("conditional", "조건부 합격"),
            ("fail", "불합격"),
            ("hold", "보류"),
        ],
        string="판정 결과", tracking=True,
    )
    disposition = fields.Selection(
        [
            ("ship", "출하 승인"),
            ("rework", "재작업"),
            ("scrap", "폐기"),
            ("sort", "전수 선별"),
            ("hold", "보류"),
            ("concession", "특채"),
        ],
        string="처리 방법", tracking=True,
    )

    # ── 담당자 ──
    inspector_id = fields.Many2one("res.users", string="검사원",
                                    default=lambda self: self.env.user, tracking=True)
    approved_by = fields.Many2one("res.users", string="승인자")

    # ── 연결 ──
    nonconformity_id = fields.Many2one("iatf.nonconformity", string="연결된 부적합")
    control_plan_id = fields.Many2one("iatf.control.plan", string="관리계획서 참조")
    document_ids = fields.Many2many("iatf.document", string="관련 문서")
    attachment_ids = fields.Many2many("ir.attachment", string="첨부파일")
    notes = fields.Text(string="비고")

    state = fields.Selection(
        [
            ("draft", "초안"),
            ("inspecting", "검사 중"),
            ("decided", "판정 완료"),
            ("closed", "종료"),
            ("cancelled", "취소"),
        ],
        string="상태", default="draft", tracking=True,
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    auto_evidence_snapshot = fields.Json(
        string='자동 연동 원검사 근거', readonly=True, copy=False,
        help='SPC·부적합·LOT 보류에 사용한 원검사입니다. 정정은 새 검사로 기록합니다.')

    _AUTO_SOURCE_FIELDS = {
        'company_id', 'product_id', 'lot_id', 'production_id', 'picking_id',
        'workorder_id', 'workcenter_id', 'inspection_stage', 'inspection_date',
        'inspection_type', 'quantity_produced', 'quantity_inspected',
        'quantity_accepted', 'quantity_rejected', 'result', 'line_ids',
        'visual_result', 'dimension_result', 'function_result', 'inspector_id',
        'article_stage', 'shift', 'production_date', 'control_plan_id',
        # [아스트라 20260912 05:27] 「`run_unit_mo_ids` 는 readonly JSON 이지만
        # **create/write/default 값 차단 및 원검사 스냅샷 필드 집합에 포함되지
        # 않았습니다. UI readonly 만으로 원천 근거를 보호할 수 없습니다.**」
        'run_unit_mo_ids',
    }

    @api.depends("quantity_inspected", "quantity_rejected")
    def _compute_defect_rate(self):
        for rec in self:
            if rec.quantity_inspected:
                rec.defect_rate = (rec.quantity_rejected / rec.quantity_inspected) * 100.0
            else:
                rec.defect_rate = 0.0

    @api.model_create_multi
    def create(self, vals_list):
        if 'default_auto_evidence_snapshot' in self.env.context or any(
                'auto_evidence_snapshot' in vals for vals in vals_list):
            raise UserError(_('자동 연동 원검사 근거를 직접 생성할 수 없습니다.'))
        # 런 묶음 근거는 **서버 집계 경로에서만** 만든다. 일반 검사 작성 권한으로
        # 직접 넣거나 default 로 주입할 수 없다.
        if not self._run_aggregate_internal() and (
                'default_run_unit_mo_ids' in self.env.context
                or any('run_unit_mo_ids' in vals for vals in vals_list)):
            raise UserError(_('런 묶음 근거는 서버 집계 절차에서만 기록합니다.'))
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("iatf.process.inspection") or _("New")
        records = super().create(vals_list)
        # [R144 정책 #9] 승인된 관리계획서가 있으면 검사 항목을 자동으로 물려받는다(항목이 이미 있으면 유지).
        for rec in records:
            if not rec.line_ids and rec.product_id:
                rec.action_load_from_control_plan()
        return records

    @api.model
    def _run_aggregate_internal(self):
        return self.env.context.get('_process_auto_evidence_token') is _AUTO_EVIDENCE_TOKEN

    def write(self, vals):
        internal = self.env.context.get('_process_auto_evidence_token') is _AUTO_EVIDENCE_TOKEN
        if 'auto_evidence_snapshot' in vals and not internal:
            raise UserError(_('자동 연동 원검사 근거는 서버에서만 기록합니다.'))
        if 'run_unit_mo_ids' in vals and not internal:
            raise UserError(_('런 묶음 근거는 서버 집계 절차에서만 기록합니다.'))
        if not internal and self.filtered('run_unit_mo_ids') and (
                self._AUTO_SOURCE_FIELDS & vals.keys()):
            # 승인 뒤든 아니든, 묶음 근거가 붙은 검사서의 범위는 사람이 직접
            # 바꾸지 않는다. 정정은 새 검사로 남긴다.
            raise UserError(_('런 묶음 검사서의 범위는 직접 변경할 수 없습니다. 정정은 새 검사로 기록하세요.'))
        if not internal and (self._AUTO_SOURCE_FIELDS | {'nonconformity_id'}) & vals.keys():
            self.check_access('write')
            self._lock_auto_evidence_records(self)
            if self.filtered('auto_evidence_snapshot'):
                raise UserError(_('이미 자동 연동한 검사 근거는 변경할 수 없습니다. 정정은 새 검사로 기록하세요.'))
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self._lock_auto_evidence_records(self)
        if self.filtered('auto_evidence_snapshot'):
            raise UserError(_('자동 연동한 원검사는 삭제하지 않고 정정 이력으로 남겨야 합니다.'))
        return super().unlink()

    def action_start_inspection(self):
        self.write({"state": "inspecting"})

    def action_decide(self):
        with self.env.cr.savepoint():
            self.check_access('write')
            self._lock_auto_evidence_records(self)
            self._lock_auto_evidence_records(self.line_ids)
            for rec in self:
                rec._check_auto_evidence_source(require_decision=True)
                rec._remember_auto_evidence()
                rec.write({"state": "decided"})
                rec._auto_feed_spc()
                if rec.result == "fail":
                    rec._auto_create_nc()
                    rec._auto_quarantine_lot()
        return True

    def _auto_source_payload(self):
        self.ensure_one()
        payload = {}
        for name in sorted(self._AUTO_SOURCE_FIELDS - {'line_ids'}):
            value = self[name]
            kind = self._fields[name].type
            payload[name] = ((value.ids[0] if value else False) if kind == 'many2one' else
                             str(value) if kind in ('date', 'datetime') and value else value)
        payload['lines'] = [{
            'id': line.id, 'characteristic_name': line.characteristic_name,
            'characteristic_type': line.characteristic_type,
            'specification': line.specification, 'measurement_method': line.measurement_method,
            'measured_value': line.measured_value, 'result': line.result,
        } for line in self.line_ids.sorted('id')]
        return {'version': 1, 'source': payload}

    # 스냅샷을 찍은 **뒤에 추가된** 원천 키. 구자료에는 없을 수 있다.
    _AUTO_SOURCE_ADDED_FIELDS = ('run_unit_mo_ids',)

    def _auto_source_matches(self, stored):
        """저장된 원천과 현재 원천이 **같은가** — 구버전 스냅샷 호환.

        [아스트라 20260912 06:30] 「44 단위 중 42 실패 … 저장
        `auto_evidence_snapshot.source` 와 현재 `_auto_source_payload().source` 의
        차이는 **오직 `run_unit_mo_ids` 키: 기존 원본에는 없음, 새 계산값에는
        false** 입니다. `_AUTO_SOURCE_FIELDS` 에 추가하면서 일반 개별 검사까지
        직렬화 형태가 바뀐 **호환성 문제**입니다. **실제 철회로 판정하면 안
        됩니다.**」

        제 회귀입니다. 필드를 보호 집합에 넣으면서 **이미 승인된 과거 근거의
        직렬화 모양까지 바꿨습니다.**

        고치는 방식: 기존 승인 원본·시각·사용자를 **다시 쓰지 않습니다.**
        비교할 때만, **나중에 추가된 키가 저장본에 없는 경우**를 이렇게 읽습니다.
          - 지금 그 값이 **비어 있으면** → 구자료다. 그 키로 차이를 만들지 않는다.
          - 지금 그 값이 **있으면** → 승인 뒤에 집계 근거가 생긴 것이다. **차단한다.**
          - 그 밖의 키가 하나라도 다르면 → 종전대로 **차단한다.**
        """
        self.ensure_one()
        if not isinstance(stored, dict):
            return False
        stored = dict(stored)
        current = dict(self._auto_source_payload()['source'])
        for name in self._AUTO_SOURCE_ADDED_FIELDS:
            if name in stored:
                continue                    # 구자료가 아니다 — 그대로 비교한다
            if current.get(name):
                return False                # 승인 뒤 집계 근거 후삽입 — 차단
            current.pop(name, None)
        return stored == current

    def _remember_auto_evidence(self):
        self.ensure_one()
        payload = self._auto_source_payload()
        if self.auto_evidence_snapshot:
            if (self.auto_evidence_snapshot.get('version') != 1 or
                    not self._auto_source_matches(
                        self.auto_evidence_snapshot.get('source'))):
                raise UserError(_('연동한 원검사와 현재 근거가 다릅니다. 새 검사로 정정하세요.'))
            return
        payload.update(recorded_by_id=self.env.uid,
                       recorded_at=fields.Datetime.to_string(fields.Datetime.now()))
        self.with_context(_process_auto_evidence_token=_AUTO_EVIDENCE_TOKEN).write({
            'auto_evidence_snapshot': payload})

    def _lock_auto_evidence_records(self, records):
        """Version rows so an RR request retries instead of using stale evidence."""
        if records:
            records.flush_recordset()
            self.env.cr.execute(SQL(
                'UPDATE %s SET write_date = write_date WHERE id IN %s',
                SQL.identifier(records._table), tuple(sorted(records.ids))))
            records.invalidate_recordset()

    def _check_auto_evidence_source(self, require_decision=False):
        self.ensure_one()
        self.check_access('write')
        self.line_ids.check_access('read')
        if not self.company_id or self.company_id not in self.env.companies:
            raise UserError(_('허용된 회사가 명확한 검사만 자동 연동할 수 있습니다.'))
        self.product_id.check_access('read')
        if self.product_id.company_id and self.product_id.company_id != self.company_id:
            raise UserError(_('검사 제품의 회사가 다릅니다.'))
        for target in (self.lot_id, self.production_id, self.picking_id, self.workorder_id):
            if not target:
                continue
            target.check_access('read')
            if target.company_id != self.company_id:
                raise UserError(_('검사와 연결된 LOT·생산·출하의 회사가 다릅니다.'))
            if 'product_id' in target._fields and target.product_id != self.product_id:
                raise UserError(_('검사와 연결된 LOT·생산의 제품이 다릅니다.'))
        if self.workorder_id and self.production_id and self.workorder_id.production_id != self.production_id:
            raise UserError(_('검사 작업지시와 제조 오더가 일치하지 않습니다.'))
        quantities = (self.quantity_produced, self.quantity_inspected,
                      self.quantity_accepted, self.quantity_rejected)
        if any(not math.isfinite(qty) or qty < 0 for qty in quantities):
            raise UserError(_('검사 수량은 유한한 0 이상의 수여야 합니다.'))
        if require_decision:
            if not self.result or self.state in ('closed', 'cancelled'):
                raise UserError(_('판정할 수 있는 검사 상태와 결과를 확인하세요.'))
            if self.quantity_inspected <= 0 or not self.line_ids:
                raise UserError(_('양의 검사 수량과 실제 검사항목이 필요합니다.'))
            if any(not line.result or (line.result != 'na' and not (line.measured_value or '').strip())
                   for line in self.line_ids):
                raise UserError(_('검사 항목마다 실제 측정·관찰 근거와 판정을 기록하세요.'))
            if self.result == 'pass' and any(line.result == 'fail' for line in self.line_ids):
                raise UserError(_('불합격 항목이 있는 검사를 합격으로 판정할 수 없습니다.'))
        # Even non-SPC inspections must never publish NaN/Infinity as evidence.
        for line in self.line_ids:
            try:
                value = float((line.measured_value or '').strip())
            except (TypeError, ValueError):
                continue  # Qualitative observations are not numeric samples.
            if not math.isfinite(value):
                raise UserError(_('검사 측정값에 NaN 또는 무한대를 사용할 수 없습니다.'))

    def _auto_evidence_model(self, model_name):
        """Only use after checking the original inspection under its caller."""
        self.ensure_one()
        context = {key: value for key, value in self.env.context.items()
                   if not key.startswith('default_')}
        context['allowed_company_ids'] = self.company_id.ids
        return self.env[model_name].sudo().with_context(context).with_company(self.company_id)

    def _auto_feed_spc(self):
        """Collect only matching company/product/characteristic evidence."""
        self.ensure_one()
        self._check_auto_evidence_source()
        self._lock_auto_evidence_records(self)
        self._lock_auto_evidence_records(self.line_ids)
        self._check_auto_evidence_source()
        self._remember_auto_evidence()
        if self.env.get("iatf.spc.study") is None:
            return
        if not self.line_ids:
            return
        SpcStudy = self._auto_evidence_model('iatf.spc.study')
        for line in self.line_ids:
            # 잠복 결함 수정: 라인 필드는 characteristic_name/measured_value(Char).
            # 기존 코드는 존재하지 않는 characteristic/actual_value 를 참조해
            # 라인 있는 판정에서 AttributeError — 수치 파싱 불가 라인은 건너뛴다.
            try:
                value = float((line.measured_value or "").strip())
            except (TypeError, ValueError):
                continue
            if line.result == 'na':
                continue
            studies = SpcStudy.search([
                ("company_id", "=", self.company_id.id),
                ("product_id", "=", self.product_id.id),
                ("characteristic_name", "=", line.characteristic_name),
                ("state", "=", "collecting"),
            ])
            origin = "pqc:%s:%s" % (self.id, line.id)
            self._lock_auto_evidence_records(studies)
            for study in studies.sorted('id'):
                self._lock_auto_evidence_records(study.subgroup_ids)
                # 같은 검사 라인을 두 번 주입하지 않는다 (판정 버튼 반복 실행).
                # 부분일치로 보면 안 된다 — "pqc:2:1" 이 "pqc:2:12" 안에 들어 있어
                # 라인 1 의 측정이 라인 12 의 것으로 오인돼 통째로 누락된다.
                # (제3자 재검토 R05) 구분자로 잘라 정확히 비교한다.
                if any(origin in (sg.origins or "").split(",") for sg in study.subgroup_ids):
                    continue
                n = study.subgroup_size or 5
                # 열려 있는 부분군(자동 주입 중, 아직 n 미만)에 다음 칸을 채운다.
                # 부분군마다 x1 만 넣고 새로 만들면 나머지 칸의 0 이 평균에 들어간다. (Q14)
                # 열림 판단의 근거는 `sample_count`(앞에서부터 몇 칸)가 아니라
                # 실제 입력 칸 수다. x5 만 손으로 채워 둔 부분군은 sample_count 가
                # 0 이라 예전 규칙에선 '닫힌 군' 으로 보여 새 군이 계속 생겼다.
                # (아스트라 독립재현 ① 반증)
                # `filled_mask` 가 있는 군만 이어 채운다. 입력 칸이 기록되지 않은 과거
                # 군에 한 칸 넣으면 추정 칸까지 근거로 승격된다. (275 리뷰 Q275-05)
                open_sg = study.subgroup_ids.filtered(
                    lambda s: s.filled_mask and 0 < s._filled_count() < n
                ).sorted("sequence")[-1:]
                if open_sg:
                    # 다음 빈 칸을 찾는다. 사람이 x2~x5 를 손으로 채워 둔 경우
                    # 그 값을 덮어쓰지 않는다. (제3자 재검토 R06)
                    k = open_sg._next_free_slot()
                    if not k:
                        continue          # 이미 n 칸이 다 찼다 — 다음 부분군은 아래에서 만든다
                    open_sg._record_measurement(k, value, origin=origin)
                else:
                    next_seq = (max(study.subgroup_ids.mapped("sequence"), default=0)) + 1
                    self._auto_evidence_model('iatf.spc.subgroup').create({
                        "study_id": study.id, "sequence": next_seq,
                        "sample_date": self.inspection_date, "x1": value,
                        # SPC 생성 API는 mask 직접 지정을 거절한다. 입력 1칸을
                        # 명시해 서버가 mask를 만들고 실측 0도 보존하게 한다.
                        "sample_count": 1, "origins": origin})

    def _auto_create_nc(self):
        """불합격 시 부적합 자동 생성"""
        self.ensure_one()
        self._check_auto_evidence_source(require_decision=True)
        self._lock_auto_evidence_records(self)
        if self.result != 'fail' or self.state != 'decided':
            raise UserError(_('판정 완료된 불합격 검사에서만 부적합을 자동 생성합니다.'))
        self._remember_auto_evidence()
        if self.nonconformity_id:
            nc = self.nonconformity_id.sudo()
            if (nc.company_id != self.company_id or nc.product_id != self.product_id or
                    nc.lot_id != self.lot_id or nc.production_id != self.production_id):
                raise UserError(_('연결된 부적합의 회사·제품·LOT·생산 근거가 다릅니다.'))
            return
        nc = self._auto_evidence_model('iatf.nonconformity').create({
            'company_id': self.company_id.id,
            'detected_by': self.env.uid,
            "title": _("공정검사 불합격: %s - %s") % (self.name, self.product_id.name),
            "nc_type": "process",
            "severity": "major",
            "problem_description": Markup("<p>공정검사 %s 불합격 자동 생성<br/>제품: %s<br/>MO: %s<br/>불량률: %s%%<br/>재고 처분은 별도 승인된 이동으로 처리합니다.</p>") % (
                self.name, self.product_id.name,
                self.production_id.name if self.production_id else "-",
                round(self.defect_rate, 2)),
            "product_id": self.product_id.id,
            "production_id": self.production_id.id if self.production_id else False,
            "lot_id": self.lot_id.id if self.lot_id else False,
            "quantity_affected": self.quantity_inspected,
            "quantity_rejected": self.quantity_rejected or 0,
        })
        self.with_context(_process_auto_evidence_token=_AUTO_EVIDENCE_TOKEN).write({
            'nonconformity_id': nc.id})
        self.message_post(body=_("부적합 %s 자동 생성됨") % nc.name)

    def _auto_quarantine_lot(self):
        """Record a hold; deciding a failure never disposes of physical stock."""
        self.ensure_one()
        self._check_auto_evidence_source(require_decision=True)
        if self.result != 'fail' or self.state != 'decided' or not self.nonconformity_id:
            raise UserError(_('불합격 판정과 부적합 근거가 있어야 LOT를 보류합니다.'))
        self._remember_auto_evidence()
        if not self.lot_id:
            return
        lot = self.lot_id.sudo()
        self._lock_auto_evidence_records(lot)
        marker = '[PQC:%s / NC:%s]' % (self.id, self.nonconformity_id.id)
        if not lot.quality_hold or marker not in (lot.hold_reason or ''):
            reason = '%s %s' % (marker, _('불합격 판정; 실물 처분 승인 대기'))
            lot._set_quality_hold_from_source(self, reason)
            self.message_post(body=_('LOT %s 품질 보류. 재고 이동·폐기는 수행하지 않았습니다.') % lot.name)

    def action_load_from_control_plan(self):
        """Control Plan에서 검사항목/기준 자동 로딩 (L3-5)"""
        self.ensure_one()
        CP = self.env.get("iatf.control.plan")
        if CP is None:
            return
        cp = self.control_plan_id
        if not cp:
            cp = CP.search([
                ("product_id", "=", self.product_id.id),
                ("state", "=", "approved"),
            ], order="create_date desc", limit=1)
            if cp:
                self.control_plan_id = cp.id
        if not cp:
            return
        existing_chars = set(self.line_ids.mapped("characteristic_name"))
        lines_to_create = []
        for cp_line in cp.line_ids:
            if cp_line.characteristic_name not in existing_chars:
                lines_to_create.append({
                    "inspection_id": self.id,
                    "sequence": cp_line.sequence,
                    "characteristic_name": cp_line.characteristic_name,
                    "characteristic_type": "dimensional" if cp_line.characteristic_type == "product" else "performance",
                    "special_characteristic": cp_line.special_characteristic if cp_line.special_characteristic != "hi" else "cc",
                    "specification": cp_line.specification,
                    "measurement_method": cp_line.evaluation_method,
                })
        if lines_to_create:
            self.env["iatf.process.inspection.line"].create(lines_to_create)
            self.message_post(body=_("관리계획서 %s에서 %d개 검사항목 로딩됨") % (cp.name, len(lines_to_create)))

    def action_compute_aql_sample(self):
        """AQL 테이블 기반 샘플 수량 자동 계산 (L3-6)"""
        self.ensure_one()
        qty = self.quantity_produced or self.quantity_inspected or 0
        # AQL Level II Normal — 간소화된 참조 테이블
        aql_table = [
            (2, 2), (8, 3), (15, 5), (25, 8), (50, 13),
            (90, 20), (150, 32), (280, 50), (500, 80),
            (1200, 125), (3200, 200), (10000, 315),
            (35000, 500), (150000, 800), (500000, 1250),
            (float("inf"), 2000),
        ]
        sample = qty  # default full
        for lot_max, sample_size in aql_table:
            if qty <= lot_max:
                sample = min(sample_size, qty)
                break
        self.quantity_inspected = sample
        self.message_post(body=_("AQL Level II 기준 샘플 수량 자동 계산: %d (로트 크기: %d)") % (sample, qty))

    def action_close(self):
        self.write({"state": "closed"})

    def action_cancel(self):
        self.write({"state": "cancelled"})

    def action_create_nc(self):
        self.ensure_one()
        nc = self.env["iatf.nonconformity"].create({
            "title": _("공정검사 불합격: %s") % self.product_id.name,
            "nc_type": "process",
            "severity": "major",
            "problem_description": "<p>%s</p>" % (self.notes or ""),
            "product_id": self.product_id.id,
        })
        self.nonconformity_id = nc.id
        return {
            "type": "ir.actions.act_window",
            "res_model": "iatf.nonconformity",
            "res_id": nc.id,
            "view_mode": "form",
            "target": "current",
        }


class IatfProcessInspectionLine(models.Model):
    _name = "iatf.process.inspection.line"
    _description = "공정검사 항목"
    _order = "sequence, id"

    inspection_id = fields.Many2one(
        "iatf.process.inspection", string="검사", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(default=10)
    characteristic_name = fields.Char(string="검사 항목", required=True)
    characteristic_type = fields.Selection(
        [("dimensional", "치수"), ("visual", "외관"), ("functional", "기능"),
         ("performance", "성능"), ("other", "기타")],
        string="항목 유형", default="dimensional",
    )
    special_characteristic = fields.Selection(
        [("none", "없음"), ("cc", "CC - 중요"), ("sc", "SC - 특별")],
        string="특별 특성", default="none",
    )
    specification = fields.Char(string="규격 / 공차")
    measurement_method = fields.Char(string="측정 방법 / 게이지")
    measured_value = fields.Char(string="측정값")
    result = fields.Selection(
        [("pass", "합격"), ("fail", "불합격"), ("na", "해당없음")],
        string="판정", default="pass",
    )
    notes = fields.Char(string="비고")

    def _lock_auto_evidence_parents(self, parents):
        parents.check_access('write')
        if parents:
            parents.flush_recordset(['auto_evidence_snapshot'])
            self.env.cr.execute(
                'UPDATE iatf_process_inspection SET write_date=write_date WHERE id IN %s',
                [tuple(sorted(parents.ids))])
            parents.invalidate_recordset(['auto_evidence_snapshot'])
            if parents.filtered('auto_evidence_snapshot'):
                raise UserError(_('이미 연동한 검사항목은 변경·추가·삭제할 수 없습니다. 새 검사로 정정하세요.'))

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['inspection_id'])
        parents = self.env['iatf.process.inspection'].browse([
            vals.get('inspection_id', defaults.get('inspection_id')) for vals in vals_list
            if vals.get('inspection_id', defaults.get('inspection_id'))])
        self._lock_auto_evidence_parents(parents)
        return super().create(vals_list)

    def write(self, vals):
        self.check_access('write')
        parents = self.inspection_id | self.env['iatf.process.inspection'].browse(vals.get('inspection_id'))
        self._lock_auto_evidence_parents(parents)
        return super().write(vals)

    def unlink(self):
        self.check_access('unlink')
        self._lock_auto_evidence_parents(self.inspection_id)
        return super().unlink()
