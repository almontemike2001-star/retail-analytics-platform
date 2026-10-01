-- =============================================================================
-- BeanFlow Coffee - Phase 1 source schema validation
-- Run:  docker compose exec -T postgres-source psql -U beanflow -d beanflow \
--         -v ON_ERROR_STOP=1 < source_db/tests/validate_phase1.sql
--
-- Everything runs inside one transaction that is ROLLED BACK at the end,
-- so the database is left empty. Each check prints PASS or raises FAIL.
-- =============================================================================
\set QUIET on
BEGIN;

-- ---- Minimal valid fixture rows ---------------------------------------------
INSERT INTO pos.regions (region_id, region_name) VALUES (1, 'Test Region');
INSERT INTO pos.areas (area_id, region_id, area_name) VALUES (1, 1, 'Test Area');
INSERT INTO pos.stores (store_id, area_id, store_code, store_name, store_type, city, opened_date)
VALUES (1, 1, 'BF-TEST', 'BeanFlow Test Store', 'mall', 'Test City', DATE '2024-01-01');
INSERT INTO pos.product_categories (category_id, category_name, category_group) VALUES (1, 'Espresso', 'beverage');
INSERT INTO pos.products (product_id, category_id, sku, product_name, size, base_price, unit_cost, launched_date)
VALUES (1, 1, 'ESP-LAT-M', 'Latte', 'medium', 150.00, 45.00, DATE '2024-01-01');
INSERT INTO pos.orders (order_id, order_number, store_id, order_ts, order_channel, subtotal, total_amount)
VALUES (1, 'T-0001', 1, now(), 'takeaway', 300.00, 300.00);

-- ---- Helper: expect a statement to fail with a given SQLSTATE ----------------
CREATE FUNCTION pg_temp.expect_error(p_label text, p_sql text, p_sqlstate text) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
    EXCEPTION WHEN OTHERS THEN
        IF SQLSTATE = p_sqlstate THEN
            RAISE NOTICE 'PASS  %  (rejected: %)', p_label, SQLERRM;
            RETURN;
        END IF;
        RAISE EXCEPTION 'FAIL  %  (wrong error % : %)', p_label, SQLSTATE, SQLERRM;
    END;
    RAISE EXCEPTION 'FAIL  %  (invalid row was accepted)', p_label;
END $$;

\o /dev/null
-- 23514 = check_violation, 23503 = foreign_key_violation, 23505 = unique_violation
SELECT pg_temp.expect_error('order_items.quantity must be > 0',
  $q$INSERT INTO pos.order_items (order_id, product_id, quantity, unit_price, line_total) VALUES (1, 1, 0, 150, 0)$q$, '23514');
SELECT pg_temp.expect_error('products.unit_cost must be >= 0',
  $q$INSERT INTO pos.products (category_id, sku, product_name, base_price, unit_cost, launched_date) VALUES (1, 'BAD-1', 'Bad', 100, -1, DATE '2024-01-01')$q$, '23514');
SELECT pg_temp.expect_error('promotions.start_date <= end_date',
  $q$INSERT INTO pos.promotions (promo_code, promo_name, promo_type, discount_value, start_date, end_date) VALUES ('BAD', 'Bad', 'fixed', 20, DATE '2024-02-01', DATE '2024-01-01')$q$, '23514');
SELECT pg_temp.expect_error('promotions.percent discount <= 100',
  $q$INSERT INTO pos.promotions (promo_code, promo_name, promo_type, discount_value, start_date, end_date) VALUES ('BAD2', 'Bad', 'percent', 150, DATE '2024-01-01', DATE '2024-01-31')$q$, '23514');
SELECT pg_temp.expect_error('stores.closed_date >= opened_date',
  $q$INSERT INTO pos.stores (area_id, store_code, store_name, store_type, city, opened_date, closed_date, status) VALUES (1, 'BF-BAD', 'Bad', 'mall', 'X', DATE '2024-05-01', DATE '2024-04-01', 'closed')$q$, '23514');
SELECT pg_temp.expect_error('stores.store_type accepted values',
  $q$INSERT INTO pos.stores (area_id, store_code, store_name, store_type, city, opened_date) VALUES (1, 'BF-BAD2', 'Bad', 'warehouse', 'X', DATE '2024-01-01')$q$, '23514');
SELECT pg_temp.expect_error('orders.order_channel accepted values',
  $q$INSERT INTO pos.orders (order_number, store_id, order_ts, order_channel, subtotal, total_amount) VALUES ('T-BAD1', 1, now(), 'drone', 100, 100)$q$, '23514');
SELECT pg_temp.expect_error('orders.order_status accepted values',
  $q$INSERT INTO pos.orders (order_number, store_id, order_ts, order_channel, order_status, subtotal, total_amount) VALUES ('T-BAD2', 1, now(), 'dine_in', 'lost', 100, 100)$q$, '23514');
SELECT pg_temp.expect_error('orders.discount_amount must be >= 0',
  $q$INSERT INTO pos.orders (order_number, store_id, order_ts, order_channel, subtotal, discount_amount, total_amount) VALUES ('T-BAD3', 1, now(), 'dine_in', 100, -5, 105)$q$, '23514');
