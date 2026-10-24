# Backend targets (recipe lines start with a TAB). Frontend targets live with the web/ app.
.PHONY: install api dev mock test eval fixtures spike openapi reset-db lint

install:
	cd api && uv sync

api dev:
	cd api && uv run uvicorn app.main:app --reload --port 8000

mock:
	cd api && MOCK_MODE=1 uv run uvicorn app.main:app --reload --port 8000

test:
	cd api && uv run pytest -q

eval:
	cd api && uv run python scripts/eval.py

fixtures:
	cd api && RECORD_FIXTURES=1 MOCK_MODE=0 uv run python scripts/record_fixtures.py

spike:
	cd api && MOCK_MODE=0 uv run python scripts/spike_tinyfish.py

openapi:
	cd api && uv run python scripts/export_openapi.py

lint:
	cd api && uv run ruff check .

reset-db:
	rm -f api/sunwai.db api/sunwai.db-shm api/sunwai.db-wal
