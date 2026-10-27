from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

RATINGS = [('unknown', '모름 / 미평가'), ('good', '양호'), ('partial', '보완'), ('poor', '미흡'), ('na', '해당없음')]
LOCKED = ('report', 'follow_up', 'closed', 'cancelled')
_TOKEN = object()


class SqAudit(models.Model):
    _inherit = 'iatf.audit'
    audit_type = fields.Selection(selection_add=[('sq', 'SQ 자체 평가')], ondelete={'sq': 'set default'})
    sq_standard_id = fields.Many2one('sq.standard', string='SQ 기준 개정', ondelete='restrict')
    sq_line_ids = fields.One2many('sq.assessment.line', 'audit_id', string='SQ 평가 항목')
    sq_date_from = fields.Date('증빙 시작일')
    sq_date_to = fields.Date('증빙 종료일')
    sq_raw_score = fields.Float('원시 득점', compute='_compute_sq_score')
    sq_applicable = fields.Float('해당 배점', compute='_compute_sq_score')
    sq_score = fields.Float('1000점 환산', compute='_compute_sq_score')
    sq_unknown = fields.Integer('미평가 항목', compute='_compute_sq_score')
    sq_area_scores = fields.Text('영역별 득점', compute='_compute_sq_score')
    sq_ratios = fields.Json('평가 시작 시 비율', readonly=True, copy=False)
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('audit_type', self.env.context.get('default_audit_type')) == 'sq':
                if vals.get('state', 'planned') != 'planned' or vals.get('sq_line_ids') or vals.get('sq_ratios'):
                    raise UserError(_('SQ 평가는 계획 상태에서 항목 생성 후 진행하십시오.'))
        return super().create(vals_list)

    @api.depends('sq_line_ids.score', 'sq_line_ids.rating', 'sq_line_ids.points')
    def _compute_sq_score(self):
        for audit in self:
            lines = audit.sq_line_ids
            audit.sq_raw_score = sum(lines.mapped('score'))
            audit.sq_applicable = sum(lines.filtered(lambda l: l.rating != 'na').mapped('points'))
            audit.sq_score = 1000 * audit.sq_raw_score / audit.sq_applicable if audit.sq_applicable else 0
            audit.sq_unknown = len(lines.filtered(lambda l: l.rating == 'unknown'))
            areas = {}
            for line in lines:
                key = line.item_id.area_id.name
                values = areas.setdefault(key, [0, 0])
                values[0] += line.score
                values[1] += line.points if line.rating != 'na' else 0
            audit.sq_area_scores = '\n'.join(f'{k}: {v[0]:g} / {v[1]:g}' for k, v in areas.items())

    @api.constrains('sq_standard_id', 'company_id', 'audit_type', 'sq_date_from', 'sq_date_to')
    def _check_sq(self):
        for audit in self.filtered(lambda a: a.audit_type == 'sq'):
            if not audit.sq_standard_id or audit.company_id != audit.sq_standard_id.company_id:
                raise ValidationError(_('같은 회사의 SQ 기준을 선택하십시오.'))
            if audit.sq_date_from and audit.sq_date_to and audit.sq_date_from > audit.sq_date_to:
                raise ValidationError(_('증빙 기간을 확인하십시오.'))

    def write(self, vals):
        if vals.get('audit_type') == 'sq' and any(a.audit_type != 'sq' for a in self):
            raise UserError(_('기존 감사를 SQ로 전환하지 말고 SQ 기준에서 새 평가서를 작성하십시오.'))
        if 'sq_ratios' in vals and self.env.context.get('_sq_init') is not _TOKEN:
            raise UserError(_('채점 비율은 평가 항목 생성 시 기록합니다.'))
        for audit in self.filtered(lambda a: a.audit_type == 'sq'):
            if audit.sq_line_ids and {'sq_standard_id', 'company_id', 'audit_type', 'sq_ratios'} & vals.keys():
                raise UserError(_('평가 시작 후 회사·기준·비율은 변경할 수 없습니다.'))
            if audit.state in LOCKED and {'sq_date_from', 'sq_date_to', 'sq_line_ids'} & vals.keys():
                raise UserError(_('발행된 SQ 평가는 수정할 수 없습니다.'))
            if audit.state in LOCKED and vals.get('state') in ('planned', 'in_progress'):
                raise UserError(_('발행된 평가는 새 평가서로 재평가하십시오.'))
            if vals.get('state') in ('report', 'follow_up', 'closed'):
                audit._sq_validate_complete()
        result = super().write(vals)
        if {'sq_date_from', 'sq_date_to'} & vals.keys():
            self.filtered(lambda a: a.audit_type == 'sq').sq_line_ids.with_context(_sq_init=_TOKEN).write({
                'proposed_rating': 'unknown', 'proposed_reason': '증빙 기간 변경: 제안을 다시 조회하십시오.',
                'evidence_snapshot': False})
        return result

    def action_start(self):
        # An audit's date is a local business date, not the UTC server date.
        sq = self.filtered(lambda audit: audit.audit_type == 'sq')
        other = self - sq
        result = super(SqAudit, other).action_start() if other else None
        for audit in sq:
            audit.write({'state': 'in_progress', 'actual_date': fields.Date.context_today(audit)})
        return result

    def action_sq_initialize(self):
        self.ensure_one()
        self.check_access('write')
        if self.audit_type != 'sq' or self.state not in ('planned', 'in_progress'):
            raise UserError(_('계획 또는 진행 중인 SQ 평가에서 실행하십시오.'))
        if self.sq_line_ids:
            raise UserError(_('평가 항목이 이미 생성되어 있습니다.'))
        standard = self.sq_standard_id
        standard.check_access('read')
        if standard.scored_points <= 0:
            raise UserError(_('평가 대상 배점이 있는 기준만 평가할 수 있습니다.'))
        self.with_context(_sq_init=_TOKEN).write({'sq_ratios': {key: standard[key + '_ratio'] for key in ('good', 'partial', 'poor')}})
        self.env['sq.assessment.line'].with_context(_sq_init=_TOKEN).create([{'audit_id': self.id, 'item_id': item.id,
            'points': 0 if item.internal_only else item.points,
            'requirement_snapshot': item.requirement} for item in standard.item_ids])

    def _sq_validate_complete(self):
        self.ensure_one()
        if not self.sq_line_ids or set(self.sq_line_ids.item_id.ids) != set(self.sq_standard_id.item_ids.ids):
            raise UserError(_('SQ 기준의 모든 항목을 평가해야 합니다.'))
        if self.sq_unknown or not self.sq_applicable:
            raise UserError(_('미평가 항목 또는 전체 해당없음 상태에서는 확정할 수 없습니다.'))
        if any(not (line.reason or '').strip() for line in self.sq_line_ids):
            raise UserError(_('모든 항목의 심사 판단 근거를 입력하십시오.'))

    def action_sq_propose(self):
        self.ensure_one()
        self.check_access('write')
        if self.state in LOCKED:
            raise UserError(_('발행된 평가에는 제안을 갱신할 수 없습니다.'))
        if not self.sq_date_from or not self.sq_date_to:
            raise UserError(_('증빙 시작일과 종료일을 입력하십시오.'))
        for line in self.sq_line_ids:
            rules = line.item_id.rule_ids.with_context(sq_date_from=str(self.sq_date_from), sq_date_to=str(self.sq_date_to))
            snapshots = [r._snapshot() for r in rules]
            metrics = [rule._metric_result() for rule in rules]
            ratings = {m['rating'] for m in metrics}
            # A bad signal is retained; incomplete evidence never becomes an all-good proposal.
            rating = ('poor' if 'poor' in ratings else 'unknown' if not ratings or 'unknown' in ratings
                      else 'partial' if 'partial' in ratings else 'good')
            for snapshot, metric in zip(snapshots, metrics):
                snapshot['metric'] = metric
            reason = '\n'.join('%s: %s' % (rule.name, metric['reason']) for rule, metric in zip(rules, metrics))
            line.with_context(_sq_init=_TOKEN).write({'proposed_rating': rating,
                        'proposed_reason': reason or '현장 확인 항목: 심사자가 근거를 확인해야 합니다.',
                        'evidence_snapshot': snapshots})



