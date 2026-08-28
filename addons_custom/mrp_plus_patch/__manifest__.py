{
    "name": "수량 소수점 복원 패치 (MRP Plus)",
    "version": "18.0.1.0.0",
    "summary": "수량 자리수(Product Unit of Measure)를 2자리로 복원 — 사출 원재료(kg/EA) 소요량 소수점 표시",
    "category": "Manufacturing",
    "license": "LGPL-3",
    "author": "DevSanx",
    # injection_worksite: 사출품 BOM 원재료 소요량(kg)이 소수점을 요구하는 대표 사용처.
    # 수량 자리수 패치는 이 앱과 한 세트로 설치되도록 묶는다 (worksite 가
    # mrp·stock·product·purchase 를 전부 끌고 오므로 별도 명시는 mrp 만).
    "depends": ["mrp", "injection_worksite"],
    "data": [
        "data/decimal_precision.xml",
    ],
    "installable": True,
}
