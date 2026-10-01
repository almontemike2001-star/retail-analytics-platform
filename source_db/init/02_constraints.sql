-- =============================================================================
-- BeanFlow Coffee - POS operational source system
-- 02_constraints.sql : primary keys, unique keys, CHECK constraints,
--                      foreign keys, and supporting indexes
--
-- Rerunnable: every constraint is added through pg_temp.add_constraint(),
-- which skips constraints that already exist (PostgreSQL 16 has no
-- ADD CONSTRAINT IF NOT EXISTS). Indexes use CREATE INDEX IF NOT EXISTS.
-- Note: an existing constraint is never redefined by a rerun; to change one,
-- recreate the volume (local dev) or write an explicit migration.
--
-- Scope: single-row rules only (types, ranges, accepted values, row-level
-- consistency). Cross-row and cross-table business rules - e.g. order total
-- equals the sum of its lines, payments sum to the order total, orders fall
-- within the store's trading dates - are intentionally NOT enforced here.
-- Like most real POS systems, this source can contain such inconsistencies;
-- they are detected downstream by dbt tests.
-- =============================================================================

-- Session-scoped helper (lives in pg_temp, disappears when this script ends).
CREATE OR REPLACE FUNCTION pg_temp.add_constraint(p_table regclass, p_name text, p_definition text)
RETURNS void
LANGUAGE plpgsql
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = p_table AND conname = p_name
    ) THEN
        EXECUTE format('ALTER TABLE %s ADD CONSTRAINT %I %s', p_table, p_name, p_definition);
    END IF;
END;
$$;

-- =============================================================================
-- 1. PRIMARY KEYS
-- =============================================================================
SELECT pg_temp.add_constraint('pos.regions',            'pk_regions',            'PRIMARY KEY (region_id)');
SELECT pg_temp.add_constraint('pos.areas',              'pk_areas',              'PRIMARY KEY (area_id)');
SELECT pg_temp.add_constraint('pos.stores',             'pk_stores',             'PRIMARY KEY (store_id)');
SELECT pg_temp.add_constraint('pos.product_categories', 'pk_product_categories', 'PRIMARY KEY (category_id)');
SELECT pg_temp.add_constraint('pos.products',           'pk_products',           'PRIMARY KEY (product_id)');
SELECT pg_temp.add_constraint('pos.customers',          'pk_customers',          'PRIMARY KEY (customer_id)');
SELECT pg_temp.add_constraint('pos.promotions',         'pk_promotions',         'PRIMARY KEY (promotion_id)');
SELECT pg_temp.add_constraint('pos.orders',             'pk_orders',             'PRIMARY KEY (order_id)');
SELECT pg_temp.add_constraint('pos.order_items',        'pk_order_items',        'PRIMARY KEY (order_item_id)');
SELECT pg_temp.add_constraint('pos.payments',           'pk_payments',           'PRIMARY KEY (payment_id)');

-- =============================================================================
-- 2. UNIQUE (natural / business keys)
-- =============================================================================
SELECT pg_temp.add_constraint('pos.regions',            'uq_regions_region_name',          'UNIQUE (region_name)');
SELECT pg_temp.add_constraint('pos.areas',              'uq_areas_region_area_name',       'UNIQUE (region_id, area_name)');
SELECT pg_temp.add_constraint('pos.stores',             'uq_stores_store_code',            'UNIQUE (store_code)');
SELECT pg_temp.add_constraint('pos.product_categories', 'uq_product_categories_name',      'UNIQUE (category_name)');
SELECT pg_temp.add_constraint('pos.products',           'uq_products_sku',                 'UNIQUE (sku)');
SELECT pg_temp.add_constraint('pos.customers',          'uq_customers_email',              'UNIQUE (email)');     -- NULLs allowed, not compared
SELECT pg_temp.add_constraint('pos.promotions',         'uq_promotions_promo_code',        'UNIQUE (promo_code)');
SELECT pg_temp.add_constraint('pos.orders',             'uq_orders_order_number',          'UNIQUE (order_number)');
-- Note: payments has no business-key uniqueness on purpose - an order may have
-- many payment rows (split tender, failed attempts, refunds).

-- =============================================================================
-- 3. CHECK constraints
-- =============================================================================

