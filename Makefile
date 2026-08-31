.PHONY: install run test lint format reset-data grafo mlflow

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

# Redesenha docs/grafo.png. A chave só precisa existir para instanciar o modelo; o
# desenho não chama o Groq.
grafo:
	GROQ_API_KEY=$${GROQ_API_KEY:-placeholder} \
		uv run python -c "from banco_agil.graph import exportar_grafo; print(exportar_grafo())"

# Sobe o servidor do MLflow. Os traces só aparecem no UI com ele de pé; sem ele a
# aplicação funciona igual, apenas sem observabilidade.
mlflow:
	uv run mlflow server --host 127.0.0.1 --port 5000
