"""금형 마스터 단일화(iatf.mold → injection.mold) 사전 점검.

18.0.2.0.0 부터 iatf_mold 는 별도 모델 `iatf.mold` 를 만들지 않고 `injection.mold` 를
확장한다. 점검·온도·시사출·보전·MO 의 `mold_id` 는 `injection_mold` 를 가리키게 된다.

2026-10-19 기준 운영(odoo18)·WSL(esconodoo202609)·시험 DB 모두 `iatf_mold` 0건이라
옮길 데이터가 없다. 그래서 이 스크립트는 **자동 대응(코드 매칭 등)을 하지 않는다.**
데이터가 있는 DB 에서 조용히 넘어가면 하위 기록의 금형 id 가 엉뚱한 사출 금형을
가리키게 되므로, 그 경우에는 업그레이드를 멈추고 수동 이관을 요구한다.

데이터가 없으면 `iatf_mold` 를 가리키던 외래키만 지운다. 새 외래키(injection_mold)는
모듈 로드 때 ORM 이 다시 만든다. 남은 `iatf_mold` 테이블·모델 정의는 Odoo 가 모듈
갱신 마지막 단계에서 정리한다.
"""
import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, name):
    cr.execute("SELECT to_regclass(%s)", [name])
    return cr.fetchone()[0] is not None


def migrate(cr, version):
    if not version or not _table_exists(cr, "iatf_mold"):
        return

    cr.execute("SELECT count(*) FROM iatf_mold")
    molds = cr.fetchone()[0]
    if molds:
        raise Exception(
            "iatf_mold 18.0.2.0.0: 기존 IATF 금형 대장(iatf_mold)에 %s건이 있습니다. "
            "금형 마스터는 injection.mold 로 단일화되므로, 각 IATF 금형을 대응하는 사출 금형"
            "(injection_mold, 금형 코드 기준)에 수동으로 이관한 뒤 다시 업그레이드하세요. "
            "자동 매칭은 하지 않습니다(잘못된 금형에 점검·시사출 증빙이 붙는 것을 막기 위해)."
            % molds
        )

    # 결재·메시지·첨부가 iatf.mold 를 가리키면 대상 레코드가 없는 기록이 된다(0건이 정상).
    for table, column in (("iatf_approval_request", "res_model"),
                          ("mail_message", "model"),
                          ("ir_attachment", "res_model")):
        if _table_exists(cr, table):
            cr.execute("SELECT count(*) FROM %s WHERE %s = 'iatf.mold'" % (table, column))
            count = cr.fetchone()[0]
            if count:
                _logger.warning("iatf_mold 단일화: %s.%s = 'iatf.mold' 인 행 %s건 — 대상 없는 기록입니다.",
                                table, column, count)

    cr.execute("""
        SELECT con.conrelid::regclass::text, con.conname
          FROM pg_constraint con
         WHERE con.contype = 'f' AND con.confrelid = 'iatf_mold'::regclass
    """)
    for table, constraint in cr.fetchall():
        cr.execute('ALTER TABLE %s DROP CONSTRAINT IF EXISTS "%s"' % (table, constraint))
        _logger.info("iatf_mold 단일화: %s 의 외래키 %s 를 제거했습니다(injection_mold 로 재생성).",
                     table, constraint)
