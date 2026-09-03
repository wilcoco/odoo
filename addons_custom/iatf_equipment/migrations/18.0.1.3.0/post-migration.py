def migrate(cr, version):
    """예비부품의 설비 연결을 1:N 필드에서 다대다 적용표로 옮긴다.

    이전 구조는 `iatf.equipment.spare.equipment_id` 가 required 였다. 즉 부품
    하나가 설비 하나만 가리킬 수 있어서, 같은 베어링이 사출기와 조립기에 함께
    쓰이면 부품 행을 설비 수만큼 복제해야 했다. 이제 연결은
    `iatf.spare.application` 이 들고, 부품 마스터는 한 행만 남는다.

    두 가지를 여기서 해야 한다.

    1. 기존 연결을 적용표로 옮긴다. 안 옮기면 "어느 설비에 들어가는가" 라는
       정보가 조용히 사라진다. 수량은 옛 구조에 없던 값이라 1 로 둔다.
    2. 남은 컬럼을 지운다. Odoo 는 모델에서 사라진 필드의 컬럼을 남겨 두는데,
       이 컬럼은 NOT NULL 이라 그대로 두면 **부품을 새로 등록할 때마다
       insert 가 실패한다.** 경고 로그 한 줄로 끝날 문제가 아니다.
    """
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'iatf_equipment_spare' AND column_name = 'equipment_id'
    """)
    if not cr.fetchone():
        return

    cr.execute("""
        INSERT INTO iatf_spare_application
            (spare_id, equipment_id, qty_per_unit, category_id,
             create_uid, create_date, write_uid, write_date)
        SELECT s.id, s.equipment_id, 1.0, s.category_id,
               s.create_uid, s.create_date, s.write_uid, s.write_date
          FROM iatf_equipment_spare s
         WHERE s.equipment_id IS NOT NULL
        ON CONFLICT (spare_id, equipment_id) DO NOTHING
    """)

    cr.execute("ALTER TABLE iatf_equipment_spare DROP COLUMN equipment_id")
