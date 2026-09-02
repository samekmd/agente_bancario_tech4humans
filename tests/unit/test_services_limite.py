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
    conferir_aumento_real,
    conferir_valor_do_cliente,
    faixa_para_score,
    limite_maximo_permitido,
    processar_pedido_aumento,
    valor_para_nova_tentativa,
    valores_citados,
)
from banco_agil.utils.exceptions import (
    AumentoInvalidoError,
    DadosIndisponiveisError,
    ValorNaoInformadoError,
)

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


class TestValorParaNovaTentativa:
    """Só um pedido rejeitado merece ser reoferecido depois da entrevista."""

    def _pedido(self, status: StatusPedido) -> SolicitacaoAumento:
        return SolicitacaoAumento(
            cpf_cliente="39053344705",
            data_hora_solicitacao=datetime(2026, 8, 30, 10, 0),
            limite_atual=2500.0,
            novo_limite_solicitado=6000.0,
            status_pedido=status,
        )

    def test_pedido_rejeitado_devolve_o_valor(self) -> None:
        assert valor_para_nova_tentativa(self._pedido(StatusPedido.REJEITADO)) == 6000.0

    def test_pedido_aprovado_nao_se_reabre(self) -> None:
        assert valor_para_nova_tentativa(self._pedido(StatusPedido.APROVADO)) is None

    def test_pedido_pendente_nao_e_reoferecido(self) -> None:
        assert valor_para_nova_tentativa(self._pedido(StatusPedido.PENDENTE)) is None

    def test_sem_pedido_nao_ha_o_que_reoferecer(self) -> None:
        assert valor_para_nova_tentativa(None) is None


class TestValorPrecisaVirDoCliente:
    """O caso real: cliente disse só "Quero aumentar este limite" e o modelo pediu 25.000."""

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("quero 8000", {8000.0}),
            ("quero R$ 8.000,00", {8000.0}),
            ("de 20000 para 25000", {20000.0, 25000.0}),
            ("Quero aumentar este limite", set()),
            ("quero o dobro", set()),
            ("", set()),
        ],
    )
    def test_extrai_so_o_que_o_cliente_escreveu(self, texto: str, esperado: set) -> None:
        assert valores_citados([texto]) == esperado

    def test_aceita_valor_que_o_cliente_disse(self) -> None:
        assert conferir_valor_do_cliente(8000.0, ["quero aumentar para 8000"]) is None

    def test_aceita_valor_dito_em_mensagem_anterior(self) -> None:
        """O fluxo de confirmação: "quero 8000" ... "confirma?" ... "sim"."""
        assert conferir_valor_do_cliente(8000.0, ["quero 8000", "sim"]) is None

    def test_aceita_a_reoferta_confirmada(self) -> None:
        """Depois da entrevista o valor vem do estado, não da fala — é o fluxo do P5."""
        assert conferir_valor_do_cliente(6000.0, ["sim"], valor_pendente=6000.0) is None

    def test_recusa_valor_inventado(self) -> None:
        with pytest.raises(ValorNaoInformadoError):
            conferir_valor_do_cliente(25000.0, ["Quero aumentar este limite"])

    def test_valor_dito_pelo_sistema_nao_conta(self) -> None:
        """O 25.000 do caso real saiu do meio entre limite atual e teto, ambos do sistema."""
        with pytest.raises(ValorNaoInformadoError):
            conferir_valor_do_cliente(25000.0, ["oi", "quero aumentar este limite"])


class TestConferirAumentoReal:
    """Um aumento precisa aumentar.

    A avaliação compara o valor pedido com o teto da faixa de score e nunca com o limite
    que o cliente já tem. Sem esta guarda, Helena (limite R$ 5.000, score 730) pedindo
    R$ 100 recebia "aprovado" e a linha entrava no CSV como solicitação de aumento.
    """

    def test_valor_acima_do_limite_atual_passa(self) -> None:
        assert conferir_aumento_real(5000.01, 5000.0) is None

    @pytest.mark.parametrize("pedido", [4999.99, 100.0, 0.0])
    def test_valor_abaixo_do_limite_atual_e_recusado(self, pedido: float) -> None:
        with pytest.raises(AumentoInvalidoError):
            conferir_aumento_real(pedido, 5000.0)

    def test_valor_igual_ao_limite_atual_e_recusado(self) -> None:
        """Pedir o mesmo limite que já se tem não é aumento: a comparação é estrita."""
        with pytest.raises(AumentoInvalidoError):
            conferir_aumento_real(5000.0, 5000.0)

    def test_mensagem_cita_os_dois_valores(self) -> None:
        """O agente precisa dos números para verbalizar a pergunta ao cliente."""
        with pytest.raises(AumentoInvalidoError) as erro:
            conferir_aumento_real(100.0, 5000.0)

        assert "5000.00" in erro.value.mensagem
        assert "100.00" in erro.value.mensagem

    def test_cliente_sem_limite_pode_pedir_qualquer_valor(self) -> None:
        """Tiago tem limite R$ 0,00: qualquer pedido positivo é aumento genuíno."""
        assert conferir_aumento_real(1000.0, 0.0) is None


class TestPedidoQueNaoEAumento:
    def test_nao_grava_nada_no_csv(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
    ) -> None:
        """A recusa acontece antes do registro: o CSV não pode ganhar a linha."""
        cliente = repo_clientes.buscar_por_cpf("52998224725")

        with pytest.raises(AumentoInvalidoError):
            processar_pedido_aumento(
                cliente, 100.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes
            )

        assert repo_solicitacoes.listar_por_cpf(cliente.cpf) == []

    def test_tiago_pedindo_o_teto_da_faixa_continua_aprovado(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        faixas: list[FaixaLimite],
    ) -> None:
        """Score 0 e limite R$ 0,00: R$ 1.000 é o teto da faixa 0-299 e é aprovável.

        A validação nova não pode regredir a fronteira inclusiva da tabela de faixas.
        """
        cliente = repo_clientes.buscar_por_cpf("45130988302")

        pedido, avaliacao = processar_pedido_aumento(
            cliente, 1000.0, faixas=faixas, repo_solicitacoes=repo_solicitacoes
        )

        assert cliente.limite_atual == 0.0
        assert avaliacao.aprovado is True
        assert pedido.status_pedido is StatusPedido.APROVADO
