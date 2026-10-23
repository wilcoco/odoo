import json
import math
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.osv import expression


class SqEvidenceMetrics(models.Model):
    _inherit = 'sq.evidence.rule'

    metric_kind = fields.Selection([
        ('count', '건수 / 내용 확인'), ('pass_rate', '판정 건수 합격률'),
        ('cpk', '평균 Cpk'), ('grr', '평균 %GRR'),
        ('calibration', '기한 내 정상 교정 비율'), ('closure', '종결률'),
        ('approval', '승인·완료 건수'), ('field_rate', '현장 기록 적합률'),
    ], string='제안 지표', required=True, default='count')
    metric_field = fields.Char('지표 필드')
    metric_domain_json = fields.Text('지표 대상 조건 (JSON)', default='[]', required=True)
    positive_values = fields.Char('정상·완료 값 (쉼표 구분)', default='pass')
    decided_values = fields.Char('판정 완료 값 (쉼표 구분)', default='pass,fail,conditional')
    good_threshold = fields.Float('양호 제안 경계', default=95)
    partial_threshold = fields.Float('보완 제안 경계', default=80)
    minimum_samples = fields.Integer('최소 표본 수', default=1)
    metric_source = fields.Char('지표 설정 출처')

    @api.constrains('metric_domain_json', 'minimum_samples', 'good_threshold', 'partial_threshold', 'metric_kind')
    def _check_metric_config(self):
        for rule in self:
            try:
                assert isinstance(json.loads(rule.metric_domain_json), list)
            except (ValueError, TypeError, AssertionError):
                raise ValidationError(_('지표 대상 조건은 JSON 목록이어야 합니다.'))
            if rule.minimum_samples < 1 or not all(math.isfinite(v) for v in (rule.good_threshold, rule.partial_threshold)):
                raise ValidationError(_('최소 표본은 1 이상이고 경계값은 유한한 숫자여야 합니다.'))
            if rule.metric_kind == 'grr':
                valid = 0 <= rule.good_threshold <= rule.partial_threshold
            else:
                valid = rule.good_threshold >= rule.partial_threshold >= 0
            if rule.metric_kind in ('pass_rate', 'field_rate', 'calibration', 'closure'):
                valid = valid and rule.good_threshold <= 100
            if not valid:
                raise ValidationError(_('지표 방향에 맞는 양호·보완 경계값을 입력하십시오.'))

    def _metric_result(self):
        """Calculate an advisory result under source ACLs, never an audit decision."""
        self.ensure_one()
        unknown = {'rating': 'unknown', 'value': None, 'samples': 0}
        try:
            target, domain = self._target()
            domain = expression.AND([domain, json.loads(self.metric_domain_json)])
            records = target.search(domain, limit=10001)
            if len(records) > 10000:
                return dict(unknown, reason='지표 대상이 10,000건을 넘습니다. 기간을 줄여 주세요.')
            n = len(records)
            if not n:
                return dict(unknown, reason='모름: 기간 내 판정 가능한 기록이 0건입니다.')
            kind = self.metric_kind
            value = None
            if kind == 'count':
                value = n
                rating = 'partial' if n >= self.minimum_count else 'unknown'
            else:
                field = target._fields.get(self.metric_field)
                if not field:
                    return dict(unknown, reason='지표 필드가 없습니다. 원천 설정을 확인하십시오.')
                # read() enforces field-level security as well as record access.
                names = [self.metric_field]
                if kind == 'calibration':
                    names += ['result']
                rows = records.read(names)
                positives = {v.strip() for v in (self.positive_values or '').split(',') if v.strip()}
                decided = {v.strip() for v in (self.decided_values or '').split(',') if v.strip()}
                if kind in ('cpk', 'grr'):
                    if field.type not in ('float', 'integer'):
                        return dict(unknown, reason='지표 필드가 숫자 형식이 아닙니다.')
                    values = [r[self.metric_field] for r in rows]
                    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
                        return dict(unknown, reason='계산 가능한 지표가 없습니다.')
                    if kind == 'grr' and any(v < 0 for v in values):
                        return dict(unknown, reason='음수 %GRR은 유효한 측정 결과가 아닙니다.')
                    value = sum(values) / n
                elif kind in ('pass_rate', 'field_rate'):
                    values = [r[self.metric_field] for r in rows if r[self.metric_field] in decided]
                    n = len(values)
                    value = 100 * sum(v in positives for v in values) / n if n else None
                elif kind == 'calibration':
                    if field.type != 'date':
                        return dict(unknown, reason='교정 예정일 필드가 날짜 형식이 아닙니다.')
                    asof = fields.Date.to_date(self.env.context.get('sq_date_to')) or fields.Date.context_today(self)
                    # Missing due dates are unknown, not valid indefinitely.
                    if any(not row[self.metric_field] for row in rows):
                        return dict(unknown, reason='다음 교정 예정일이 없는 기록이 있습니다.', samples=n)
                    value = 100 * sum(fields.Date.to_date(r[self.metric_field]) >= asof and r['result'] in positives for r in rows) / n
                elif kind == 'closure':
                    value = 100 * sum(r[self.metric_field] in positives for r in rows) / n
                elif kind == 'approval':
                    value = sum(r[self.metric_field] in positives for r in rows)
                if value is None or n < self.minimum_samples:
                    return dict(unknown, samples=n, reason='모름: 판정 완료 표본이 최소 기준에 미달합니다.')
                if kind == 'grr':
                    rating = 'good' if value < self.good_threshold else 'partial' if value <= self.partial_threshold else 'poor'
                else:
                    rating = 'good' if value >= self.good_threshold else 'partial' if value >= self.partial_threshold else 'poor'
            if n < self.minimum_samples:
                rating = 'unknown'
            reason = '%s = %g / 표본 %d건. ' % (dict(self._fields['metric_kind'].selection)[kind], value, n)
            if not self.proposal_enabled or not (self.proposal_source or '').strip():
                rating = 'unknown'
                reason += '임계값 실데이터 검증 전: 심사자가 확인해야 합니다.'
            else:
                reason += '검증 근거: %s. 최종 판정은 심사자가 확인합니다.' % self.proposal_source
            return {'rating': rating, 'value': value, 'samples': n, 'reason': reason,
                    'kind': kind, 'good_threshold': self.good_threshold, 'partial_threshold': self.partial_threshold,
                    'source': self.proposal_source, 'asof': self.env.context.get('sq_date_to')}
        except (AccessError, UserError, ValueError, TypeError) as error:
            return dict(unknown, reason=str(error), unavailable=True)

    def _configure_metric_defaults(self):
        """Seed proposal templates, leaving human validation disabled and edits intact."""
        presets = {
            'iatf.spc.study': ('cpk', 'cpk', 1.33, 1.0, [['state', 'in', ['analyzed', 'closed']]], ''),
            'iatf.msa.study': ('grr', 'pct_grr', 10, 30, [['state', 'in', ['analyzed', 'closed']]], ''),
            'iatf.incoming.inspection': ('pass_rate', 'result', 95, 0, [['state', 'in', ['decided', 'closed']]], 'pass'),
            'iatf.process.inspection': ('pass_rate', 'result', 95, 0, [['state', 'in', ['decided', 'closed']]], 'pass'),
            'iatf.shipping.inspection': ('pass_rate', 'result', 95, 0, [['state', 'in', ['decided', 'closed']]], 'pass'),
            'iatf.calibration.record': ('calibration', 'next_due_date', 100, 0, [], 'pass,adjusted'),
            'iatf.nonconformity': ('closure', 'state', 90, 70, [['state', '!=', 'cancelled']], 'closed'),
            'iatf.check.record': ('field_rate', 'overall_result', 95, 80, [['state', '=', 'done']], 'ok'),
        }
        for rule in self.filtered(lambda r: not r.metric_source and not r.proposal_enabled):
            preset = presets.get(rule.model_name)
            if not preset and rule.model_name in ('iatf.ppap', 'iatf.apqp', 'iatf.fmea', 'iatf.control.plan', 'iatf.document'):
                preset = ('approval', 'state', 1, 0, [], 'approved,completed,closed')
            if not preset:
                continue
            kind, field, good, partial, domain, positive = preset
            rule.write({'metric_kind': kind, 'metric_field': field, 'good_threshold': good,
                        'partial_threshold': partial, 'metric_domain_json': json.dumps(domain),
                        'positive_values': positive,
                        'decided_values': 'ok,issue' if kind == 'field_rate' else 'pass,fail,conditional',
                        'metric_source': 'sq-spec/10 참고값 · 2026-10-19 3단계 판정에 매핑 · 실데이터 검증 전'})
