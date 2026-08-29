"""Testes do repositório de clientes."""

from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from banco_agil.repositories.base import ler_csv
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.utils.exceptions import ClienteNaoEncontradoError

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("entrada", ["52998224725", "529.982.247-25"])
def test_busca_aceita_cpf_com_e_sem_pontuacao(repo_clientes: ClientesRepository, entrada) -> None:
    cliente = repo_clientes.buscar_por_cpf(entrada)

    assert cliente is not None
    assert cliente.nome == "Helena Ribeiro Antunes"
    assert cliente.data_nascimento == date(1985, 3, 12)
    assert cliente.limite_atual == 5000.0
    assert cliente.score_atual == 730


def test_cpf_inexistente_retorna_none(repo_clientes: ClientesRepository) -> None:
    assert repo_clientes.buscar_por_cpf("00000000000") is None


def test_atualizar_score_persiste_e_devolve_registro(repo_clientes: ClientesRepository) -> None:
    atualizado = repo_clientes.atualizar_score("39053344705", 580)

    assert atualizado.score_atual == 580
    assert repo_clientes.buscar_por_cpf("39053344705").score_atual == 580


def test_atualizar_score_nao_altera_demais_linhas(
    repo_clientes: ClientesRepository, clientes_csv: Path
) -> None:
    antes = ler_csv(clientes_csv)
    repo_clientes.atualizar_score("39053344705", 580)
    depois = ler_csv(clientes_csv)

    assert len(depois) == len(antes)
    intocadas_antes = [linha for linha in antes if linha["cpf"] != "39053344705"]
    intocadas_depois = [linha for linha in depois if linha["cpf"] != "39053344705"]
    assert intocadas_depois == intocadas_antes


def test_atualizar_score_de_cpf_inexistente_levanta_erro(
    repo_clientes: ClientesRepository,
) -> None:
    with pytest.raises(ClienteNaoEncontradoError):
        repo_clientes.atualizar_score("00000000000", 500)


@pytest.mark.parametrize("score", [-1, 1001])
def test_score_fora_do_intervalo_e_barrado_pelo_modelo(
    repo_clientes: ClientesRepository, clientes_csv: Path, score: int
) -> None:
    antes = clientes_csv.read_text(encoding="utf-8")

    with pytest.raises(ValidationError):
        repo_clientes.atualizar_score("39053344705", score)

    assert clientes_csv.read_text(encoding="utf-8") == antes
