import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """점검 항목에 '기준 방식'·'입력 방식' 이 생겼다 — 기존 항목을 제 자리에 놓는다.

    새 필드는 기본값(정성 / 양호·불량)으로 채워진다. 그런데 이미 상·하한을 넣어 둔
    항목까지 '정성' 이 되면, 화면에는 기준이 보이는데 판정에는 안 쓰이는 상태가 된다.
    담당자는 기준이 걸려 있다고 믿고 넘어가므로, 기준이 아예 없는 것보다 나쁘다.

    그리고 개정 차수는 1 부터 시작해야 한다. 0 으로 남으면 첫 실적의 '몇 차 개정본'
    이 0 이 되어, 나중에 개정 이력을 되짚을 때 시작점이 사라진다.
    """
    # 1. 상·하한이 있는 항목 → 범위 판정 + 수치 기입
    cr.execute("""
        UPDATE iatf_check_sheet_item
           SET spec_mode = 'range', entry_type = 'numeric'
         WHERE (COALESCE(spec_min, 0) <> 0 OR COALESCE(spec_max, 0) <> 0)
           AND (spec_mode IS NULL OR spec_mode = 'qualitative')
    """)
    _logger.info("점검 항목 %s 건을 '범위 판정' 으로 옮겼습니다.", cr.rowcount)

    # 2. 나머지는 정성 판정으로 명시한다 (NULL 로 두면 제약이 걸린다)
    cr.execute("""
        UPDATE iatf_check_sheet_item
           SET spec_mode = COALESCE(spec_mode, 'qualitative'),
               entry_type = COALESCE(entry_type, 'judge')
         WHERE spec_mode IS NULL OR entry_type IS NULL
    """)

    # 3. 개정 차수 — 기존 시트는 1차로 본다
    cr.execute("UPDATE iatf_check_sheet SET revision = 1 WHERE COALESCE(revision, 0) = 0")

    # 4. 이미 있는 실적에 개정 차수를 채운다. 그 시점의 차수를 알 길이 없으므로
    #    현재 차수(=1)를 넣는다. 3번에서 전부 1 로 맞췄기 때문에 이 값은 정확하다.
    cr.execute("""
        UPDATE iatf_check_record r
           SET sheet_revision = s.revision
          FROM iatf_check_sheet s
         WHERE r.sheet_id = s.id
           AND COALESCE(r.sheet_revision, 0) = 0
    """)

    # 5. 실적 라인의 정의 스냅샷.
    #    COALESCE 로는 안 된다 — Odoo 는 새 컬럼을 만들 때 필드 기본값('정성'/'양호·불량')
    #    으로 기존 행을 이미 채워 놓는다. 그래서 NULL 이 아니라 '기본값이 박힌 상태' 를
    #    상대해야 한다. 상·하한이 있는 라인은 그 값으로 판정된 것이므로 '범위' 가 맞다.
    cr.execute("""
        UPDATE iatf_check_record_line l
           SET spec_mode = CASE
                   WHEN COALESCE(l.spec_min, 0) <> 0 OR COALESCE(l.spec_max, 0) <> 0
                        THEN COALESCE(NULLIF(i.spec_mode, 'qualitative'), 'range')
                   ELSE COALESCE(i.spec_mode, 'qualitative')
               END,
               entry_type = CASE
                   WHEN COALESCE(l.spec_min, 0) <> 0 OR COALESCE(l.spec_max, 0) <> 0
                        THEN 'numeric'
                   ELSE COALESCE(i.entry_type, 'judge')
               END,
               target_value = COALESCE(NULLIF(l.target_value, 0), i.target_value),
               tolerance = COALESCE(NULLIF(l.tolerance, 0), i.tolerance),
               is_key_item = COALESCE(i.is_key_item, false)
          FROM iatf_check_sheet_item i
         WHERE l.item_id = i.id
           AND COALESCE(l.spec_mode, 'qualitative') = 'qualitative'
    """)
    _logger.info("실적 라인 %s 건의 기준 스냅샷을 채웠습니다.", cr.rowcount)

    # 기준 항목이 이미 삭제된 실적 라인(item_id 가 끊긴 것)도 남는다. 이쪽은
    # 되짚을 기준이 없으니 라인에 남은 상·하한만 보고 판단한다.
    cr.execute("""
        UPDATE iatf_check_record_line
           SET spec_mode = 'range', entry_type = 'numeric'
         WHERE item_id IS NULL
           AND COALESCE(spec_mode, 'qualitative') = 'qualitative'
           AND (COALESCE(spec_min, 0) <> 0 OR COALESCE(spec_max, 0) <> 0)
    """)
    cr.execute("""
        UPDATE iatf_check_record_line
           SET spec_mode = COALESCE(spec_mode, 'qualitative'),
               entry_type = COALESCE(entry_type, 'judge'),
               is_key_item = COALESCE(is_key_item, false)
         WHERE spec_mode IS NULL OR entry_type IS NULL OR is_key_item IS NULL
    """)
