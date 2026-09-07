def migrate(cr, version):
    """mtbf / availability_rate 를 저장 필드에서 계산 필드로 바꾸면서 남는 컬럼을 지운다.

    Odoo 는 store=True 를 해제해도 컬럼을 남긴다. 그런데 이 두 컬럼에는
    '가동시간이 없으면 가동률 100%' 라는 옛 계산 결과가 그대로 들어 있다.
    SQL 로 직접 조회하는 리포트가 생기면 그 거짓값을 읽게 되므로 지운다.
    값은 전부 다른 필드에서 재계산되므로 손실되는 데이터는 없다.
    """
    cr.execute("""
        ALTER TABLE iatf_equipment
            DROP COLUMN IF EXISTS mtbf,
            DROP COLUMN IF EXISTS availability_rate
    """)
