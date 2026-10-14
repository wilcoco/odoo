"""Explicit IATF boundaries. Native posting/super CRUD is never retried."""
import inspect
from odoo import models, _
from odoo.exceptions import AccessError, UserError


def run(records, callback, area, description, **options):
    if options.get('mode', 'gate') == 'gate':
        # Native business write rights are checked before the isolated quality
        # callback. Missing read rights on IATF specifications must not block it.
        records.check_access('write')
        options['allow_quality_access'] = True
    return records.env['iatf.passive.log']._run(records, callback, area, description, **options)


def stock_identity(moves):
    """Preserve company/product/LOT identity independently of quality verdicts."""
    moves.check_access('read')
    for move in moves:
        if move.company_id not in moves.env.companies:
            raise AccessError(_('허용된 회사의 재고 이동만 처리할 수 있습니다.'))
        if move.picking_id and move.picking_id.company_id != move.company_id:
            raise UserError(_('이동과 입출고의 회사가 다릅니다.'))
        for line in move.move_line_ids:
            if line.company_id != move.company_id or line.product_id != move.product_id:
                raise UserError(_('이동 상세의 회사·제품이 원본과 다릅니다.'))
            lot = line.lot_id
            if lot and (lot.product_id != line.product_id or lot.company_id and lot.company_id != line.company_id):
                raise UserError(_('LOT의 제품·회사가 이동 상세와 다릅니다.'))


class StockLot(models.Model):
    _inherit = 'stock.lot'

    def _iatf_quality_hold_blocks(self, message):
        """Optional MES adapter: bypass only IATF hold, never the MES verdict."""
        self.ensure_one()
        self.check_access('read')
        if not self.quality_hold:
            return False
        Log = self.env['iatf.passive.log']
        if not Log._enabled(self):
            return True
        frame = inspect.currentframe().f_back
        try:
            Log._record(self, 'MES/LOT 보류', 'MES에서 재확인한 IATF 보류 조건 통과; 보류 상태는 유지',
                        message, frame.f_code, error=UserError(message), caller_line=frame.f_lineno)
        finally:
            del frame
        return False


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _assert_outgoing_inspections(self, moves=None):
        self.check_access('write')
        stock_identity(moves if moves is not None else self.move_ids)
        return run(self, super()._assert_outgoing_inspections, '출하',
                   'OQC·포장/라벨 승인, 보류 LOT 및 검사 수량 일치 검증', args=(moves,))

    def _create_iqc_inspections(self):
        self.check_access('write')
        return run(self, super()._create_iqc_inspections, '입고', '입고 후 IQC 자동 생성', mode='auxiliary')

    def _check_packaging_spec(self):
        return run(self, super()._check_packaging_spec, '포장', '포장 사양 자동 경고', mode='auxiliary')


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _iqc_prepare_receipts(self):
        candidates = self.filtered(lambda m: m.state not in ('done', 'cancel') and
            m.location_id.usage == 'supplier' and m.location_dest_id.usage == 'internal' and m.product_id.is_storable)
        if not candidates:
            return super()._iqc_prepare_receipts()
        stock_identity(self)
        return run(self, super()._iqc_prepare_receipts, '입고',
                   'IQC 검사대기 위치 전환을 검증만 수행하고 기존 입고 위치 유지', mode='observe')

    def _iqc_check_pending_move(self):
        stock_identity(self)
        return run(self, super()._iqc_check_pending_move, '입고/재고', '검사대기 위치 및 IQC 승인 이동 검증')

    def _iqc_check_actual_stock(self, lines=None):
        stock_identity(self)
        return run(self, super()._iqc_check_actual_stock, '입고/재고', 'IQC 관리 품목의 가용 재고 검증', args=(lines,))

    def _kr_check_held_lots(self, stage):
        stock_identity(self)
        return run(self, super()._kr_check_held_lots, '제조/LOT', '품질 보류 LOT 제조 투입 검증: %s' % stage, args=(stage,))

    def _assert_assembly_outgoing_stock(self):
        stock_identity(self)
        return run(self, super()._assert_assembly_outgoing_stock, '출하/재고', 'IATF 조립제품 실재고·예약 검증')

    def _create_traceability_record(self):
        return run(self, super()._create_traceability_record, '추적성', '재고 완료 후 IATF 추적 이력 생성', mode='auxiliary')


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _create_pqc_inspection(self):
        self.check_access('write')
        return run(self, super()._create_pqc_inspection, '생산', '생산 완료 후 PQC 생성/계획 단위 집계',
                   mode='auxiliary', fallback=self.env['iatf.process.inspection'])

    def _update_mold_shots(self):
        return run(self, super()._update_mold_shots, '금형', '생산 완료 후 IATF 금형 타수 기록', mode='auxiliary')

    def _auto_link_control_plan(self):
        return run(self, super()._auto_link_control_plan, '관리계획', 'MO 관리계획서 자동 연결', mode='auxiliary')

    def _check_first_mo_ppap(self):
        return run(self, super()._check_first_mo_ppap, 'PPAP', '첫 MO의 PPAP 요청 자동 생성', mode='auxiliary')

    def _notify_operator_qualification(self):
        return run(self, super()._notify_operator_qualification, '교육', '작업자 자격 경고', mode='auxiliary')


class MrpWorkorder(models.Model):
    _inherit = 'mrp.workorder'

    def _check_previous_ipqc(self):
        self.check_access('write')
        return run(self, super()._check_previous_ipqc, '공정', '이전 공정 IPQC 불합격 검증')

    def _create_ipqc_inspection(self):
        self.check_access('write')
        return run(self, super()._create_ipqc_inspection, '공정', '작업 완료 후 IPQC 생성',
                   mode='auxiliary', fallback=self.env['iatf.process.inspection'])


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    def _check_pending_change_requests(self, vals):
        self.check_access('write')
        return run(self, super()._check_pending_change_requests, 'BOM/변경', '미승인 변경요청에 따른 BOM 수정 잠금', args=(vals,))

    def _create_bom_change_requests(self, vals, old_values):
        return run(self, super()._create_bom_change_requests, 'BOM/변경', 'BOM 저장 후 변경요청 자동 생성',
                   mode='auxiliary', args=(vals, old_values))


class ProcessInspection(models.Model):
    _inherit = 'iatf.process.inspection'

    def _auto_feed_spc(self):
        return run(self, super()._auto_feed_spc, 'SPC', '공정검사 판정 후 SPC 측정값 연동', mode='auxiliary')

    def _auto_create_nc(self):
        return run(self, super()._auto_create_nc, '부적합', '검사 판정 후 NC 자동 생성',
                   mode='auxiliary', fallback=self.env['iatf.nonconformity'])

    def _auto_quarantine_lot(self):
        return run(self, super()._auto_quarantine_lot, 'LOT 보류', '불합격 검사 후 LOT 보류 증빙 생성', mode='auxiliary')
