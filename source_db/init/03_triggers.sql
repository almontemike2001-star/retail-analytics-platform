-- =============================================================================
-- BeanFlow Coffee - POS operational source system
-- 03_triggers.sql : automatic maintenance of updated_at
--
-- updated_at is the change-tracking column the Phase 2 extractor uses for
-- incremental loads, so it must move whenever a mutable row changes.
--
-- Behaviour of pos.set_updated_at() (BEFORE UPDATE, row level):
--   * Fires only when the row actually changed (WHEN OLD IS DISTINCT FROM NEW),
--     so no-op updates do not create false "changes" for the extractor.
--   * If the UPDATE does not touch updated_at, it is set to now()
--     (transaction start time).
--   * If the UPDATE explicitly sets a new updated_at value, that value is kept.
--     This lets the synthetic data simulator write historically-dated changes
--     during backfill (e.g. a refund that "happened" last March).
--   * INSERTs are not affected; the column DEFAULT now() applies unless the
--     writer supplies a value.
--
-- Attached only to tables that have updated_at. Static reference tables
-- (regions, areas, product_categories) have no updated_at and no trigger.
--
-- Rerunnable: CREATE OR REPLACE FUNCTION / CREATE OR REPLACE TRIGGER (PG14+).
-- =============================================================================

CREATE OR REPLACE FUNCTION pos.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.updated_at IS NOT DISTINCT FROM OLD.updated_at THEN
        NEW.updated_at := now();
    END IF;
    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION pos.set_updated_at() IS
    'BEFORE UPDATE trigger: sets updated_at = now() unless the statement explicitly set a new updated_at.';

-- ---- Attach to mutable tables -------------------------------------------------
CREATE OR REPLACE TRIGGER trg_stores_set_updated_at
    BEFORE UPDATE ON pos.stores
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_products_set_updated_at
    BEFORE UPDATE ON pos.products
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_customers_set_updated_at
    BEFORE UPDATE ON pos.customers
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_promotions_set_updated_at
    BEFORE UPDATE ON pos.promotions
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_orders_set_updated_at
    BEFORE UPDATE ON pos.orders
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_order_items_set_updated_at
    BEFORE UPDATE ON pos.order_items
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();

CREATE OR REPLACE TRIGGER trg_payments_set_updated_at
    BEFORE UPDATE ON pos.payments
    FOR EACH ROW WHEN (OLD.* IS DISTINCT FROM NEW.*)
    EXECUTE FUNCTION pos.set_updated_at();
