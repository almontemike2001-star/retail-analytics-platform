-- =============================================================================
-- BeanFlow Coffee - Phase 2 synthetic data validation queries
-- Run all:  docker compose exec -T postgres-source psql -U beanflow -d beanflow < simulator/sql/validate_patterns.sql
-- Each block prints the evidence for one intentional business pattern.
-- =============================================================================
\pset pager off
-- Time zone convention: the server and session run in UTC. Every business date, hour, weekday and
-- daypart below is derived from an explicit conversion, e.g. (order_ts AT TIME ZONE 'Asia/Manila'),
-- so results never depend on the session's TimeZone setting.

\echo '== 1. Row counts =='
SELECT 'regions' t, count(*) FROM pos.regions UNION ALL SELECT 'areas', count(*) FROM pos.areas
UNION ALL SELECT 'stores', count(*) FROM pos.stores UNION ALL SELECT 'product_categories', count(*) FROM pos.product_categories
UNION ALL SELECT 'products', count(*) FROM pos.products UNION ALL SELECT 'customers', count(*) FROM pos.customers
UNION ALL SELECT 'promotions', count(*) FROM pos.promotions UNION ALL SELECT 'orders', count(*) FROM pos.orders
UNION ALL SELECT 'order_items', count(*) FROM pos.order_items UNION ALL SELECT 'payments', count(*) FROM pos.payments;

\echo '== 2. Store type behaviour (kiosk: most tickets, lowest AOV; mall: biggest baskets) =='
WITH o AS (
    SELECT o.*, s.store_type, (SELECT sum(quantity) FROM pos.order_items i WHERE i.order_id = o.order_id) AS units
      FROM pos.orders o JOIN pos.stores s USING (store_id) WHERE o.order_status <> 'cancelled')
SELECT store_type,
       count(*)                                                        AS orders,
       round(count(*)::numeric / count(DISTINCT (store_id, (order_ts AT TIME ZONE 'Asia/Manila')::date)), 1) AS orders_per_store_day,
       round(avg(subtotal - discount_amount), 2)                       AS aov_net_php,
       round(avg(units), 2)                                            AS units_per_txn,
       round(100.0 * avg((customer_id IS NULL)::int), 1)               AS walk_in_pct
  FROM o GROUP BY store_type ORDER BY aov_net_php;

\echo '== 3. Orders by hour (peaks ~08:00, ~12:30, ~15:30; quiet early/late) =='
SELECT extract(hour FROM order_ts AT TIME ZONE 'Asia/Manila')::int AS hour, count(*) AS orders,
       repeat('#', (count(*) * 60 / max(count(*)) OVER ())::int) AS bar
  FROM pos.orders GROUP BY 1 ORDER BY 1;

\echo '== 3b. Morning (07-09) vs evening (18-20) share by store type (drive_thru/office morning-heavy, mall none) =='
SELECT s.store_type,
       round(100.0 * avg((extract(hour FROM o.order_ts AT TIME ZONE 'Asia/Manila') BETWEEN 7 AND 8)::int), 1)  AS pct_07_09,
       round(100.0 * avg((extract(hour FROM o.order_ts AT TIME ZONE 'Asia/Manila') BETWEEN 18 AND 19)::int), 1) AS pct_18_20
  FROM pos.orders o JOIN pos.stores s USING (store_id) GROUP BY 1 ORDER BY 2 DESC;

\echo '== 4. Weekday vs weekend orders per store-day (office collapses, mall rises) =='
WITH d AS (
    SELECT s.store_type, o.store_id, (o.order_ts AT TIME ZONE 'Asia/Manila')::date AS d, count(*) AS n
      FROM pos.orders o JOIN pos.stores s USING (store_id) GROUP BY 1, 2, 3)
SELECT store_type,
       round(avg(n) FILTER (WHERE extract(isodow FROM d) < 6), 1)  AS weekday_avg,
       round(avg(n) FILTER (WHERE extract(isodow FROM d) >= 6), 1) AS weekend_avg,
       round(avg(n) FILTER (WHERE extract(isodow FROM d) >= 6)
           / avg(n) FILTER (WHERE extract(isodow FROM d) < 6), 2)  AS weekend_index
  FROM d GROUP BY 1 ORDER BY weekend_index;

