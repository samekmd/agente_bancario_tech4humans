"""Testes da regra de faixa de score e da decisão de aumento de limite."""

from datetime import datetime

import pytest

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import FaixaLimite, SolicitacaoAumento
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.services.limite import (
    avaliar_aumento,
    faixa_para_score,
    limite_maximo_permitido,
    processar_pedido_aumento,
)
from banco_agil.utils.exceptions import DadosIndisponiveisError

pytestmark = pytest.mark.unit


@pytest.fixture
def faixas(repo_score_limite: ScoreLimiteRepository) -> list[FaixaLimite]:
    return repo_score_limite.listar_faixas()


class TestFaixaParaScore:
    @pytest.mark.parametrize(
        ("score", "limite"),
        [
            (0, 1000.0),
            (299, 1000.0),
            (300, 3000.0),
            (499, 3000.0),
            (500, 8000.0),
            (699, 8000.0),
            (700, 15000.0),
            (849, 15000.0),
            (850, 30000.0),
            (1000, 30000.0),
        ],
    )
    def test_fronteiras_de_cada_faixa(
        self, faixas: list[FaixaLimite], score: int, limite: float
    ) -> None:
        assert limite_maximo_permitido(score, faixas) == limite

    def test_score_max_e_inclusivo(self, faixas: list[FaixaLimite]) -> None:
        assert faixa_para_score(299, faixas).score_max == 299
        assert faixa_para_score(300, faixas).score_min == 300

    @pytest.mark.parametrize("score", [-1, 1001])
    def test_score_fora_de_qualquer_faixa_levanta_erro(
        self, faixas: list[FaixaLimite], score: int
    ) -> None:
        with pytest.raises(DadosIndisponiveisError):
            faixa_para_score(score, faixas)

    def test_base_com_buraco_nao_engole_o_score(self) -> None:
        incompletas = [FaixaLimite(score_min=0, score_max=299, limite_maximo=1000.0)]

        with pytest.raises(DadosIndisponiveisError):
            faixa_para_score(500, incompletas)


class TestAvaliarAumento:
    def test_aprova_pedido_dentro_da_faixa(self, faixas: list[FaixaLimite]) -> None:
        resultado = avaliar_aumento(score=730, limite_solicitado=10000.0, faixas=faixas)

        assert resultado.aprovado is True
        assert resultado.status_pedido is StatusPedido.APROVADO
        assert resultado.limite_maximo == 15000.0

    def test_rejeita_pedido_acima_da_faixa(self, faixas: list[FaixaLimite]) -> None:
        resultado = avaliar_aumento(score=320, limite_solicitado=9000.0, faixas=faixas)

        assert resultado.aprovado is False
        assert resultado.status_pedido is StatusPedido.REJEITADO
        assert resultado.limite_maximo == 3000.0

    def test_score_alto_nao_aprova_pedido_acima_do_teto(self, faixas: list[FaixaLimite]) -> None:
        resultado = avaliar_aumento(score=910, limite_solicitado=50000.0, faixas=faixas)

        assert resultado.aprovado is False
        assert resultado.limite_maximo == 30000.0

    def test_pedido_exatamente_no_teto_e_aprovado(self, faixas: list[FaixaLimite]) -> None:
        assert avaliar_aumento(500, 8000.0, faixas=faixas).aprovado is True

    def test_um_centavo_acima_do_teto_e_rejeitado(self, faixas: list[FaixaLimite]) -> None:
        assert avaliar_aumento(500, 8000.01, faixas=faixas).aprovado is False

    def test_entrevista_muda_o_desfecho_do_mesmo_pedido(self, faixas: list[FaixaLimite]) -> None:
        """Cenário do seed: 470 rejeita 6000; após a entrevista, 580 aprova."""
        assert avaliar_aumento(470, 6000.0, faixas=faixas).aprovado is False
        assert avaliar_aumento(580, 6000.0, faixas=faixas).aprovado is True

    def test_le_as_faixas_do_repositorio_quando_nao_recebe_a_lista(
        self, repo_score_limite: ScoreLimiteRepository
    ) -> None:
        resultado = avaliar_aumento(730, 10000.0, repo=repo_score_limite)

        assert resultado.aprovado is True
        assert resultado.score_considerado == 730


class TestProcessarPedidoAumento:
    def test_registra_pendente_antes_de_decidir(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")
        vistos: list[StatusPedido] = []
        original = repo_solicitacoes.registrar

        def espiao(solicitacao: SolicitacaoAumento) -> SolicitacaoAumento:
            vistos.append(solicitacao.status_pedido)
            return original(solicitacao)

        monkeypatch.setattr(repo_solicitacoes, "registrar", espiao)
        processar_pedido_aumento(
            cliente, 6000.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes
        )

        assert vistos == [StatusPedido.PENDENTE]

    def test_linha_termina_com_o_status_da_decisao(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")

        pedido, avaliacao = processar_pedido_aumento(
            cliente, 6000.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes
        )

        assert avaliacao.aprovado is False
        assert pedido.status_pedido is StatusPedido.REJEITADO
        registradas = repo_solicitacoes.listar_por_cpf(cliente.cpf)
        assert [s.status_pedido for s in registradas] == [StatusPedido.REJEITADO]

    def test_pedido_aprovado_grava_aprovado(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("52998224725")

        pedido, avaliacao = processar_pedido_aumento(
            cliente, 10000.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes
        )

        assert avaliacao.aprovado is True
        assert pedido.status_pedido is StatusPedido.APROVADO

    def test_grava_o_limite_atual_do_cliente_na_linha(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")
        agora = datetime(2026, 8, 28, 17, 0)

        pedido, _ = processar_pedido_aumento(
            cliente, 6000.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes, agora=agora
        )

        assert pedido.limite_atual == cliente.limite_atual
        assert pedido.novo_limite_solicitado == 6000.0
        assert pedido.data_hora_solicitacao == agora
