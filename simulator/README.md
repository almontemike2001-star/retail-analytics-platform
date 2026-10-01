# BeanFlow synthetic POS simulator

Populates the PostgreSQL `pos` schema with **100% synthetic**, pattern-rich coffee-retail data.

```bash
cd simulator
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest                                             # unit tests, no database needed

python -m beanflow_sim.cli seed                     # master data + ~36k base members (once)
python -m beanflow_sim.cli backfill --days 90       # 90 business days ending yesterday
python -m beanflow_sim.cli daily --date 2026-10-01  # one more day (must be the next day)
python -m beanflow_sim.cli counts
python -m beanflow_sim.cli reset --yes              # TRUNCATE all pos tables (local dev)
```

Options: `--profile dev|test`, `--seed N` (or `BEANFLOW_SIM_SEED`), `--env-file PATH`.
Database settings come from `.env` (`POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`).

## Financial convention

All amounts are synthetic PHP values.

| Term | Definition | Source columns |
| --- | --- | --- |
| Menu price | Synthetic **VAT-exclusive** price | `products.base_price`; price charged at sale = `order_items.unit_price` |
| Gross sales | Before discounts and before tax | `SUM(order_items.quantity × unit_price)` |
| Discounts | Line-level (bundle promos) + order-level (percent / fixed promos) | `order_items.line_discount` + `orders.discount_amount` |
| Net sales | After discounts, before tax | `orders.subtotal − orders.discount_amount` (`subtotal` = sum of `line_total`, already net of line discounts) |
| Tax | 12% VAT on the discounted taxable amount, rounded to centavos | `orders.tax_amount = ROUND(0.12 × net sales, 2)` |
| Total | Amount the customer pays | `orders.total_amount = net sales + tax_amount` |

Completed orders are paid in full: the sum of `payments.amount` where `payment_status = 'paid'` equals `total_amount`. Sales KPIs downstream use **net sales** (excluding tax), as defined in the architecture.

## Time zone convention

Timestamps are stored as `TIMESTAMPTZ`, and the server runs in UTC. Business dates, hours and dayparts are always derived with an explicit `order_ts AT TIME ZONE 'Asia/Manila'`; the SQL in `sql/validate_patterns.sql` never relies on the session time zone.

## Rules

- Same seed → byte-identical data. Each business day has its own random stream, so a day is the same whether it was made by `backfill` or `daily`.
- `seed` runs once; a second run is skipped.
- Each day is one transaction (signups, orders, lines, payments, end-of-day changes).
- Days are generated in order with no gaps. Already-generated days are skipped; gaps and out-of-order days are rejected.
- All rows satisfy the Phase 1 constraints. Cross-table business defects are not injected here.

## Modules

| Module | Responsibility |
| --- | --- |
| `config.py` | Profiles, `.env` loading, accepted values (mirror of the DB CHECKs), timezone helpers |
| `reference_data.py` | Geography (4 regions, 12 areas) and menu (10 categories, 87 SKUs), in popularity order |
| `patterns.py` | Every business pattern: store-type behaviour, calendar effects, intraday curves, category mix by daypart |
| `randomness.py` | Per-day seeded generators; stable hash for latent traits (customer propensity, store performance) |
| `models.py` | Row types in exact table-column order (money in integer centavos) |
| `master_data.py` | Regions, areas, stores, categories, products, monthly promotion calendar |
| `customers.py` | Base members, daily signups, Pareto visit propensity, home-store customer sampling |
| `orders.py` | One business day of orders, lines, payments (vectorised sampling + per-order assembly) |
| `mutations.py` | End-of-day changes with historical `updated_at`: refunds, tier upgrades, store events, price/cost changes, next month's promos |
| `db.py` | Connections, COPY bulk loads, state loading, identity-sequence sync |
| `runner.py` | Seed and day orchestration, idempotency and chronology rules |
| `cli.py` | Command-line interface |

Pattern checks: `sql/validate_patterns.sql`.
