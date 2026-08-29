.PHONY: install run test lint format reset-data

install:
	uv sync --all-extras

run:
	uv run streamlit run app.py

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

reset-data:
	cp data/seed/clientes.csv data/clientes.csv
	cp data/seed/score_limite.csv data/score_limite.csv
	rm -f data/solicitacoes_aumento_limite.csv
