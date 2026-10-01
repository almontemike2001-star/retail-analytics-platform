COMPOSE := docker compose
PY ?= $(CURDIR)/simulator/.venv/bin/python
MODE ?= run

.PHONY: up down logs ps check-env dev-bootstrap dev-loop dev-reset test

check-env:
	@test -f .env || { echo "Missing .env - run: cp .env.example .env  (then set POSTGRES_PASSWORD)"; exit 1; }
	@! grep -q '^POSTGRES_PASSWORD=CHANGE_ME$$' .env || { echo "Set a real POSTGRES_PASSWORD in .env (placeholder CHANGE_ME found)"; exit 1; }

## Start PostgreSQL in the background and wait until it is healthy
up: check-env
	$(COMPOSE) up -d --wait

## Stop and remove containers (data volume is kept)
down: check-env
	$(COMPOSE) down

## Follow service logs
logs: check-env
	$(COMPOSE) logs -f --tail=100

## Show service status and health
ps: check-env
	$(COMPOSE) ps

## Seed the simulator and bootstrap ingestion as of START-1:  make dev-bootstrap START=2026-07-03 [MODE=extract]
dev-bootstrap: check-env
	@test -n "$(START)" || { echo "usage: make dev-bootstrap START=YYYY-MM-DD"; exit 2; }
	$(PY) -m beanflow_sim.cli seed --start-date $(START)
	$(PY) -m beanflow_ingest.cli bootstrap $(if $(filter extract,$(MODE)),--no-load,) --as-of $$($(PY) -c 'import sys,datetime as d; print(d.date.fromisoformat(sys.argv[1]) - d.timedelta(days=1))' $(START))

## Simulate -> ingest, one day at a time:  make dev-loop START=2026-07-03 DAYS=7 [MODE=extract]
dev-loop: check-env
	@test -n "$(START)" -a -n "$(DAYS)" || { echo "usage: make dev-loop START=YYYY-MM-DD DAYS=N [MODE=run|extract]"; exit 2; }
	PYTHON=$(PY) bash scripts/dev_loop.sh $(START) $(DAYS) $(MODE)

## DESTRUCTIVE: wipe source data, landing files, audit log and Bronze tables:  make dev-reset CONFIRM=yes
dev-reset: check-env
	@test "$(CONFIRM)" = "yes" || { echo "Refusing: this deletes Postgres pos data, data/landing, the audit log and Bronze tables. Re-run with CONFIRM=yes"; exit 2; }
	$(PY) -m beanflow_sim.cli reset --yes
	$(PY) -m beanflow_ingest.cli reset-dev --yes

## Unit tests (no live GCP; Postgres integration tests run when the database is reachable)
test:
	cd simulator && $(PY) -m pytest
	cd ingestion && $(PY) -m pytest