-- ---- Names / codes must not be blank --------------------------------------
SELECT pg_temp.add_constraint('pos.regions',            'ck_regions_name_not_blank',    $c$CHECK (btrim(region_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.areas',              'ck_areas_name_not_blank',      $c$CHECK (btrim(area_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.product_categories', 'ck_categories_name_not_blank', $c$CHECK (btrim(category_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.stores',             'ck_stores_code_not_blank',     $c$CHECK (btrim(store_code) <> '' AND btrim(store_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.products',           'ck_products_sku_not_blank',    $c$CHECK (btrim(sku) <> '' AND btrim(product_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.promotions',         'ck_promotions_code_not_blank', $c$CHECK (btrim(promo_code) <> '' AND btrim(promo_name) <> '')$c$);
SELECT pg_temp.add_constraint('pos.orders',             'ck_orders_number_not_blank',   $c$CHECK (btrim(order_number) <> '')$c$);

-- ---- stores ----------------------------------------------------------------
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_store_type',
    $c$CHECK (store_type IN ('mall', 'street', 'office', 'drive_thru', 'kiosk'))$c$);
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_status',
    $c$CHECK (status IN ('active', 'temporarily_closed', 'closed'))$c$);
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_closed_after_opened',
    $c$CHECK (closed_date IS NULL OR closed_date >= opened_date)$c$);
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_closed_status_has_date',
    $c$CHECK ((status = 'closed') = (closed_date IS NOT NULL))$c$);   -- closed <=> closed_date set
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_latitude',
    $c$CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90)$c$);
SELECT pg_temp.add_constraint('pos.stores', 'ck_stores_longitude',
    $c$CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)$c$);

-- ---- product_categories / products ----------------------------------------
SELECT pg_temp.add_constraint('pos.product_categories', 'ck_categories_group',
    $c$CHECK (category_group IN ('beverage', 'food', 'merchandise'))$c$);
SELECT pg_temp.add_constraint('pos.products', 'ck_products_size',
    $c$CHECK (size IS NULL OR size IN ('small', 'medium', 'large'))$c$);
SELECT pg_temp.add_constraint('pos.products', 'ck_products_base_price_non_negative',
    $c$CHECK (base_price >= 0)$c$);
SELECT pg_temp.add_constraint('pos.products', 'ck_products_unit_cost_non_negative',
    $c$CHECK (unit_cost >= 0)$c$);

-- ---- customers -------------------------------------------------------------
SELECT pg_temp.add_constraint('pos.customers', 'ck_customers_loyalty_tier',
    $c$CHECK (loyalty_tier IN ('basic', 'silver', 'gold', 'platinum'))$c$);
SELECT pg_temp.add_constraint('pos.customers', 'ck_customers_gender',
    $c$CHECK (gender IS NULL OR gender IN ('female', 'male', 'non_binary', 'undisclosed'))$c$);
SELECT pg_temp.add_constraint('pos.customers', 'ck_customers_email_format',
    $c$CHECK (email IS NULL OR email ~ '^[^@[:space:]]+@[^@[:space:]]+\.[^@[:space:]]+$')$c$);
SELECT pg_temp.add_constraint('pos.customers', 'ck_customers_email_lowercase',
    $c$CHECK (email IS NULL OR email = lower(email))$c$);        -- makes UNIQUE(email) case-insensitive in practice
SELECT pg_temp.add_constraint('pos.customers', 'ck_customers_birth_before_signup',
    $c$CHECK (birth_date IS NULL OR (birth_date >= DATE '1900-01-01' AND birth_date < signup_date))$c$);

-- ---- promotions ------------------------------------------------------------
SELECT pg_temp.add_constraint('pos.promotions', 'ck_promotions_promo_type',
    $c$CHECK (promo_type IN ('percent', 'fixed', 'bundle'))$c$);
SELECT pg_temp.add_constraint('pos.promotions', 'ck_promotions_discount_value',
    $c$CHECK (discount_value > 0 AND (promo_type <> 'percent' OR discount_value <= 100))$c$);
SELECT pg_temp.add_constraint('pos.promotions', 'ck_promotions_min_order_non_negative',
    $c$CHECK (min_order_amount >= 0)$c$);
SELECT pg_temp.add_constraint('pos.promotions', 'ck_promotions_date_range',
    $c$CHECK (start_date <= end_date)$c$);

-- ---- orders ----------------------------------------------------------------
SELECT pg_temp.add_constraint('pos.orders', 'ck_orders_channel',
    $c$CHECK (order_channel IN ('dine_in', 'takeaway', 'delivery'))$c$);
SELECT pg_temp.add_constraint('pos.orders', 'ck_orders_status',
    $c$CHECK (order_status IN ('completed', 'cancelled', 'refunded'))$c$);
SELECT pg_temp.add_constraint('pos.orders', 'ck_orders_amounts_non_negative',
    $c$CHECK (subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0)$c$);
SELECT pg_temp.add_constraint('pos.orders', 'ck_orders_discount_not_above_subtotal',
    $c$CHECK (discount_amount <= subtotal)$c$);

-- ---- order_items -----------------------------------------------------------
SELECT pg_temp.add_constraint('pos.order_items', 'ck_order_items_quantity_positive',
    $c$CHECK (quantity > 0)$c$);