\echo '== 5. Payday effect (15th, last day of month and the day after vs. other days) =='
WITH daily AS (
    SELECT (order_ts AT TIME ZONE 'Asia/Manila')::date AS d, count(*) AS n, sum(subtotal - discount_amount) AS net
      FROM pos.orders WHERE order_status <> 'cancelled' GROUP BY 1)
SELECT CASE WHEN extract(day FROM d) IN (15, 16) OR d = (date_trunc('month', d) + interval '1 month - 1 day')::date
                 OR extract(day FROM d) = 1 THEN 'payday window' ELSE 'other days' END AS day_type,
       count(*) AS days, round(avg(n)) AS avg_orders, round(avg(net)) AS avg_net_sales_php
  FROM daily GROUP BY 1;

\echo '== 6. Monthly seasonality (daily average; December peaks in backfills that include it) =='
SELECT to_char(order_ts AT TIME ZONE 'Asia/Manila', 'YYYY-MM') AS month, count(DISTINCT (order_ts AT TIME ZONE 'Asia/Manila')::date) AS days,
       round(count(*)::numeric / count(DISTINCT (order_ts AT TIME ZONE 'Asia/Manila')::date)) AS orders_per_day
  FROM pos.orders GROUP BY 1 ORDER BY 1;

\echo '== 7. Walk-in share (target 30-40 %) =='
SELECT round(100.0 * avg((customer_id IS NULL)::int), 1) AS walk_in_pct,
       round(100.0 * avg((customer_id IS NOT NULL)::int), 1) AS identified_pct
  FROM pos.orders;

\echo '== 8. Customer repeat behaviour (skewed: many one-timers, few heavy regulars) =='
WITH c AS (SELECT customer_id, count(*) AS n FROM pos.orders WHERE customer_id IS NOT NULL GROUP BY 1)
SELECT CASE WHEN n = 1 THEN '1 order (one-time)' WHEN n <= 3 THEN '2-3 orders' WHEN n <= 9 THEN '4-9 orders'
            WHEN n <= 24 THEN '10-24 orders' ELSE '25+ orders (loyal)' END AS bucket,
       count(*) AS customers, sum(n) AS orders,
       round(100.0 * sum(n) / sum(sum(n)) OVER (), 1) AS pct_of_identified_orders
  FROM c GROUP BY 1 ORDER BY min(n);
WITH c AS (SELECT customer_id, count(*) AS n, ntile(10) OVER (ORDER BY count(*) DESC) AS decile
             FROM pos.orders WHERE customer_id IS NOT NULL GROUP BY 1)
SELECT round(100.0 * sum(n) FILTER (WHERE decile = 1) / sum(n), 1) AS top_10pct_customers_share_of_orders FROM c;
SELECT round(100.0 * count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM pos.orders o WHERE o.customer_id = c.customer_id))
       / count(*), 1) AS members_with_no_orders_pct FROM pos.customers c;

\echo '== 9. Product popularity (Pareto: top 20 % of SKUs carry most units) =='
WITH u AS (SELECT p.product_name, p.size, sum(i.quantity) AS units
             FROM pos.order_items i JOIN pos.products p USING (product_id) GROUP BY 1, 2)
SELECT product_name, size, units, round(100.0 * units / sum(units) OVER (), 2) AS pct_units
  FROM u ORDER BY units DESC LIMIT 10;
WITH u AS (SELECT product_id, sum(quantity) AS units, ntile(5) OVER (ORDER BY sum(quantity) DESC) AS q
             FROM pos.order_items GROUP BY 1)
SELECT round(100.0 * sum(units) FILTER (WHERE q = 1) / sum(units), 1) AS top_20pct_skus_share_of_units FROM u;

