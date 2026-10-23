"""Compare supplier certificate with the actual received LOT, without new stock."""
from datetime import timedelta
from odoo import api,fields,models,_
from odoo.exceptions import AccessError,UserError,ValidationError

_POLICY={'iqc_certificate_required','iqc_shelf_life_required','iqc_shelf_life_days'}
_CERTIFICATE={'certificate_plant','certificate_lot_name','certificate_issue_date',
              'certificate_manufactured_date','certificate_expiry_date'}


class Product(models.Model):
    _inherit='product.template'
    iqc_certificate_required=fields.Boolean('입고 성적서 공장·LOT 필수')
    iqc_shelf_life_required=fields.Boolean('입고 유효기간 관리')
    iqc_shelf_life_days=fields.Integer('확정 보관 유효기간(일)',help='고객·재질 기준을 확인하여 입력합니다. 개발에서 기본값을 넣지 않습니다.')

    def _certificate_policy_actor(self):
        if not self.env.su and not self.env.user.has_group('iatf_incoming_inspection.group_incoming_inspection_manager'):
            raise AccessError(_('성적서·보관기간 관리 기준은 수입검사 책임자가 변경합니다.'))
    @api.model_create_multi
    def create(self,vals_list):
        if any(key in vals or 'default_'+key in self.env.context for vals in vals_list for key in _POLICY):
            self._certificate_policy_actor()
        return super().create(vals_list)
    def write(self,values):
        if _POLICY & values.keys():self._certificate_policy_actor()
        return super().write(values)
    @api.constrains('iqc_shelf_life_days','iqc_shelf_life_required')
    def _check_shelf_life(self):
        for product in self:
            if product.iqc_shelf_life_days<0 or product.iqc_shelf_life_required and product.iqc_shelf_life_days<=0:
                raise ValidationError(_('유효기간 관리 대상은 확정 보관일수가 필요합니다.'))


class IncomingCertificate(models.Model):
    _inherit='iatf.incoming.inspection'
    certificate_plant=fields.Char('성적서 생산 공장')
    certificate_lot_name=fields.Char('성적서 원료 LOT')
    certificate_issue_date=fields.Date('성적서 발행일')
    certificate_manufactured_date=fields.Date('자재 제조일')
    certificate_expiry_date=fields.Date('성적서 유효기한')
    certificate_required=fields.Boolean(related='product_id.iqc_certificate_required')
    shelf_life_required=fields.Boolean(related='product_id.iqc_shelf_life_required')

    def write(self,values):
        if _CERTIFICATE & values.keys():self._iqc_assert_editable()
        return super().write(values)

    def _iqc_validate_certificate(self):
        self.ensure_one()
        if self.quantity_accepted<=0:return
        product=self.product_id
        self._lock_certificate_source(product)
        required=product.iqc_certificate_required or product.iqc_shelf_life_required or bool(self.supplier_cert_no)
        if required:
            if not (self.supplier_cert_no and self.certificate_plant and self.certificate_lot_name and self.certificate_issue_date and self.attachment_ids):
                raise UserError(_('합격 처리에는 성적서 번호·공장·LOT·발행일과 실제 파일을 연결하십시오.'))
            if not self.lot_id or self.certificate_lot_name.strip()!=self.lot_id.name.strip():
                raise UserError(_('성적서 LOT와 실제 입고 장부 LOT가 다릅니다. 재검토 전 합격 재고를 해제할 수 없습니다.'))
            if self.certificate_issue_date>fields.Date.to_date(self.inspection_date):
                raise UserError(_('성적서 발행일이 검사일보다 늦습니다.'))
        if product.iqc_shelf_life_required:
            if not (self.certificate_manufactured_date and self.certificate_expiry_date and product.iqc_shelf_life_days>0):
                raise UserError(_('제조일·성적서 유효기한·확정 보관일수가 필요합니다.'))
            end=self.certificate_manufactured_date+timedelta(days=product.iqc_shelf_life_days)
            if (self.certificate_manufactured_date>fields.Date.to_date(self.inspection_date)
                or self.certificate_expiry_date<self.certificate_manufactured_date
                or min(end,self.certificate_expiry_date)<max(fields.Date.context_today(self),fields.Date.to_date(self.inspection_date))):
                raise UserError(_('자재 유효기간을 벗어났습니다. 불합격·반품 또는 별도 품질 검토로 처리하십시오.'))

    def _lock_certificate_source(self,product):
        # Product is already readable by the inspection user. Lock only its
        # current template so a concurrent policy change cannot race release.
        product.product_tmpl_id.flush_recordset()
        self.env.cr.execute('SELECT id FROM product_template WHERE id=%s FOR UPDATE',[product.product_tmpl_id.id])

    def _iqc_validate_evidence(self):
        result=super()._iqc_validate_evidence()
        self._iqc_validate_certificate()
        return result

    def _iqc_evidence_snapshot(self):
        result=super()._iqc_evidence_snapshot()
        values={key:fields.Date.to_string(self[key]) if self._fields[key].type=='date' else self[key] for key in sorted(_CERTIFICATE)}
        policy={key:self.product_id[key] for key in sorted(_POLICY)}
        # Empty optional additions must not invalidate historical approvals.
        if any(values.values()) or any(policy.values()):result['supplier_certificate']={'values':values,'policy':policy}
        return result
