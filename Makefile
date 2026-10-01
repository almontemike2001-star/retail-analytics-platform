COMPOSE := docker compose

.PHONY: up down logs ps check-env

check-env:
	@test -f .env || { echo "Missing .env - run: cp .env.example .env"; exit 1; }
	@! grep -q '^POSTGRES_PASSWORD=CHANGE_ME$$' .env || { echo "Set a real POSTGRES_PASSWORD in .env"; exit 1; }

up: check-env
	$(COMPOSE) up -d --wait

down: check-env
	$(COMPOSE) down

logs: check-env
	$(COMPOSE) logs -f --tail=100

ps: check-env
	$(COMPOSE) ps