\echo '== 10. Category mix by daypart (coffee AM, meals at lunch, cold drinks PM) =='
WITH x AS (
    SELECT c.category_name,
           CASE WHEN extract(hour FROM o.order_ts AT TIME ZONE 'Asia/Manila') < 11 THEN '1 morning' WHEN extract(hour FROM o.order_ts AT TIME ZONE 'Asia/Manila') < 14 THEN '2 lunch'
                WHEN extract(hour FROM o.order_ts AT TIME ZONE 'Asia/Manila') < 18 THEN '3 afternoon' ELSE '4 evening' END AS daypart, i.quantity
      FROM pos.order_items i JOIN pos.orders o USING (order_id) JOIN pos.products p USING (product_id)
      JOIN pos.product_categories c USING (category_id))
SELECT category_name,
       round(100.0 * sum(quantity) FILTER (WHERE daypart = '1 morning')   / sum(sum(quantity) FILTER (WHERE daypart = '1 morning')) OVER (), 1)   AS morning_pct,
       round(100.0 * sum(quantity) FILTER (WHERE daypart = '2 lunch')     / sum(sum(quantity) FILTER (WHERE daypart = '2 lunch')) OVER (), 1)     AS lunch_pct,
       round(100.0 * sum(quantity) FILTER (WHERE daypart = '3 afternoon') / sum(sum(quantity) FILTER (WHERE daypart = '3 afternoon')) OVER (), 1) AS afternoon_pct,
       round(100.0 * sum(quantity) FILTER (WHERE daypart = '4 evening')   / sum(sum(quantity) FILTER (WHERE daypart = '4 evening')) OVER (), 1)   AS evening_pct
  FROM x GROUP BY 1 ORDER BY 1;

\echo '== 11. Basket size (mostly 1-3 lines, occasional large baskets) =='
SELECT lines, count(*) AS orders, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
  FROM (SELECT order_id, count(*) AS lines FROM pos.order_items GROUP BY 1) b GROUP BY 1 ORDER BY 1;
SELECT quantity, count(*) AS lines FROM pos.order_items GROUP BY 1 ORDER BY 1;

\echo '== 12. Promotions (only some eligible orders use one; payday/holiday percent, fixed, bundle) =='
SELECT coalesce(p.promo_type, '(none)') AS promo_type, split_part(p.promo_code, '-', 1) AS campaign, count(*) AS orders,
       round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct_orders,
       sum(o.discount_amount) AS order_discount_php,
       sum((SELECT sum(line_discount) FROM pos.order_items i WHERE i.order_id = o.order_id)) AS line_discount_php
  FROM pos.orders o LEFT JOIN pos.promotions p USING (promotion_id) GROUP BY 1, 2 ORDER BY 3 DESC;

\echo '== 13. Payments: tender mix, split tender, failed attempts, refunds =='
SELECT payment_method, payment_status, count(*), round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
  FROM pos.payments GROUP BY 1, 2 ORDER BY 1, 2;
SELECT count(*) AS split_tender_orders
  FROM (SELECT order_id FROM pos.payments WHERE payment_status = 'paid' GROUP BY 1 HAVING count(*) > 1) x;

\echo '== 14. Order status mix (~97.5 % completed, ~2 % cancelled, ~0.5-0.7 % refunded) =='
SELECT order_status, count(*), round(100.0 * count(*) / sum(count(*)) OVER (), 2) AS pct FROM pos.orders GROUP BY 1;

\echo '== 15. Order totals reconcile (every count must be 0) =='
SELECT
  (SELECT count(*) FROM pos.order_items WHERE line_total <> quantity * unit_price - line_discount)        AS bad_line_totals,
  (SELECT count(*) FROM pos.orders o WHERE subtotal <> (SELECT sum(line_total) FROM pos.order_items i
                                                          WHERE i.order_id = o.order_id))               AS bad_subtotals,
  (SELECT count(*) FROM pos.orders WHERE total_amount <> subtotal - discount_amount + tax_amount)         AS bad_totals,
  (SELECT count(*) FROM pos.orders WHERE tax_amount <> round((subtotal - discount_amount) * 0.12, 2))    AS bad_vat,
  (SELECT count(*) FROM pos.orders o WHERE order_status IN ('completed', 'refunded')
      AND total_amount <> (SELECT coalesce(sum(amount), 0) FROM pos.payments p
                            WHERE p.order_id = o.order_id AND p.payment_status = 'paid'))               AS bad_payment_sums,
  (SELECT count(*) FROM pos.orders o WHERE order_status = 'refunded'
      AND NOT EXISTS (SELECT 1 FROM pos.payments p WHERE p.order_id = o.order_id
                         AND p.payment_status = 'refunded'))                                             AS refunds_without_refund_payment,
  (SELECT count(*) FROM pos.orders o WHERE order_status = 'cancelled'
      AND EXISTS (SELECT 1 FROM pos.payments p WHERE p.order_id = o.order_id AND p.payment_status = 'paid')) AS cancelled_but_paid;

