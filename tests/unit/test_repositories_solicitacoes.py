"""Testes do repositório de solicitações de aumento de limite."""

from datetime import datetime
from pathlib import Path

import pytest

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import SolicitacaoAumento
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.utils.exceptions import SolicitacaoNaoEncontradaError

pytestmark = pytest.mark.unit

CABECALHO = "cpf_cliente,data_hora_solicitacao,limite_atual,novo_limite_solicitado,status_pedido"


def _solicitacao(
    cpf: str = "39053344705",
    quando: datetime | None = None,
    novo_limite: float = 6000.0,
) -> SolicitacaoAumento:
    return SolicitacaoAumento(
        cpf_cliente=cpf,
        data_hora_solicitacao=quando or datetime(2026, 8, 28, 14, 0),
        limite_atual=2500.0,
        novo_limite_solicitado=novo_limite,
    )


def test_primeira_escrita_cria_arquivo_com_cabecalho_do_contrato(
    repo_solicitacoes: SolicitacoesRepository, solicitacoes_csv: Path
) -> None:
    repo_solicitacoes.registrar(_solicitacao())

    assert solicitacoes_csv.read_text(encoding="utf-8").splitlines()[0] == CABECALHO


def test_pedido_nasce_pendente(
    repo_solicitacoes: SolicitacoesRepository, solicitacoes_csv: Path
) -> None:
    repo_solicitacoes.registrar(_solicitacao())

    registradas = repo_solicitacoes.listar_por_cpf("39053344705")
    assert len(registradas) == 1
    assert registradas[0].status_pedido is StatusPedido.PENDENTE


def test_atualizar_status_altera_somente_a_linha_alvo(
    repo_solicitacoes: SolicitacoesRepository,
) -> None:
    alvo = datetime(2026, 8, 28, 14, 0)
    outra = datetime(2026, 8, 28, 15, 30)
    repo_solicitacoes.registrar(_solicitacao(quando=alvo))
    repo_solicitacoes.registrar(_solicitacao(quando=outra, novo_limite=9000.0))

    atualizada = repo_solicitacoes.atualizar_status("39053344705", alvo, StatusPedido.APROVADO)

    assert atualizada.status_pedido is StatusPedido.APROVADO
    registradas = repo_solicitacoes.listar_por_cpf("39053344705")
    por_data = {s.data_hora_solicitacao: s.status_pedido for s in registradas}
    assert por_data == {alvo: StatusPedido.APROVADO, outra: StatusPedido.PENDENTE}


def test_atualizar_status_de_pedido_inexistente_levanta_erro(
    repo_solicitacoes: SolicitacoesRepository,
) -> None:
    repo_solicitacoes.registrar(_solicitacao())

    with pytest.raises(SolicitacaoNaoEncontradaError):
        repo_solicitacoes.atualizar_status(
            "39053344705", datetime(2020, 1, 1, 0, 0), StatusPedido.APROVADO
        )


def test_listar_por_cpf_nao_vaza_outros_clientes(
    repo_solicitacoes: SolicitacoesRepository,
) -> None:
    repo_solicitacoes.registrar(_solicitacao(cpf="39053344705"))
    repo_solicitacoes.registrar(_solicitacao(cpf="11144477735"))

    assert [s.cpf_cliente for s in repo_solicitacoes.listar_por_cpf("39053344705")] == [
        "39053344705"
    ]


def test_listar_por_cpf_com_arquivo_ausente_retorna_vazio(
    repo_solicitacoes: SolicitacoesRepository,
) -> None:
    assert repo_solicitacoes.listar_por_cpf("39053344705") == []