class SqAssessmentLine(models.Model):
    _name = 'sq.assessment.line'
    _description = 'SQ 평가 항목 판정'
    _check_company_auto = True
    audit_id = fields.Many2one('iatf.audit', required=True, ondelete='cascade', check_company=True)
    company_id = fields.Many2one(related='audit_id.company_id', store=True)
    item_id = fields.Many2one('sq.item', string='SQ 항목', required=True, ondelete='restrict', check_company=True)
    points = fields.Float('배점', required=True, readonly=True)
    requirement_snapshot = fields.Text('평가 기준 원문', readonly=True)
    rating = fields.Selection(RATINGS, default='unknown', required=True, string='심사자 판정')
    score = fields.Float('득점', compute='_compute_score', store=True)
    reason = fields.Text('판단 근거 / 해당없음 확인')
    finding = fields.Text('지적사항')
    action = fields.Text('조치 계획')
    proposed_rating = fields.Selection(RATINGS, readonly=True, string='제안')
    proposed_reason = fields.Text('제안 근거', readonly=True)
    evidence_snapshot = fields.Json('증빙 조회 시점 기록', readonly=True)
    _sql_constraints = [('line_key', 'unique(audit_id,item_id)', '동일 평가 항목 중복입니다.')]

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('_sq_init') is not _TOKEN:
            raise UserError(_('SQ 평가서의 항목 생성 버튼을 사용하십시오.'))
        return super().create(vals_list)

    @api.depends('rating', 'points', 'audit_id.sq_ratios')
    def _compute_score(self):
        for line in self:
            line.score = line.points * (line.audit_id.sq_ratios or {}).get(line.rating, 0)

    @api.constrains('audit_id', 'item_id', 'rating', 'reason')
    def _check_line(self):
        for line in self:
            if line.audit_id.audit_type != 'sq' or line.audit_id.sq_standard_id != line.item_id.standard_id:
                raise ValidationError(_('평가와 같은 SQ 기준 항목만 연결하십시오.'))
            if line.rating == 'na' and not (line.reason or '').strip():
                raise ValidationError(_('해당없음은 담당자 확인 근거가 필요합니다.'))

    def write(self, vals):
        if any(l.audit_id.state in LOCKED for l in self):
            raise UserError(_('발행된 평가 항목은 수정할 수 없습니다.'))
        if {'proposed_rating', 'proposed_reason', 'evidence_snapshot'} & vals.keys() and self.env.context.get('_sq_init') is not _TOKEN:
            raise UserError(_('제안과 증빙 스냅샷은 증빙 조회·제안 버튼으로 생성하십시오.'))
        if {'audit_id', 'item_id', 'points', 'requirement_snapshot'} & vals.keys():
            raise UserError(_('평가 항목과 배점은 기준 개정에서 결정합니다.'))
        return super().write(vals)

    def unlink(self):
        if not self.env.context.get('module_uninstall') and any(l.audit_id.state in LOCKED for l in self):
            raise UserError(_('발행된 평가 항목은 삭제할 수 없습니다.'))
        return super().unlink()

    def action_accept_proposal(self):
        for line in self:
            if not line.proposed_rating or line.proposed_rating == 'unknown':
                raise UserError(_('미확인 제안은 확정할 수 없습니다.'))
            if not (line.reason or '').strip():
                raise UserError(_('심사자의 확인 근거를 먼저 입력하십시오.'))
            line.rating = line.proposed_rating

    def action_evidence(self):
        self.ensure_one()
        self.check_access('read')
        return self.item_id.with_context(
            sq_date_from=fields.Date.to_string(self.audit_id.sq_date_from),
            sq_date_to=fields.Date.to_string(self.audit_id.sq_date_to),
        ).action_evidence()


class SqPackage(models.TransientModel):
    _name = 'sq.package'
    _description = '사용자별 SQ 심사 패키지'
    name = fields.Char('명칭', required=True)
    data = fields.Binary(required=True, attachment=False)
