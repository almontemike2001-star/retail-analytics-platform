-- BeanFlow Coffee - source database bootstrap
-- Runs once when the PostgreSQL data volume is first created.

CREATE SCHEMA IF NOT EXISTS pos;

COMMENT ON SCHEMA pos IS 'BeanFlow synthetic POS source system (100% synthetic data)';

DO $$
BEGIN
    EXECUTE format(
        'ALTER DATABASE %I SET search_path TO pos, public',
        current_database()
    );
END
$$;
