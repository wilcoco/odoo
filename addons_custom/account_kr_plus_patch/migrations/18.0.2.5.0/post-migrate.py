"""저널명이 붙은 '○○ 당좌예금' 계정과목을 공용 '당좌예금' 하나로 합칩니다.

계좌 설정에서 은행저널을 만들면 예전 버전은 저널명을 앞에 붙인 계정과목
(예: 'MMT 당좌예금')을 저널마다 새로 만들었습니다. 이제는 회사마다 '당좌예금'
계정과목 하나를 공유하고, 실제 은행계좌 구분은 전표 라인의 '연결 은행계좌'
(account.move.line.kr_bank_journal_id)로 합니다.

이 스크립트는 기존 데이터를 그 구조로 옮깁니다.
  1. 회사별로 대표 계정 하나를 고르고 이름을 '당좌예금'으로 바꿉니다.
  2. 합쳐질 계정을 쓰던 전표 라인에 '연결 은행계좌'를 채워 넣습니다.
  3. 합쳐질 계정을 참조하는 모든 외래키를 대표 계정으로 옮깁니다.
  4. 참조가 사라진 계정을 삭제합니다.

병합 대상에서 빠지는 계정:
  - 외화 저널·외화 계정 (계정에 통화가 고정됨)
  - 회사의 은행계좌 코드 대역(bank_account_code_prefix) 밖의 계정.
    MMT·MMF처럼 예금이 아닌 계좌를 단기투자자산 코드로 바꿔둔 경우가 여기 해당합니다.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

SHARED_NAME = "당좌예금"

# 대표 계정으로 옮기지 않고 삭제할 테이블(다대다 관계, 회사별 코드 등).
# 대표 계정은 이미 자기 행을 갖고 있어 옮기면 중복이거나 의미가 달라집니다.
DROP_TABLES = {
    "account_code_mapping",
    "account_account_res_company_rel",
}


def _should_drop(table, column):
    return (
        table in DROP_TABLES
        or table.endswith("_rel")
        or column == "account_account_id"
    )


def _candidates(cr):
    """{company_id: {account_id: [journal_id, ...]}} — 병합 후보를 모읍니다."""
    cr.execute(
        """
        SELECT rel.res_company_id, a.id, j.id
          FROM account_account a
          JOIN account_account_res_company_rel rel
            ON rel.account_account_id = a.id
     LEFT JOIN account_journal j
            ON j.default_account_id = a.id
           AND j.type = 'bank'
           AND j.company_id = rel.res_company_id
           AND j.currency_id IS NULL
         WHERE a.account_type = 'asset_cash'
           AND a.currency_id IS NULL
           AND a.name::text LIKE %s
      ORDER BY rel.res_company_id, a.code_store::text, a.id
        """,
        ("%" + SHARED_NAME + "%",),
    )
    grouped = {}
    for company_id, account_id, journal_id in cr.fetchall():
        journals = grouped.setdefault(company_id, {}).setdefault(account_id, [])
        if journal_id:
            journals.append(journal_id)
    return grouped


def _filter_by_bank_code_prefix(env, company_id, accounts):
    """은행계좌 코드 대역(bank_account_code_prefix) 밖의 계정은 제외합니다.

    MMT·MMF처럼 예금이 아닌 계좌를 은행저널로 만들어 두고 계정과목 코드를
    단기투자자산 대역(예: 1112xx)으로 바꿔둔 경우, 이름에 '당좌예금'이 남아
    있어도 공용 계정에 합치지 않습니다.
    """
    company = env["res.company"].browse(company_id)
    prefix = company.bank_account_code_prefix
    if not prefix:
        return accounts

    kept = {}
    for account_id, journals in accounts.items():
        account = env["account.account"].browse(account_id)
        code = account.with_company(company).code or ""
        if code.startswith(prefix):
            kept[account_id] = journals
        else:
            _logger.info(
                "회사 %s: 계정과목 '%s'(코드 %s)은 은행계좌 코드 대역 '%s' 밖이라 "
                "병합하지 않습니다.",
                company_id,
                account.name,
                code,
                prefix,
            )
    return kept


def _has_foreign_currency_journal(cr, account_ids):
    """통화가 지정된 저널이 쓰는 계정은 건드리지 않습니다."""
    cr.execute(
        """
        SELECT DISTINCT default_account_id
          FROM account_journal
         WHERE default_account_id = ANY(%s)
           AND currency_id IS NOT NULL
        """,
        (list(account_ids),),
    )
    return {row[0] for row in cr.fetchall()}


def _pick_canonical(env, account_ids):
    """이미 '당좌예금'인 계정을 우선하고, 없으면 첫 계정의 이름을 바꿉니다."""
    accounts = env["account.account"].browse(account_ids)
    exact = accounts.filtered(
        lambda item: (item.name or "").strip() == SHARED_NAME
    )
    canonical = exact[:1] or accounts[:1]
    if (canonical.name or "").strip() != SHARED_NAME:
        _logger.info(
            "계정과목 '%s'(id=%s) 이름을 '%s'(으)로 변경합니다.",
            canonical.name,
            canonical.id,
            SHARED_NAME,
        )
        canonical.name = SHARED_NAME
    return canonical


def _fill_bank_journal_on_lines(cr, account_id, journal_ids):
    """대표 계정으로 옮기기 전에 '연결 은행계좌'를 채워 놓습니다."""
    if len(journal_ids) != 1:
        # 이미 여러 저널이 공유하던 계정은 어느 은행인지 단정할 수 없다.
        return []
    cr.execute(
        """
        UPDATE account_move_line
           SET kr_bank_journal_id = %s
         WHERE account_id = %s
           AND kr_bank_journal_id IS NULL
     RETURNING move_id
        """,
        (journal_ids[0], account_id),
    )
    return [row[0] for row in cr.fetchall()]


def _referencing_columns(cr):
    """account_account.id 를 가리키는 단일 컬럼 외래키를 모두 찾습니다."""
    cr.execute(
        """
        SELECT c.conrelid::regclass::text, a.attname
          FROM pg_constraint c
          JOIN pg_attribute a
            ON a.attrelid = c.conrelid
           AND a.attnum = c.conkey[1]
         WHERE c.contype = 'f'
           AND c.confrelid = 'account_account'::regclass
           AND array_length(c.conkey, 1) = 1
        """
    )
    return [row for row in cr.fetchall() if row[0] != "account_account"]


def _move_references(cr, columns, canonical_id, account_id):
    for table, column in columns:
        if _should_drop(table, column):
            cr.execute(
                f'DELETE FROM "{table}" WHERE "{column}" = %s', (account_id,)
            )
            continue
        cr.execute("SAVEPOINT kr_merge_ref")
        try:
            cr.execute(
                f'UPDATE "{table}" SET "{column}" = %s WHERE "{column}" = %s',
                (canonical_id, account_id),
            )
        except Exception:  # noqa: BLE001 - 유니크 제약 충돌은 행 삭제로 처리
            cr.execute("ROLLBACK TO SAVEPOINT kr_merge_ref")
            _logger.warning(
                "%s.%s 는 대표 계정으로 옮길 수 없어 계정 %s 참조 행을 삭제합니다.",
                table,
                column,
                account_id,
            )
            cr.execute(
                f'DELETE FROM "{table}" WHERE "{column}" = %s', (account_id,)
            )
        else:
            cr.execute("RELEASE SAVEPOINT kr_merge_ref")


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    grouped = _candidates(cr)
    if not grouped:
        return

    columns = _referencing_columns(cr)
    touched_move_ids = set()
    removed_ids = []

    for company_id, accounts in grouped.items():
        foreign = _has_foreign_currency_journal(cr, list(accounts))
        accounts = {
            account_id: journals
            for account_id, journals in accounts.items()
            if account_id not in foreign
        }
        accounts = _filter_by_bank_code_prefix(env, company_id, accounts)
        if not accounts:
            continue

        canonical = _pick_canonical(env, list(accounts))
        for account_id, journal_ids in accounts.items():
            if account_id == canonical.id:
                continue
            touched_move_ids.update(
                _fill_bank_journal_on_lines(cr, account_id, journal_ids)
            )
            _move_references(cr, columns, canonical.id, account_id)
            cr.execute(
                "DELETE FROM ir_model_data "
                " WHERE model = 'account.account' AND res_id = %s",
                (account_id,),
            )
            cr.execute(
                "DELETE FROM account_account WHERE id = %s", (account_id,)
            )
            removed_ids.append(account_id)
            _logger.info(
                "회사 %s: 계정과목 %s 를 '%s'(id=%s)에 병합했습니다.",
                company_id,
                account_id,
                SHARED_NAME,
                canonical.id,
            )

    env.invalidate_all()
    if not removed_ids:
        return

    moves = env["account.move"].browse(sorted(touched_move_ids)).exists()
    if moves:
        moves._compute_kr_bank_journal_ids()
        moves.flush_recordset()
    _logger.info("당좌예금 계정과목 %s 개를 병합했습니다.", len(removed_ids))
