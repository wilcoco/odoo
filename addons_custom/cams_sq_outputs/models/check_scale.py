from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

SCORES = [(str(value), str(value)) for value in range(1, 6)]


class Item(models.Model):
    _inherit = 'iatf.check.sheet.item'
    five_point_required = fields.Boolean('5점 평가 사용')
    five_point_definition = fields.Text('5~1점 실제 판정 기준')
    stop_score = fields.Selection(SCORES, string='이 점수 이하 가동중지 기준')

    @api.constrains('five_point_required', 'five_point_definition', 'stop_score')
    def _check_scale_definition(self):
        for item in self:
            if item.five_point_required and not (item.five_point_definition or '').strip():
                raise ValidationError(_('5점 평가를 사용하려면 실제 판정 기준을 먼저 입력하십시오.'))
            if item.stop_score and not item.five_point_required:
                raise ValidationError(_('가동중지 점수는 5점 평가 항목에만 지정하십시오.'))

    def write(self, values):
        changed = {'five_point_required', 'five_point_definition', 'stop_score'} & values.keys()
        before = {item.id: {key: item[key] for key in changed} for item in self}
        result = super().write(values)
        for item in self:
            actual = [key for key in changed if before[item.id][key] != item[key]]
            if actual:
                item.sheet_id._log_revision(_('5점 평가 기준 변경: %s') % item.name)
        return result


class Line(models.Model):
    _inherit = 'iatf.check.record.line'
    five_point_required = fields.Boolean('당시 5점 평가 사용', readonly=True)
    five_point_definition = fields.Text('당시 점수 기준', readonly=True)
    stop_score = fields.Selection(SCORES, string='당시 가동중지 점수', readonly=True)
    five_point_score = fields.Selection(SCORES, string='실제 평가점수')

    @api.model_create_multi
    def create(self, values):
        prepared = []
        for value in values:
            value = dict(value)
            item = self.env['iatf.check.sheet.item'].browse(value.get('item_id', self.env.context.get('default_item_id'))).exists()
            if item:
                item.check_access('read')
            for key in ('five_point_required', 'five_point_definition', 'stop_score'):
                value[key] = item[key] if item else False
            prepared.append(value)
        return super().create(prepared)

    def write(self, values):
        if {'five_point_required', 'five_point_definition', 'stop_score'} & values.keys():
            raise UserError(_('완료 여부와 관계없이 당시 점수 기준은 변경할 수 없습니다. 새 점검을 만드십시오.'))
        return super().write(values)


class Record(models.Model):
    _inherit = 'iatf.check.record'

    def _derive_overall(self):
        result, ng, na = super()._derive_overall()
        stopped = self.line_ids.filtered(lambda line: line.five_point_required and line.five_point_score
            and line.stop_score and int(line.five_point_score) <= int(line.stop_score))
        if stopped and result != 'pending':
            return 'issue', len(stopped | self.line_ids.filtered(lambda line: line.result == 'ng')), na
        return result, ng, na

    @api.depends('line_ids.five_point_score', 'line_ids.stop_score', 'line_ids.five_point_required',
                 'line_ids.result', 'line_ids.remark', 'line_ids.spec_min', 'line_ids.spec_max')
    def _compute_overall(self):
        return super()._compute_overall()

    @api.constrains('state', 'line_ids', 'corrective_action')
    def _check_done_is_complete(self):
        result = super()._check_done_is_complete()
        for record in self.filtered(lambda r: r.state == 'done'):
            if any(line.five_point_required and not line.five_point_score for line in record.line_ids):
                raise ValidationError(_('5점 평가 항목의 실제 점수가 없습니다.'))
            stopped = record.line_ids.filtered(lambda line: line.five_point_required and line.five_point_score
                and line.stop_score and int(line.five_point_score) <= int(line.stop_score))
            if stopped and not (record.corrective_action or '').strip():
                raise ValidationError(_('가동중지 기준에 해당합니다. 책임자 보고와 실제 조치를 기록하십시오.'))
        return result

    def _snapshot_line_payload(self, line):
        data = super()._snapshot_line_payload(line)
        data.update({'5점평가사용': line.five_point_required, '점수기준': line.five_point_definition or '',
            '중지점수': line.stop_score or '', '실제점수': line.five_point_score or ''})
        return data
