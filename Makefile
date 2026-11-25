.PHONY: up down logs test

up:
	docker compose up --build -d
	@echo "Frontend: http://localhost:3000   Backend: http://localhost:8000/health"

down:
	docker compose down

logs:
	docker compose logs -f

test:
	cd backend && pip install -r requirements-dev.txt && python -m pytest -q
