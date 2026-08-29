"""Fixtures compartilhadas. Nenhum teste toca `data/`: tudo roda sobre `tmp_path`."""

import shutil
from pathlib import Path

import pytest

from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def clientes_csv(tmp_path: Path) -> Path:
    """Cópia descartável da base de clientes."""
    destino = tmp_path / "clientes.csv"
    shutil.copy(FIXTURES / "clientes.csv", destino)
    return destino


@pytest.fixture
def score_limite_csv(tmp_path: Path) -> Path:
    """Cópia descartável das faixas de score."""
    destino = tmp_path / "score_limite.csv"
    shutil.copy(FIXTURES / "score_limite.csv", destino)
    return destino


@pytest.fixture
def solicitacoes_csv(tmp_path: Path) -> Path:
    """Caminho de um CSV de solicitações que ainda não existe."""
    return tmp_path / "solicitacoes_aumento_limite.csv"


@pytest.fixture
def repo_clientes(clientes_csv: Path) -> ClientesRepository:
    return ClientesRepository(clientes_csv)


@pytest.fixture
def repo_score_limite(score_limite_csv: Path) -> ScoreLimiteRepository:
    return ScoreLimiteRepository(score_limite_csv)


@pytest.fixture
def repo_solicitacoes(solicitacoes_csv: Path) -> SolicitacoesRepository:
    return SolicitacoesRepository(solicitacoes_csv)
