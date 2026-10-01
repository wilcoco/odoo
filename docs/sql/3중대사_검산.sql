-- 발주없는매입 UAT 7단계 — 3중 대사 검산 (읽기 전용)
-- 사용법: psql -U odoo -d odoo18 -v from="'2026-08-01'" -v to="'2026-08-31'" -f 3중대사_검산.sql
-- ① 사용실적 합계 = ② 매입계산서 공급가 합계 = ③ 거래처원장 미지급금  (업체별 1원 단위 일치)
\pset border 2

-- ────────────────────────────────────────────────────────────────
-- ① 사용실적(정산 적립) — 청구서로 넘어간 것만
-- ────────────────────────────────────────────────────────────────
\echo '=== ① 사용실적 합계 (vendor_mrp_accrual, state=billed) ==='
SELECT p.name AS 공급업체,
       count(*)      AS 적립건수,
       sum(a.amount) AS 사용실적합계
  FROM vendor_mrp_accrual a
  JOIN res_partner p ON p.id = a.vendor_id
 WHERE a.state = 'billed'
   AND a.date BETWEEN :from::date AND :to::date
 GROUP BY p.name
 ORDER BY p.name;

-- ────────────────────────────────────────────────────────────────
-- ② 매입계산서 공급가 — ①이 링크한 청구서만 (전기된 것)
-- ────────────────────────────────────────────────────────────────
\echo '=== ② 매입계산서 공급가 합계 (전기분) ==='
SELECT p.name AS 공급업체,
       count(DISTINCT m.id)  AS 계산서건수,
       sum(m.amount_untaxed) AS 공급가합계,
       sum(m.amount_tax)     AS 세액합계,
       sum(m.amount_total)   AS 총액
  FROM account_move m
  JOIN res_partner p ON p.id = m.partner_id
 WHERE m.id IN (SELECT DISTINCT bill_id FROM vendor_mrp_accrual
                 WHERE bill_id IS NOT NULL
                   AND date BETWEEN :from::date AND :to::date)
   AND m.state = 'posted'
 GROUP BY p.name
 ORDER BY p.name;

-- 전기 누락 점검 — 여기 뭔가 나오면 ②·③ 불일치의 원인은 대부분 이것
\echo '=== ②-주의: 초안(미전기) 상태로 남은 계산서 ==='
SELECT p.name AS 공급업체, m.name AS 계산서, m.state AS 상태, m.amount_total AS 총액
  FROM account_move m
  JOIN res_partner p ON p.id = m.partner_id
 WHERE m.id IN (SELECT DISTINCT bill_id FROM vendor_mrp_accrual
                 WHERE bill_id IS NOT NULL
                   AND date BETWEEN :from::date AND :to::date)
   AND m.state <> 'posted'
 ORDER BY p.name;

-- ────────────────────────────────────────────────────────────────
-- ③ 거래처원장 미지급금 잔액
-- ────────────────────────────────────────────────────────────────
\echo '=== ③ 미지급금 잔액 (매입채무 계정, 전기분) ==='
SELECT p.name AS 공급업체,
       -sum(l.balance) AS 미지급금잔액
  FROM account_move_line l
  JOIN account_move m   ON m.id = l.move_id
  JOIN account_account a ON a.id = l.account_id
  JOIN res_partner p     ON p.id = l.partner_id
 WHERE a.account_type = 'liability_payable'
   AND m.state = 'posted'
   AND p.id IN (SELECT DISTINCT vendor_id FROM vendor_mrp_accrual
                 WHERE date BETWEEN :from::date AND :to::date)
 GROUP BY p.name
 ORDER BY p.name;

-- ────────────────────────────────────────────────────────────────
-- 판정표 — 세 다리를 한 줄로. 판정 컬럼이 전부 '일치'여야 정상.
-- ────────────────────────────────────────────────────────────────
\echo '=== 판정: ①=② 및 ②총액=③ 잔액 ==='
WITH acc AS (
    SELECT a.vendor_id, sum(a.amount) AS 사용실적
      FROM vendor_mrp_accrual a
     WHERE a.state = 'billed'
       AND a.date BETWEEN :from::date AND :to::date
     GROUP BY a.vendor_id
), bills AS (
    SELECT a.vendor_id,
           sum(DISTINCT_m.amount_untaxed) AS 공급가,
           sum(DISTINCT_m.amount_total)   AS 총액
      FROM (SELECT DISTINCT vendor_id, bill_id FROM vendor_mrp_accrual
             WHERE bill_id IS NOT NULL
               AND date BETWEEN :from::date AND :to::date) a
      JOIN account_move DISTINCT_m ON DISTINCT_m.id = a.bill_id
     WHERE DISTINCT_m.state = 'posted'
     GROUP BY a.vendor_id
), ledger AS (
    SELECT l.partner_id AS vendor_id, -sum(l.balance) AS 미지급금
      FROM account_move_line l
      JOIN account_move m    ON m.id = l.move_id
      JOIN account_account a ON a.id = l.account_id
     WHERE a.account_type = 'liability_payable'
       AND m.state = 'posted'
     GROUP BY l.partner_id
)
SELECT p.name AS 공급업체,
       acc.사용실적,
       bills.공급가,
       bills.총액,
       ledger.미지급금,
       CASE WHEN acc.사용실적 = bills.공급가 THEN '일치' ELSE '★불일치' END AS "①=②",
       CASE WHEN bills.총액   = ledger.미지급금 THEN '일치' ELSE '★불일치(지급분 있으면 정상)' END AS "②=③"
  FROM acc
  JOIN res_partner p ON p.id = acc.vendor_id
  LEFT JOIN bills  ON bills.vendor_id  = acc.vendor_id
  LEFT JOIN ledger ON ledger.vendor_id = acc.vendor_id
 ORDER BY p.name;

-- 주의: ③은 기간 필터가 없는 '현재 잔액'이다. 해당 업체에 지급(대변 상계)이
-- 있었거나 다른 경로(수지 톤정산 등) 청구가 섞이면 ②와 달라지는 것이 정상이다.
-- ①=② 가 틀리면 그건 항상 결함이다.