\echo '== 16. updated_at is historical (written_in_last_15_min must be 0 right after a backfill) =='
SELECT 'orders' t, min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') AS written_in_last_15_min FROM pos.orders
UNION ALL SELECT 'order_items', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.order_items
UNION ALL SELECT 'payments', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.payments
UNION ALL SELECT 'customers', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.customers
UNION ALL SELECT 'stores', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.stores
UNION ALL SELECT 'products', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.products
UNION ALL SELECT 'promotions', min(updated_at AT TIME ZONE 'Asia/Manila')::date, max(updated_at AT TIME ZONE 'Asia/Manila')::date, count(*) FILTER (WHERE updated_at > now() - interval '15 minutes') FROM pos.promotions;
SELECT (updated_at AT TIME ZONE 'Asia/Manila')::date AS updated_on, count(*) AS orders FROM pos.orders GROUP BY 1 ORDER BY 1 DESC LIMIT 5;
SELECT count(*) FILTER (WHERE (updated_at AT TIME ZONE 'Asia/Manila')::date = (order_ts AT TIME ZONE 'Asia/Manila')::date) AS same_day_updates,
       count(*) FILTER (WHERE (updated_at AT TIME ZONE 'Asia/Manila')::date > (order_ts AT TIME ZONE 'Asia/Manila')::date)  AS later_updates_refunds
  FROM pos.orders;

\echo '== 17. Mutations captured for SCD2 / incremental extraction =='
SELECT 'refunded orders' AS change, count(*) FROM pos.orders WHERE order_status = 'refunded'
UNION ALL SELECT 'customers above basic tier', count(*) FROM pos.customers WHERE loyalty_tier <> 'basic'
UNION ALL SELECT 'stores not active', count(*) FROM pos.stores WHERE status <> 'active'
UNION ALL SELECT 'stores changed after opening', count(*) FROM pos.stores WHERE (updated_at AT TIME ZONE 'Asia/Manila')::date > opened_date
UNION ALL SELECT 'products changed after launch', count(*) FROM pos.products WHERE (updated_at AT TIME ZONE 'Asia/Manila')::date > launched_date;
SELECT store_code, status, area_id, opened_date, closed_date, updated_at AT TIME ZONE 'Asia/Manila' AS updated_at_manila FROM pos.stores
 WHERE (updated_at AT TIME ZONE 'Asia/Manila')::date > opened_date ORDER BY updated_at;
SELECT loyalty_tier, count(*) FROM pos.customers GROUP BY 1 ORDER BY 2 DESC;

\echo '== 18. New store openings and product launches inside the window =='
SELECT store_code, store_type, opened_date, min(o.order_ts AT TIME ZONE 'Asia/Manila')::date AS first_order
  FROM pos.stores s JOIN pos.orders o USING (store_id)
 WHERE opened_date > (SELECT min(order_ts AT TIME ZONE 'Asia/Manila')::date FROM pos.orders) GROUP BY 1, 2, 3 ORDER BY 3;
SELECT p.product_name, p.launched_date, min(o.order_ts AT TIME ZONE 'Asia/Manila')::date AS first_sold
  FROM pos.products p JOIN pos.order_items i USING (product_id) JOIN pos.orders o USING (order_id)
 WHERE p.launched_date > (SELECT min(order_ts AT TIME ZONE 'Asia/Manila')::date FROM pos.orders) GROUP BY 1, 2 ORDER BY 2;
