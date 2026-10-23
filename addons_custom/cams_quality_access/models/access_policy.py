"""Optional integration ACLs: read only, explicit users, no business data changes."""
from odoo import api, models
from .policy import QUALITY_SOURCES, SQ_SOURCES, SQ_CHILD_FIELDS, SHARED_SOURCES


class QualityAccessPolicy(models.AbstractModel):
    _name = 'cams.quality.access.policy'
    _description = '품질·SQ 조회 권한 설치 정책'

    @api.model
    def _scope(self, model_name, path, shared=False):
        target = self.env[model_name]
        for part in path.split('.'):
            field = target._fields.get(part)
            if not field or field.type != 'many2one':
                raise ValueError('Invalid company path: %s.%s' % (model_name, path))
            target = self.env[field.comodel_name]
        if target._name != 'res.company':
            raise ValueError('Company scope required: %s' % model_name)
        return "[('%s', 'in', %scompany_ids)]" % (path, '[False] + ' if shared else '')

    @api.model
    def _owned(self, model, key, values):
        xmlid = 'cams_quality_access.' + key
        record = self.env.ref(xmlid, raise_if_not_found=False)
        if record:
            record.write(values)
        else:
            record = self.env[model].create(values)
            self.env['ir.model.data'].create({
                'module': 'cams_quality_access', 'name': key,
                # Function-created XMLIDs must survive the loader's end-of-update
                # obsolete-record cleanup. _sync_access still updates them explicitly.
                'model': model, 'res_id': record.id, 'noupdate': True,
            })
        return record

    @api.model
    def _sync_access(self):
        # Private method: unavailable over RPC. XML loader runs as administrator.
        for role, sources in [('quality', QUALITY_SOURCES), ('sq', SQ_SOURCES)]:
            policy = dict(sources)
            if role == 'sq':
                for parent, name in SQ_CHILD_FIELDS:
                    if parent not in self.env:
                        continue
                    field = self.env[parent]._fields.get(name)
                    if not field or field.type != 'one2many':
                        raise ValueError('Reviewed child field changed: %s.%s' % (parent, name))
                    policy.setdefault(field.comodel_name, field.inverse_name + '.' + sources[parent])
            group = self.env.ref('cams_quality_access.group_' + role + '_source_reader')
            for name, path in sorted(policy.items()):
                if name not in self.env:
                    continue  # Optional source addon; run -u after installing it.
                domain = self._scope(name, path, name in SHARED_SOURCES)
                if name == 'iatf.inspection.criteria':
                    domain = domain[:-1] + ", '|', ('supplier_id', '=', False), ('supplier_id.company_id', 'in', [False] + company_ids)]"
                model = self.env['ir.model']._get(name)
                key = role + '_' + name.replace('.', '_')
                self._owned('ir.model.access', 'access_' + key, {
                    'name': '품질/SQ 조회: ' + name, 'model_id': model.id,
                    'group_id': group.id, 'perm_read': True,
                    'perm_write': False, 'perm_create': False, 'perm_unlink': False,
                })
                self._owned('ir.rule', 'scope_' + key, {
                    'name': '품질/SQ 회사 범위: ' + name, 'model_id': model.id,
                    'groups': [(6, 0, group.ids)], 'domain_force': domain,
                    'perm_read': True, 'perm_write': False,
                    'perm_create': False, 'perm_unlink': False,
                })