SELECT pg_temp.expect_error('payments.payment_method accepted values',
  $q$INSERT INTO pos.payments (order_id, payment_method, amount, paid_at) VALUES (1, 'bitcoin', 100, now())$q$, '23514');
SELECT pg_temp.expect_error('payments.payment_status accepted values',
  $q$INSERT INTO pos.payments (order_id, payment_method, amount, payment_status, paid_at) VALUES (1, 'cash', 100, 'pending', now())$q$, '23514');
SELECT pg_temp.expect_error('customers.loyalty_tier accepted values',
  $q$INSERT INTO pos.customers (full_name, signup_date, loyalty_tier) VALUES ('Test Person', DATE '2024-01-01', 'diamond')$q$, '23514');
SELECT pg_temp.expect_error('order_items -> orders foreign key',
  $q$INSERT INTO pos.order_items (order_id, product_id, quantity, unit_price, line_total) VALUES (999999, 1, 1, 150, 150)$q$, '23503');
SELECT pg_temp.expect_error('stores.store_code unique',
  $q$INSERT INTO pos.stores (area_id, store_code, store_name, store_type, city, opened_date) VALUES (1, 'BF-TEST', 'Dup', 'mall', 'X', DATE '2024-01-01')$q$, '23505');
SELECT pg_temp.expect_error('products.sku unique',
  $q$INSERT INTO pos.products (category_id, sku, product_name, base_price, unit_cost, launched_date) VALUES (1, 'ESP-LAT-M', 'Dup', 100, 10, DATE '2024-01-01')$q$, '23505');
SELECT pg_temp.expect_error('orders.order_number unique',
  $q$INSERT INTO pos.orders (order_number, store_id, order_ts, order_channel, subtotal, total_amount) VALUES ('T-0001', 1, now(), 'dine_in', 100, 100)$q$, '23505');

\o

-- ---- Nullable customer_id / promotion_id (walk-in, no promo) ----------------
DO $$
BEGIN
    INSERT INTO pos.orders (order_number, store_id, customer_id, promotion_id, order_ts, order_channel, subtotal, total_amount)
    VALUES ('T-WALKIN', 1, NULL, NULL, now(), 'dine_in', 150, 150);
    RAISE NOTICE 'PASS  walk-in order with NULL customer_id and promotion_id accepted';
END $$;

-- ---- Multiple payments per order (split tender + refund) --------------------
DO $$
DECLARE n int;
BEGIN
    INSERT INTO pos.payments (order_id, payment_method, amount, payment_status, paid_at) VALUES
        (1, 'cash',     100.00, 'paid',     now()),
        (1, 'e_wallet', 200.00, 'paid',     now()),
        (1, 'e_wallet', 200.00, 'refunded', now());
    SELECT count(*) INTO n FROM pos.payments WHERE order_id = 1;
    IF n <> 3 THEN RAISE EXCEPTION 'FAIL  expected 3 payments, found %', n; END IF;
    RAISE NOTICE 'PASS  3 payment rows reference order 1 (split tender + refund)';
END $$;

-- ---- updated_at trigger ------------------------------------------------------
-- now() is frozen within a transaction, so backdate the row first, then update.
DO $$
DECLARE before_ts timestamptz; after_ts timestamptz;
BEGIN
    UPDATE pos.orders SET updated_at = TIMESTAMPTZ '2024-01-01 00:00:00+00' WHERE order_id = 1;  -- explicit value is kept
    SELECT updated_at INTO before_ts FROM pos.orders WHERE order_id = 1;
    IF before_ts <> TIMESTAMPTZ '2024-01-01 00:00:00+00' THEN RAISE EXCEPTION 'FAIL  explicit updated_at was overwritten'; END IF;
    RAISE NOTICE 'PASS  explicit updated_at preserved (simulator backfill)';

    UPDATE pos.orders SET order_status = 'refunded' WHERE order_id = 1;                         -- real change
    SELECT updated_at INTO after_ts FROM pos.orders WHERE order_id = 1;
    IF after_ts <> now() THEN RAISE EXCEPTION 'FAIL  updated_at not bumped on change (got %)', after_ts; END IF;
    RAISE NOTICE 'PASS  updated_at set to now() on status change';

    UPDATE pos.orders SET updated_at = TIMESTAMPTZ '2024-01-01 00:00:00+00' WHERE order_id = 1;
    UPDATE pos.orders SET order_status = 'refunded' WHERE order_id = 1;                         -- no-op update
    SELECT updated_at INTO after_ts FROM pos.orders WHERE order_id = 1;
    IF after_ts <> TIMESTAMPTZ '2024-01-01 00:00:00+00' THEN RAISE EXCEPTION 'FAIL  no-op update bumped updated_at'; END IF;
    RAISE NOTICE 'PASS  no-op update leaves updated_at unchanged';
END $$;

ROLLBACK;
\echo 'Phase 1 validation finished (transaction rolled back, no data left behind).'
