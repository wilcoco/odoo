from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

from ..tools.approval_number import approval_number_key, normalize_approval_number

STUDIO_FIELD = "x_escon_tax_approval_no"
INVOICE_TYPES = ("in_invoice", "in_refund", "out_invoice", "out_refund")
PURCHASE_TYPES = ("in_invoice", "in_refund")
TAX_DOCUMENT_TYPES = ("tax_invoice", "invoice")
REFERENCE_SPECS = (
    ("ir.ui.view", ("arch_db",), "화면"),
    ("ir.actions.server", ("code", "update_path"), "서버 자동화"),
    ("ir.filters", ("domain", "context"), "사용자 필터"),
    ("ir.rule", ("domain_force",), "레코드 규칙"),
    ("ir.actions.act_window", ("domain", "context"), "창 동작"),
    ("ir.model.fields", ("depends", "domain"), "다른 사용자 정의 필드"),
)


class KrApprovalNumberMerge(models.TransientModel):
    """승인번호 정본 이관과 Studio 호환 필드의 안전한 폐기를 관리한다."""

    _name = "kr.approval.number.merge"
    _description = "세금계산서 승인번호 필드 통합"

    source = fields.Selection(
        [("studio", "세금계산서승인번호 (스튜디오 필드)"),
         ("ref", "업체 청구서 참조 (ref) — 승인번호 형식인 것만"),
         ("both", "둘 다 (값이 다르면 적용 제외)")],
        string="가져올 곳", required=True, default="both")
    apply_now = fields.Boolean(
        string="실제로 적용", default=False,
        help="끄면 미리보기만 합니다. 결과를 확인한 뒤 켜고 다시 실행하세요.")
    studio_field_present = fields.Boolean(string="Studio 호환 필드 존재", readonly=True)
    studio_data_ready = fields.Boolean(string="Studio 데이터 이관 완료", readonly=True)
    studio_reference_count = fields.Integer(string="남은 내부 참조", readonly=True)
    studio_retirement_ready = fields.Boolean(string="Studio 필드 제거 가능", readonly=True)
    confirm_studio_removal = fields.Boolean(
        string="백업 및 외부 연동 확인 완료",
        help="DB 백업과 외부 API·ETL·BI 연동의 x 필드 미사용을 확인한 경우에만 선택하세요.")
    result = fields.Text(string="결과", readonly=True)

    @api.model
    def _has_studio_field(self):
        return STUDIO_FIELD in self.env["account.move"]._fields

    @api.model
    def _studio_reference_status(self):
        """Odoo DB 안에서 Studio 필드를 문자열로 참조하는 구성을 점검한다."""
        details = []
        for model_name, field_names, label in REFERENCE_SPECS:
            model = self.env.get(model_name)
            if model is None:
                continue
            record_ids = set()
            for field_name in field_names:
                if field_name not in model._fields:
                    continue
                record_ids.update(model.sudo().with_context(active_test=False).search([
                    (field_name, "ilike", STUDIO_FIELD),
                ]).ids)
            if record_ids:
                details.append((label, len(record_ids)))
        return {
            "count": sum(count for _label, count in details),
            "details": details,
        }

    @api.model
    def _studio_retirement_status(self):
        """모든 회사의 값 이관과 내부 참조 제거가 끝났는지 반환한다."""
        status = {
            "present": self._has_studio_field(),
            "data_ready": False,
            "ready": False,
            "values": 0,
            "invalid": 0,
            "missing": 0,
            "mismatch": 0,
            "duplicates": 0,
            "non_invoice": 0,
            "references": 0,
            "reference_details": [],
        }
        if not status["present"]:
            return status

        moves = self.env["account.move"].sudo().search([
            (STUDIO_FIELD, "!=", False),
        ])
        status["values"] = len(moves)
        for move in moves:
            studio_value = normalize_approval_number(move[STUDIO_FIELD])
            canonical_value = normalize_approval_number(move.kr_approval_number)
            if move.move_type not in INVOICE_TYPES:
                status["non_invoice"] += 1
            if not studio_value:
                status["invalid"] += 1
            elif not canonical_value:
                status["missing"] += 1
            elif studio_value != canonical_value:
                status["mismatch"] += 1
        canonical_owners = defaultdict(list)
        for move in self.env["account.move"].sudo().search([
            ("kr_approval_number", "!=", False),
        ]):
            canonical_owners[approval_number_key(
                move.kr_approval_number
            )].append(move.id)
        status["duplicates"] = sum(
            len(move_ids) for move_ids in canonical_owners.values()
            if len(move_ids) > 1
        )
        status["data_ready"] = not any(
            status[key]
            for key in ("invalid", "missing", "mismatch", "duplicates")
        )
        references = self._studio_reference_status()
        status["references"] = references["count"]
        status["reference_details"] = references["details"]
        status["ready"] = status["data_ready"] and not status["references"]
        return status

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        return self._with_studio_status(values, fields_list=fields_list)

    def _with_studio_status(self, values, fields_list=None):
        status = self._studio_retirement_status()
        mapping = {
            "studio_field_present": status["present"],
            "studio_data_ready": status["data_ready"],
            "studio_reference_count": status["references"],
            "studio_retirement_ready": status["ready"],
        }
        for field_name, value in mapping.items():
            if fields_list is None or field_name in fields_list:
                values[field_name] = value
        return values

    def _source_values(self, move):
        studio_raw = ""
        studio_value = False
        if self.source in ("studio", "both") and self._has_studio_field():
            studio_raw = str(move[STUDIO_FIELD] or "").strip()
            studio_value = normalize_approval_number(studio_raw)

        ref_raw = ""
        ref_value = False
        if (
            self.source in ("ref", "both")
            and move.move_type in PURCHASE_TYPES
            and move.kr_doc_type in TAX_DOCUMENT_TYPES
        ):
            ref_raw = str(move.ref or "").strip()
            ref_value = normalize_approval_number(ref_raw)
        return studio_raw, studio_value, ref_raw, ref_value

    def action_run(self):
        self.ensure_one()
        Move = self.env["account.move"]
        moves = Move.search([("move_type", "in", INVOICE_TYPES)])
        taken = {}
        existing_owners = defaultdict(list)
        for move in Move.sudo().search([("kr_approval_number", "!=", False)]):
            key = approval_number_key(move.kr_approval_number)
            taken.setdefault(key, move.id)
            existing_owners[key].append(move)

        proposals = []
        accessible_ids = set(moves.ids)
        conflicts = []
        hidden_duplicate_groups = 0
        for value, owners in existing_owners.items():
            if len(owners) <= 1:
                continue
            if all(move.id in accessible_ids for move in owners):
                conflicts.append(_(
                    "기존 정본 중복 %(value)s: 전표 %(moves)s"
                ) % {
                    "value": value,
                    "moves": ", ".join(
                        str(move.name or move.id) for move in owners),
                })
            else:
                hidden_duplicate_groups += 1
        if hidden_duplicate_groups:
            conflicts.append(_(
                "접근 제한 회사에 걸친 기존 정본 논리 중복 %(count)d그룹 — "
                "전사 권한으로 별도 확인 필요"
            ) % {"count": hidden_duplicate_groups})
        already_aligned = skipped_filled = no_source = 0
        invalid_studio = invalid_ref = 0
        for move in moves:
            studio_raw, studio_value, ref_raw, ref_value = self._source_values(move)
            if studio_raw and not studio_value:
                invalid_studio += 1
            if ref_raw and not ref_value:
                invalid_ref += 1
            if studio_value and ref_value and studio_value != ref_value:
                conflicts.append(_(
                    "%(name)s: Studio(%(studio)s)와 ref(%(ref)s)의 승인번호가 다름"
                ) % {"name": move.name or move.id,
                     "studio": studio_value, "ref": ref_value})
                continue
            value = studio_value or ref_value
            if not value:
                no_source += 1
                continue
            if move.kr_approval_number:
                if approval_number_key(move.kr_approval_number) == value:
                    already_aligned += 1
                else:
                    skipped_filled += 1
                continue
            proposals.append((move, value))

        grouped = defaultdict(list)
        for move, value in proposals:
            grouped[value].append(move)
        to_write = []
        for value, candidate_moves in grouped.items():
            if len(candidate_moves) > 1:
                conflicts.append(_(
                    "%(val)s: 여러 전표에서 동시에 가져오려 함 (%(names)s)"
                ) % {"val": value,
                     "names": ", ".join(str(move.name or move.id)
                                          for move in candidate_moves)})
                continue
            move = candidate_moves[0]
            owner = taken.get(value)
            if owner and owner != move.id:
                if owner in accessible_ids:
                    conflicts.append(_(
                        "%(name)s: %(val)s은(는) 다른 전표(id %(owner)s)가 이미 사용"
                    ) % {"name": move.name or move.id,
                         "val": value, "owner": owner})
                else:
                    conflicts.append(_(
                        "%(name)s: %(val)s은(는) 접근 제한 회사의 전표가 이미 사용"
                    ) % {"name": move.name or move.id, "val": value})
                continue
            to_write.append((move, value))

        status = self._studio_retirement_status()
        self.write(self._with_studio_status({}))
        lines = [
            _("대상 전표 %d건 검사") % len(moves),
            _("Studio 호환 필드 존재: %s") % (
                _("예") if status["present"] else _("아니오 — 제거할 필드 없음")),
            "",
            _("옮길 수 있는 건수: %d") % len(to_write),
            _("이미 정본과 일치: %d") % already_aligned,
            _("정본에 다른 값이 있어 건너뜀: %d") % skipped_filled,
            _("승인번호 형식이 아니어서 제외된 Studio 값: %d") % invalid_studio,
            _("승인번호 형식이 아니어서 제외된 ref: %d") % invalid_ref,
            _("가져올 값이 없음: %d") % no_source,
            _("충돌(중복 또는 원천 불일치): %d") % len(conflicts),
        ]
        if conflicts:
            lines.append("\n" + _("[충돌 목록 — 수동 확인 필요]"))
            lines += conflicts[:30]
            if len(conflicts) > 30:
                lines.append(_("...외 %d건") % (len(conflicts) - 30))

        if not self.apply_now:
            lines.insert(0, _(
                "※ 미리보기입니다. 실제 반영하려면 '실제로 적용'을 켜고 "
                "다시 실행하세요.\n"))
            lines.extend(self._studio_status_lines(status))
            self.result = "\n".join(lines)
            return self._reopen()

        done = 0
        failures = []
        for move, value in to_write:
            try:
                with self.env.cr.savepoint():
                    move.with_context(
                        skip_kr_legacy_ref_sync=True,
                        skip_is_manually_modified=True,
                    ).write({"kr_approval_number": value})
                done += 1
            except Exception as error:  # noqa: BLE001 - 한 건 오류가 전체 이관을 막지 않게
                failures.append(_("%s: 반영 실패 — %s") % (
                    move.name or move.id, str(error)[:100]))
        status = self._studio_retirement_status()
        self.write(self._with_studio_status({}))
        lines.append("\n" + _("→ 실제 반영 %d건 완료") % done)
        if failures:
            lines.append(_("→ 반영 실패 %d건") % len(failures))
            lines += failures[:30]
        lines.extend(self._studio_status_lines(status))
        self.result = "\n".join(lines)
        return self._reopen()

    def action_remove_studio_field(self):
        """검증을 모두 통과한 수동 Studio 필드만 명시적으로 제거한다."""
        self.ensure_one()
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(_("시스템 관리자만 Studio 호환 필드를 제거할 수 있습니다."))
        if not self.confirm_studio_removal:
            raise UserError(_("백업 및 외부 연동 확인 완료를 먼저 선택하세요."))
        status = self._studio_retirement_status()
        if not status["present"]:
            raise UserError(_("제거할 Studio 호환 필드가 없습니다."))
        if not status["ready"]:
            raise UserError(_(
                "데이터 이관 또는 내부 참조 제거가 완료되지 않아 필드를 제거할 수 없습니다."
            ))
        studio_field = self.env["ir.model.fields"].sudo().search([
            ("model", "=", "account.move"),
            ("name", "=", STUDIO_FIELD),
        ], limit=1)
        if not studio_field or studio_field.state != "manual":
            raise UserError(_(
                "이 필드는 Studio 수동 필드가 아니므로 모듈에서 제거할 수 없습니다."
            ))
        studio_field.unlink()
        return {"type": "ir.actions.client", "tag": "reload"}

    @staticmethod
    def _studio_status_lines(status):
        if not status["present"]:
            return [_("※ Studio 호환 필드가 없어 별도 제거 작업이 필요하지 않습니다.")]
        lines = [_(
            "※ Studio 값 %(count)d건: 형식 오류 %(invalid)d건, 정본 누락 "
            "%(missing)d건, 값 불일치 %(mismatch)d건, 정본 논리 중복 "
            "%(duplicates)d건, 비청구 전표 %(other)d건"
        ) % {"count": status["values"], "invalid": status["invalid"],
             "missing": status["missing"], "mismatch": status["mismatch"],
             "duplicates": status["duplicates"],
             "other": status["non_invoice"]}]
        if status["reference_details"]:
            lines.append(_("※ 남은 Odoo 내부 참조: %s") % ", ".join(
                "%s %d건" % item for item in status["reference_details"]))
        if status["ready"]:
            lines.append(_(
                "※ 전사 데이터와 Odoo 내부 참조 점검을 통과했습니다. DB 백업과 "
                "외부 연동 확인 후 시스템 관리자가 필드를 제거할 수 있습니다."))
        else:
            lines.append(_(
                "※ Studio 필드 제거 보류: 위 데이터 오류와 내부 참조를 먼저 해결하세요."))
        return lines

    def _reopen(self):
        return {"type": "ir.actions.act_window", "res_model": self._name,
                "res_id": self.id, "view_mode": "form",
                "views": [[False, "form"]], "target": "new"}
