"""Testes do repositório de faixas de score e limite."""

from pathlib import Path

import pytest

from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.utils.exceptions import DadosIndisponiveisError

pytestmark = pytest.mark.unit


def test_le_todas_as_faixas_na_ordem_do_arquivo(repo_score_limite: ScoreLimiteRepository) -> None:
    faixas = repo_score_limite.listar_faixas()

    assert [(f.score_min, f.score_max) for f in faixas] == [
        (0, 299),
        (300, 499),
        (500, 699),
        (700, 849),
        (850, 1000),
    ]
    assert faixas[0].limite_maximo == 1000.0
    assert faixas[-1].limite_maximo == 30000.0


def test_faixas_sao_contiguas_e_cobrem_o_intervalo_completo(
    repo_score_limite: ScoreLimiteRepository,
) -> None:
    faixas = repo_score_limite.listar_faixas()

    assert faixas[0].score_min == 0
    assert faixas[-1].score_max == 1000
    for anterior, seguinte in zip(faixas, faixas[1:], strict=False):
        assert seguinte.score_min == anterior.score_max + 1


def test_base_ausente_levanta_dados_indisponiveis(tmp_path: Path) -> None:
    repo = ScoreLimiteRepository(tmp_path / "nao_existe.csv")

    with pytest.raises(DadosIndisponiveisError):
        repo.listar_faixas()
