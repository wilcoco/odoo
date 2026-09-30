from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from dateutil.relativedelta import relativedelta
from markupsafe import escape


_WORKFLOW_CONTEXT = '_iatf_document_workflow'
_WORKFLOW_TOKEN = object()


class IatfDocument(models.Model):
    _name = "iatf.document"
    _description = "Controlled Document (IATF 16949 §7.5)"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "doc_number"

    # ── Identification ──
    doc_number = fields.Char(
        string="문서 번호", required=True, copy=False, readonly=True,
        default=lambda self: _("New"),
    )
    name = fields.Char(string="제목", required=True, tracking=True)
    category_id = fields.Many2one(
        "iatf.document.category", string="카테고리", required=True, tracking=True,
    )
    doc_type = fields.Selection(
        [
            ("manual", "품질 매뉴얼"),
            ("procedure", "절차서"),
            ("instruction", "작업 지침서"),
            ("form", "양식"),
            ("specification", "규격서"),
            ("standard", "외부 표준"),
            ("record", "품질 기록"),
            ("other", "기타"),
        ],
        string="문서 유형", required=True, default="procedure", tracking=True,
    )
    description = fields.Html(string="설명 / 범위")

    # ── Ownership ──
    owner_id = fields.Many2one(
        "res.users", string="문서 소유자", default=lambda self: self.env.user,
        tracking=True,
    )
    department_id = fields.Many2one("hr.department", string="부서")
    company_id = fields.Many2one(
        "res.company", string="회사", default=lambda self: self.env.company,
    )

    # ── Revision control ──
    current_revision = fields.Char(string="현재 개정", default="00", tracking=True)
    revision_date = fields.Date(string="개정일", tracking=True)
    revision_ids = fields.One2many("iatf.document.revision", "document_id", string="개정 이력")
    revision_count = fields.Integer(compute="_compute_revision_count")

    # ── Approval workflow ──
    state = fields.Selection(
        [
            ("draft", "초안"),
            ("review", "검토 중"),
            ("approved", "승인됨"),
            ("obsolete", "폐기"),
        ],
        string="상태", default="draft", required=True, tracking=True,
    )
    reviewer_id = fields.Many2one("res.users", string="검토자", tracking=True)
    approver_id = fields.Many2one("res.users", string="승인자", tracking=True)
    review_date = fields.Date(string="검토일", readonly=True, copy=False)
    approval_date = fields.Date(string="승인일", readonly=True, copy=False)
    next_review_date = fields.Date(
        string="다음 검토일",
        help="Periodic review date as required by IATF 16949 §7.5.3.1",
        tracking=True,
    )

    # ── Retention ──
    retention_years = fields.Integer(
        string="보존 기간 (년)",
        help="How long to retain this document after obsolescence. "
             "Defaults from category if not set.",
    )
    retention_expiry = fields.Date(
        string="보존 만료일", compute="_compute_retention_expiry", store=True,
    )

    # ── Distribution ──
    distribution_ids = fields.One2many(
        "iatf.document.distribution", "document_id", string="배포 목록",
    )

    # ── Attachments ──
    attachment_ids = fields.Many2many(
        "ir.attachment", string="첨부파일",
        help="Attach the controlled document files here.",
    )
    attachment_count = fields.Integer(compute="_compute_attachment_count")

    # ── External reference ──
    external_origin = fields.Char(
        string="외부 출처",
        help="For external documents: origin standard/organization (e.g. ISO, AIAG, customer)",
    )

    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("doc_number_uniq", "unique(doc_number, company_id)", "Document number must be unique per company."),
    ]

    # ── Computes ──

    @api.depends("revision_ids")
    def _compute_revision_count(self):
        for doc in self:
            doc.revision_count = len(doc.revision_ids)

    @api.depends("attachment_ids")
    def _compute_attachment_count(self):
        for doc in self:
            doc.attachment_count = len(doc.attachment_ids)

    @api.depends("approval_date", "retention_years", "category_id.retention_years")
    def _compute_retention_expiry(self):
        for doc in self:
            years = doc.retention_years or (doc.category_id.retention_years if doc.category_id else 0)
            if doc.approval_date and years:
                doc.retention_expiry = doc.approval_date + relativedelta(years=years)
            else:
                doc.retention_expiry = False

    # ── CRUD ──

    @api.model_create_multi
    def create(self, vals_list):
        defaults = self.default_get(['state', 'review_date', 'approval_date'])
        for vals in vals_list:
            effective = dict(defaults, **vals)
            if (effective.get('state', 'draft') != 'draft'
                    or effective.get('approval_date') or effective.get('review_date')):
                raise UserError(_('새 문서는 초안으로 작성한 뒤 검토와 승인을 진행하십시오.'))
            if vals.get("doc_number", _("New")) == _("New"):
                vals["doc_number"] = self.env["ir.sequence"].next_by_code("iatf.document") or _("New")
        return super().create(vals_list)

    def write(self, vals):
        workflow = self.env.context.get(_WORKFLOW_CONTEXT) is _WORKFLOW_TOKEN
        self._lock_document()
        content = {'name', 'description', 'doc_number', 'doc_type', 'category_id', 'owner_id',
                   'department_id', 'company_id', 'current_revision', 'revision_date',
                   'attachment_ids', 'external_origin', 'retention_years'}
        if not workflow and content & vals.keys() and any(doc.state != 'draft' for doc in self):
            raise UserError(_('검토·승인한 문서 내용은 회수 또는 새 개정으로 변경하십시오.'))
        if not workflow and {'state', 'review_date', 'approval_date'} & vals.keys():
            raise UserError(_('문서 상태와 승인일은 검토·승인·회수 메뉴로만 변경할 수 있습니다.'))
        if not workflow and {'reviewer_id', 'approver_id', 'company_id'} & vals.keys():
            if any(doc.state != 'draft' for doc in self):
                raise UserError(_('검토자·승인자·회사는 문서를 초안으로 회수한 뒤 변경하십시오.'))
        return super().write(vals)

    def _lock_document(self):
        self.check_access('write')
        if self.ids:
            self.flush_recordset()
            self.env.cr.execute('SELECT id FROM iatf_document WHERE id IN %s ORDER BY id FOR UPDATE',
                                [tuple(self.ids)])
            self.invalidate_recordset()
        if any(doc.company_id and doc.company_id not in self.env.companies for doc in self):
            raise AccessError(_('허용된 회사의 문서만 처리할 수 있습니다.'))

    def copy(self, default=None):
        default = dict(default or {})
        default.update(state='draft', review_date=False, approval_date=False)
        return super().copy(default)

    def unlink(self):
        self._lock_document()
        if any(doc.state in ('approved', 'obsolete') or doc.revision_ids for doc in self):
            raise UserError(_('승인 문서와 개정 이력은 삭제하지 말고 폐기 상태로 보존하십시오.'))
        return super().unlink()

    def _workflow_write(self, vals):
        self.check_access('write')
        return self.with_context(**{_WORKFLOW_CONTEXT: _WORKFLOW_TOKEN}).write(vals)

    def _check_approval_actor(self):
        self.check_access('write')
        if self.ids:
            self.flush_recordset(['state', 'approver_id', 'company_id'])
            self.env.cr.execute(
                'SELECT id FROM iatf_document WHERE id IN %s ORDER BY id FOR UPDATE',
                [tuple(self.ids)])
            self.invalidate_recordset(['state', 'approver_id', 'company_id'])
        for doc in self:
            if doc.company_id and doc.company_id not in self.env.companies:
                raise AccessError(_('현재 허용된 회사의 문서만 승인할 수 있습니다.'))
            if doc.state != 'review':
                raise UserError(_('검토 중인 문서만 승인할 수 있습니다.'))
            if not doc.approver_id:
                raise UserError(_('문서 승인자를 지정하십시오.'))
            if (doc.approver_id != self.env.user
                    or not self.env.user.has_group('iatf_document_control.group_document_manager')):
                raise AccessError(_('지정된 문서 승인자이면서 문서관리 책임자 권한이 있어야 승인할 수 있습니다.'))
            if (not doc.approver_id.active or doc.approver_id.share
                    or (doc.company_id and doc.company_id not in doc.approver_id.company_ids)):
                raise AccessError(_('승인자의 활성 상태와 소속 회사를 확인하십시오.'))

    # ── Workflow actions ──

    def action_submit_review(self):
        for doc in self:
            if doc.state != 'draft':
                raise UserError(_('초안 문서만 검토를 요청할 수 있습니다.'))
            if not doc.reviewer_id:
                raise UserError(_("Please assign a Reviewer before submitting for review."))
            doc._workflow_write({"state": "review", "review_date": fields.Date.today()})

    def action_approve(self):
        self._check_approval_actor()
        for doc in self:
            doc._workflow_write({
                "state": "approved",
                "approval_date": fields.Date.today(),
            })
            if not doc.next_review_date:
                doc.next_review_date = fields.Date.today() + relativedelta(years=1)

    def action_obsolete(self):
        self._lock_document()
        if not self.env.user.has_group('iatf_document_control.group_document_manager'):
            raise AccessError(_('문서관리 책임자만 승인 문서를 폐기할 수 있습니다.'))
        self._workflow_write({"state": "obsolete"})

    def action_reset_draft(self):
        self._lock_document()
        if any(doc.state in ('approved', 'obsolete') for doc in self):
            raise UserError(_('승인 문서는 새 개정을 만들어 이전 승인 내용을 보존하십시오.'))
        self._workflow_write({"state": "draft", "review_date": False, "approval_date": False})

    def action_new_revision(self):
        self.ensure_one()
        self._lock_document()
        if not self.env.user.has_group('iatf_document_control.group_document_manager'):
            raise AccessError(_('문서관리 책임자만 새 개정을 시작할 수 있습니다.'))
        if self.state != "approved":
            raise UserError(_("Only approved documents can be revised."))
        # Create revision record for current version
        revision = self.env["iatf.document.revision"].with_context(
            **{_WORKFLOW_CONTEXT: _WORKFLOW_TOKEN}).create({
            "document_id": self.id,
            "revision_number": self.current_revision,
            "revision_date": self.revision_date or self.approval_date or fields.Date.today(),
            "reason": _("Superseded by new revision"),
            "revised_by": self.env.user.id,
            "approved_by": self.approver_id.id,
            "change_description": self.description,
            "snapshot_name": self.name,
            "snapshot_approval_date": self.approval_date,
        })
        # Duplicate the binary attachment records so editing a future revision
        # cannot replace the bytes attached to this historical revision.
        copies = self.env['ir.attachment']
        for attachment in self.attachment_ids:
            attachment.check_access('read')
            copies |= attachment.copy({'res_model': 'iatf.document.revision', 'res_id': revision.id})
        revision.with_context(**{_WORKFLOW_CONTEXT: _WORKFLOW_TOKEN}).write(
            {'attachment_ids': [(6, 0, copies.ids)]})
        # Increment revision
        try:
            next_rev = str(int(self.current_revision) + 1).zfill(2)
        except (ValueError, TypeError):
            next_rev = (self.current_revision or '00') + ".1"
        self._workflow_write({
            "current_revision": next_rev,
            "revision_date": fields.Date.today(),
            "state": "draft",
            "review_date": False,
            "approval_date": False,
        })
        self._auto_create_change_request(next_rev)
        return True

    def _auto_create_change_request(self, new_rev):
        """문서 개정 시 변경요청(CR) 자동 생성 (L2-18)"""
        CR = self.env.get("iatf.change.request")
        if CR is None:
            return
        CR.create({
            "title": _("문서 개정: %s (Rev.%s)") % (self.name, new_rev),
            "change_type": "method",
            "change_category": "planned",
            "change_source": "engineering",
            "description": "<p>문서 개정에 의한 자동 변경요청 생성<br/>문서: %s<br/>문서번호: %s<br/>신규 개정: %s</p>" % (
                escape(self.name), escape(self.doc_number), escape(new_rev)),
            "reason": "<p>문서 개정</p>",
            "company_id": self.company_id.id,
        })
        self.message_post(body=_("문서 개정 → 변경요청(CR) 자동 생성됨"))