SELECT pg_temp.add_constraint('pos.order_items', 'ck_order_items_amounts_non_negative',
    $c$CHECK (unit_price >= 0 AND line_discount >= 0 AND line_total >= 0)$c$);
SELECT pg_temp.add_constraint('pos.order_items', 'ck_order_items_discount_not_above_gross',
    $c$CHECK (line_discount <= quantity * unit_price)$c$);

-- ---- payments --------------------------------------------------------------
SELECT pg_temp.add_constraint('pos.payments', 'ck_payments_method',
    $c$CHECK (payment_method IN ('cash', 'card', 'e_wallet'))$c$);
SELECT pg_temp.add_constraint('pos.payments', 'ck_payments_status',
    $c$CHECK (payment_status IN ('paid', 'failed', 'refunded'))$c$);
SELECT pg_temp.add_constraint('pos.payments', 'ck_payments_amount_positive',
    $c$CHECK (amount > 0)$c$);

-- =============================================================================
-- 4. FOREIGN KEYS
-- ON DELETE RESTRICT everywhere: an OLTP system of record does not hard-delete
-- referenced rows (stores close, products deactivate, orders get cancelled).
-- =============================================================================
SELECT pg_temp.add_constraint('pos.areas', 'fk_areas_region',
    'FOREIGN KEY (region_id) REFERENCES pos.regions (region_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.stores', 'fk_stores_area',
    'FOREIGN KEY (area_id) REFERENCES pos.areas (area_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.products', 'fk_products_category',
    'FOREIGN KEY (category_id) REFERENCES pos.product_categories (category_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.customers', 'fk_customers_signup_store',
    'FOREIGN KEY (signup_store_id) REFERENCES pos.stores (store_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.orders', 'fk_orders_store',
    'FOREIGN KEY (store_id) REFERENCES pos.stores (store_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.orders', 'fk_orders_customer',
    'FOREIGN KEY (customer_id) REFERENCES pos.customers (customer_id) ON DELETE RESTRICT');   -- nullable: walk-in
SELECT pg_temp.add_constraint('pos.orders', 'fk_orders_promotion',
    'FOREIGN KEY (promotion_id) REFERENCES pos.promotions (promotion_id) ON DELETE RESTRICT'); -- nullable: no promo
SELECT pg_temp.add_constraint('pos.order_items', 'fk_order_items_order',
    'FOREIGN KEY (order_id) REFERENCES pos.orders (order_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.order_items', 'fk_order_items_product',
    'FOREIGN KEY (product_id) REFERENCES pos.products (product_id) ON DELETE RESTRICT');
SELECT pg_temp.add_constraint('pos.payments', 'fk_payments_order',
    'FOREIGN KEY (order_id) REFERENCES pos.orders (order_id) ON DELETE RESTRICT');

-- =============================================================================
-- 5. SUPPORTING INDEXES
-- PostgreSQL does not index foreign-key columns automatically. These keep
-- joins and FK checks fast, and the updated_at indexes support the Phase 2
-- incremental extract (WHERE updated_at >= :window_start AND < :window_end).
-- =============================================================================
CREATE INDEX IF NOT EXISTS ix_areas_region_id           ON pos.areas (region_id);
CREATE INDEX IF NOT EXISTS ix_stores_area_id            ON pos.stores (area_id);
CREATE INDEX IF NOT EXISTS ix_products_category_id      ON pos.products (category_id);
CREATE INDEX IF NOT EXISTS ix_customers_signup_store_id ON pos.customers (signup_store_id);
CREATE INDEX IF NOT EXISTS ix_orders_store_id_order_ts  ON pos.orders (store_id, order_ts);
CREATE INDEX IF NOT EXISTS ix_orders_customer_id        ON pos.orders (customer_id) WHERE customer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_orders_promotion_id       ON pos.orders (promotion_id) WHERE promotion_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_order_items_order_id      ON pos.order_items (order_id);
CREATE INDEX IF NOT EXISTS ix_order_items_product_id    ON pos.order_items (product_id);
CREATE INDEX IF NOT EXISTS ix_payments_order_id         ON pos.payments (order_id);

CREATE INDEX IF NOT EXISTS ix_stores_updated_at         ON pos.stores (updated_at);
CREATE INDEX IF NOT EXISTS ix_products_updated_at       ON pos.products (updated_at);
CREATE INDEX IF NOT EXISTS ix_customers_updated_at      ON pos.customers (updated_at);
CREATE INDEX IF NOT EXISTS ix_promotions_updated_at     ON pos.promotions (updated_at);
CREATE INDEX IF NOT EXISTS ix_orders_updated_at         ON pos.orders (updated_at);
CREATE INDEX IF NOT EXISTS ix_order_items_updated_at    ON pos.order_items (updated_at);
CREATE INDEX IF NOT EXISTS ix_payments_updated_at       ON pos.payments (updated_at);
