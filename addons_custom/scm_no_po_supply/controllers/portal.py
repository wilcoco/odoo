import uuid
from urllib.parse import urlencode

from odoo import http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request
from odoo.addons.supplier_portal_purchase.controllers.portal import SupplierPortalController


class NoPoPortal(http.Controller):
    """Explicit company/partner search, then narrow elevated create only.

    Existing token/login authentication and company grants remain authoritative.
    Portal visitors never receive generic ORM ACLs on notices or agreements.
    """

    @http.route('/supplier/no-po', type='http', auth='public', website=True, methods=['GET'])
    def notices(self, token=None, **kwargs):
        try:
            partner = SupplierPortalController()._validate_portal_access(token)
        except AccessDenied as exc:
            return request.render('supplier_portal_purchase.portal_access_denied', {'error': str(exc)})
        notices = request.env['scm.no.po.notice'].sudo().search([
            ('company_id', '=', request.env.company.id), ('partner_id', '=', partner.id),
            ('state', '=', 'issued'), ('agreement_id.active', '=', True)], order='need_date, id', limit=200)
        return request.render('scm_no_po_supply.portal_notices', {
            'partner': partner, 'token': token, 'notices': notices,
            'request_keys': {notice.id: str(uuid.uuid4()) for notice in notices},
            'page_name': 'no_po', 'query': urlencode({'token': token}) if token else '',
        })

    @http.route('/supplier/no-po/asn', type='http', auth='public', website=True,
                methods=['POST'], csrf=True)
    def create_asn(self, token=None, **post):
        try:
            partner = SupplierPortalController()._validate_portal_access(token)
            notice_id = int(post.get('notice_id', ''))
            notice = request.env['scm.no.po.notice'].sudo().search([
                ('id', '=', notice_id), ('partner_id', '=', partner.id),
                ('company_id', '=', request.env.company.id)], limit=1)
            if not notice:
                raise AccessDenied('접근할 수 없는 요구통보입니다.')
            # Any validation failure rolls back partial ORM changes before rendering.
            with request.env.cr.savepoint():
                asn = notice._supplier_create_asn(float(post.get('quantity', '')),
                    post.get('expected_date'), (post.get('lot_name') or '').strip(),
                    post.get('request_key', ''))
        except (AccessDenied, AccessError, UserError, ValidationError, ValueError, TypeError) as exc:
            return request.render('supplier_portal_purchase.portal_access_denied', {'error': str(exc)})
        query = urlencode({'token': token}) if token else ''
        return request.redirect('/supplier/asn/%s/pass?%s' % (asn.id, query))
