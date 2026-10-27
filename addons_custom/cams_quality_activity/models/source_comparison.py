"""Read original business records; never manufacture an SQ pass or ledger."""
from markupsafe import Markup
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class ManufacturingSourceComparison(models.TransientModel):
    _name = 'cams.manufacturing.source.comparison'
    _description = '생산·품질 원천 자료 대조'

    company_id = fields.Many2one('res.company', required=True, default=lambda s: s.env.company)
    production_id = fields.Many2one('mrp.production', '생산지시', required=True, check_company=True)
    daily_html = fields.Html('생산일보·점검표', compute='_compute_comparison', sanitize=True)
    material_html = fields.Html('원재료 LOT·성적서·장부', compute='_compute_comparison', sanitize=True)
    mold_html = fields.Html('금형 변경·초중종물', compute='_compute_comparison', sanitize=True)
    condition_html = fields.Html('성형조건·실측', compute='_compute_comparison', sanitize=True)
    shipping_html = fields.Html('출하 성적서·생산 LOT', compute='_compute_comparison', sanitize=True)

    def _source_table(self, title, model_name, domain, columns):
        """Normal ACL/rules only. Each bounded table discloses truncation/counts.

        Domain/columns are code-owned, never accepted from an RPC caller.
        Lack of access, lack of integration and zero data remain distinct.
        """
        heading = Markup('<h4>%s</h4>') % title
        if model_name not in self.env:
            return heading + Markup('<p>원천 모듈 미설치 — 연결 확인 필요</p>')
        source = self.env[model_name]
        if not source.has_access('read'):
            return heading + Markup('<p>원천 조회 권한 없음 — 해당 업무 역할 확인 필요</p>')
        missing = [field for field in columns if field not in source._fields]
        if missing:
            return heading + Markup('<p>원천 필드 연결 확인 필요: %s</p>') % ', '.join(missing)
        # Active/inactive sources both matter when reviewing historical evidence.
        source = source.with_context(active_test=False)
        try:
            count = source.search_count(domain)
            rows = source.search(domain, order='id', limit=100)
            values = rows.read(list(columns))
        except AccessError:
            return heading + Markup('<p>원천 또는 연결 자료 조회 권한 없음 — 해당 업무 역할 확인 필요</p>')
        if not values:
            return heading + Markup('<p>연결된 자료 0건 — 모름, 적합 판정 불가</p>')
        html = heading + Markup('<p>조회 가능한 원천 %s건 중 %s건 표시. 아래 링크에서 원본을 확인하십시오.</p>') % (count, len(values))
        html += Markup('<table class="table table-sm"><thead><tr><th>원본</th>')
        for label in columns.values():
            html += Markup('<th>%s</th>') % label
        html += Markup('</tr></thead><tbody>')
        for value in values:
            html += Markup('<tr><td><a href="/web#model=%s&amp;id=%s&amp;view_type=form">#%s</a></td>') % (model_name, value['id'], value['id'])
            for field in columns:
                item = value.get(field)
                if source._fields[field].type == 'many2one' and item:
                    item = item[1]
                if source._fields[field].type == 'selection' and item:
                    item = dict(source._fields[field]._description_selection(self.env)).get(item, item)
                if source._fields[field].type == 'boolean':
                    item = '예' if item else '아니요'
                elif item is False or item is None:
                    item = '미입력'
                elif source._fields[field].type == 'datetime' and item:
                    item = fields.Datetime.context_timestamp(self, fields.Datetime.to_datetime(item)).strftime('%Y-%m-%d %H:%M:%S')
                html += Markup('<td>%s</td>') % str(item)
            html += Markup('</tr>')
        return html + Markup('</tbody></table>')

    def _actual_lots(self, mo, raw=False):
        moves = self.env['stock.move.line']
        moves.check_access('read')
        field = 'move_id.raw_material_production_id' if raw else 'move_id.production_id'
        return moves.search([(field, '=', mo.id), ('company_id', '=', self.company_id.id),
            ('state', '=', 'done'), ('quantity', '>', 0), ('lot_id', '!=', False)]).lot_id

    @api.depends('production_id', 'company_id')
    def _compute_comparison(self):
        for wizard in self:
            empty = Markup('<p>생산지시를 선택하십시오.</p>')
            wizard.daily_html = wizard.material_html = wizard.mold_html = wizard.condition_html = wizard.shipping_html = empty
            if not wizard.production_id:
                continue
            mo = wizard.production_id
            mo.check_access('read')
            if wizard.company_id not in self.env.companies or mo.company_id != wizard.company_id:
                raise UserError(_('현재 허용 회사의 생산지시만 대조할 수 있습니다.'))
            company = [('company_id', '=', wizard.company_id.id)]
            table = wizard._source_table
            warning = Markup('<p><strong>원천 연결 대조 화면입니다. 자료 존재나 수량만으로 합격을 판정하지 않습니다.</strong> 명시적으로 연결된 생산지시·실제 재고 이동의 LOT만 조회합니다.</p>')
            wizard.daily_html = warning + table('생산지시', 'mrp.production', [('id', '=', mo.id)] + company,
                {'name': '지시', 'product_id': '품번', 'product_qty': '지시 수량', 'qty_produced': '생산 수량', 'state': '상태'})
            wizard.daily_html += table('사출 생산 원천', 'injection.production.record', [('mo_id', '=', mo.id)] + company,
                {'production_date': '생산 일시', 'lot_id': '생산 LOT', 'raw_material_lot_id': '원재료 LOT', 'workcenter_id': '설비', 'measured_weight': '실측 중량', 'weight_is_measured': '실측 여부'})
            wizard.daily_html += table('연결된 일상 점검표', 'iatf.check.record', [('production_id', '=', mo.id)] + company,
                {'sheet_id': '점검 시트', 'check_date': '점검일', 'lot_id': 'LOT', 'workcenter_id': '설비', 'state': '상태', 'overall_result': '판정'})
            wizard.material_html = warning
            wizard.shipping_html = warning
            try:
                raw_lots = wizard._actual_lots(mo, raw=True)
                finished_lots = wizard._actual_lots(mo)
            except AccessError:
                wizard.material_html += Markup('<p>실제 투입 LOT 조회 권한 없음 — 재고 조회 역할 확인 필요</p>')
                wizard.shipping_html += Markup('<p>실제 생산 LOT 조회 권한 없음 — 재고 조회 역할 확인 필요</p>')
            else:
                wizard.material_html += table('실제 투입 LOT', 'stock.lot', [('id', 'in', raw_lots.ids)] + company,
                    {'name': 'LOT', 'product_id': '원료 품번'})
                wizard.material_html += table('원료 수입검사·공급자 성적서', 'iatf.incoming.inspection', [('lot_id', 'in', raw_lots.ids)] + company,
                    {'name': '검사', 'lot_id': '입고 LOT', 'supplier_cert_no': '성적서 번호', 'certificate_lot_name': '성적서 LOT', 'certificate_plant': '공장', 'certificate_expiry_date': '유효 기한', 'state': '상태'})
                wizard.material_html += table('원료 LOT를 사용한 배합 장부', 'iatf.blend.log', [('line_ids.lot_id', 'in', raw_lots.ids)] + company,
                    {'name': '배합', 'blend_date': '배합일', 'production_id': '연결 지시', 'lot_id': '산출 LOT', 'total_qty': '투입 kg', 'state': '상태', 'result': '판정'})
                wizard.shipping_html += table('실제 생산 입고 LOT', 'stock.lot', [('id', 'in', finished_lots.ids)] + company,
                    {'name': 'LOT', 'product_id': '품번'})
                wizard.shipping_html += table('출하 전표 LOT 이동', 'stock.move.line', [('lot_id', 'in', finished_lots.ids), ('picking_id.picking_type_id.code', '=', 'outgoing')] + company,
                    {'picking_id': '출하', 'lot_id': 'LOT', 'product_id': '품번', 'quantity': '수량', 'state': '처리 상태'})
                wizard.shipping_html += table('출하검사 성적서', 'iatf.shipping.inspection', [('lot_id', 'in', finished_lots.ids)] + company,
                    {'name': '검사', 'shipping_date': '출하일', 'lot_id': 'LOT', 'picking_id': '출하 전표', 'quantity': '검사 수량', 'state': '상태', 'result': '판정', 'approval_state': '승인'})
            wizard.mold_html = warning + table('생산지시의 금형 변경 작업 이력', 'injection.worker.log',
                [('mo_id', '=', mo.id), ('action_type', '=', 'change_mold'), ('mo_id.company_id', '=', wizard.company_id.id)],
                {'timestamp': '변경 시각', 'notes': '변경 내역', 'mo_id': '생산지시'})
            wizard.mold_html += Markup('<p>변경 시각 전후 검사와 교대·초중종물 누락을 담당자가 확인하십시오. 시간만으로 검사와 변경을 자동 연결하지 않습니다.</p>')
            wizard.mold_html += table('동일 생산지시의 공정검사', 'iatf.process.inspection', [('production_id', '=', mo.id)] + company,
                {'name': '검사', 'inspection_date': '검사 시각', 'article_stage': '초중종물', 'lot_id': 'LOT', 'state': '상태', 'result': '결과', 'approval_state': '승인'})
            wizard.condition_html = warning + table('명시적으로 생산품에 매칭된 샷의 성형조건', 'injection.machine.shot.measurement',
                [('shot_id.link_ids.production_record_id.mo_id', '=', mo.id)] + company,
                {'shot_id': '샷', 'metric': '항목', 'channel_no': '채널', 'value_kind': '실측/설정', 'value': '값', 'unit': '단위', 'condition_limit_id': '대조 기준', 'condition_status': '현행 기준 대조'})
            wizard.condition_html += Markup('<p>성형조건 표시는 원천 모듈의 현행 기준 대조입니다. 당시 승인 기준의 완료 스냅샷을 대체하지 않으며, 미매칭 샷은 이 표에 포함되지 않습니다.</p>')

    def action_refresh(self):
        self.ensure_one()
        self._compute_comparison()
        return {'type': 'ir.actions.act_window', 'res_model': self._name,
            'res_id': self.id, 'view_mode': 'form', 'target': 'current'}
