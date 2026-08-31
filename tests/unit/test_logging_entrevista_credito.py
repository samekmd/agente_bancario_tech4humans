"""Testes do rastro de log das tools, services e repositories.

Estes testes existem porque, sem log, uma falha inesperada dentro de uma tool vira
`{"ok": false}` genérico e desaparece — foi exatamente o que dificultou o diagnóstico.
"""

import logging
from datetime import datetime
from typing import Any

import pytest

from banco_agil.domain.enums import StatusPedido, TipoEmprego
from banco_agil.domain.models import Cliente, DadosEntrevista
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.services.entrevista import concluir_entrevista, registrar_slot
from banco_agil.services.limite import processar_pedido_aumento
from banco_agil.services.score import calcular_score
from banco_agil.tools.base import ERRO_INESPERADO, falha_de
from banco_agil.utils.exceptions import EntradaInvalidaError
from banco_agil.utils.logging import mascarar_cpf

pytestmark = pytest.mark.unit

COMPLETOS = {
    "renda_mensal": 8000.0,
    "despesas_mensais": 3000.0,
    "tipo_emprego": TipoEmprego.FORMAL,
    "num_dependentes": 0,
    "tem_dividas": False,
}


@pytest.fixture(autouse=True)
def captura(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.DEBUG, logger="banco_agil")
    return caplog


class TestMascararCpf:
    def test_nao_registra_o_documento_inteiro(self) -> None:
        mascarado = mascarar_cpf("39053344705")

        assert mascarado == "390.***.**7-05"
        assert "39053344705" not in mascarado

    @pytest.mark.parametrize("entrada", [None, "", "123"])
    def test_entrada_invalida_nao_quebra(self, entrada: Any) -> None:
        assert mascarar_cpf(entrada) in {"-", "***"}


class TestLogDaTool:
    def test_erro_inesperado_e_registrado_com_traceback(
        self, captura: pytest.LogCaptureFixture
    ) -> None:
        payload = falha_de(RuntimeError("coluna score_atual ausente"), "finalizar_entrevista")

        assert payload["erro"] == ERRO_INESPERADO
        registro = captura.records[-1]
        assert registro.levelno == logging.ERROR
        assert registro.exc_info is not None
        assert "finalizar_entrevista" in registro.getMessage()
        # O detalhe técnico fica no log, nunca no payload que o cliente lê.
        assert "coluna score_atual ausente" not in payload["erro"]

    def test_erro_de_dominio_e_registrado_sem_traceback(
        self, captura: pytest.LogCaptureFixture
    ) -> None:
        payload = falha_de(EntradaInvalidaError("Vínculo inválido."), "registrar_resposta")

        assert payload["erro"] == "Vínculo inválido."
        registro = captura.records[-1]
        assert registro.levelno == logging.WARNING
        assert registro.exc_info is None


class TestLogDaEntrevista:
    def test_valor_recusado_registra_o_que_chegou(self, captura: pytest.LogCaptureFixture) -> None:
        with pytest.raises(EntradaInvalidaError):
            registrar_slot({}, "tipo_emprego", "carteira assinada")

        texto = captura.text
        assert "carteira assinada" in texto
        assert "aceitos" in texto

    def test_score_registra_a_decomposicao_da_formula(
        self, captura: pytest.LogCaptureFixture
    ) -> None:
        calcular_score(DadosEntrevista(**COMPLETOS))

        texto = captura.text
        assert "emprego=300" in texto
        assert "dependentes=100" in texto
        assert "dividas=100" in texto
        assert "-> final 580" in texto

    def test_conclusao_registra_score_antes_e_depois(
        self, repo_clientes: ClientesRepository, captura: pytest.LogCaptureFixture
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")

        concluir_entrevista(cliente, COMPLETOS, repo=repo_clientes)

        texto = captura.text
        assert "DadosEntrevista criado" in texto
        assert "score 470 -> 580" in texto
        assert "melhorou" in texto
        assert "39053344705" not in texto

    def test_entrevista_incompleta_registra_o_campo_que_falta(
        self, repo_clientes: ClientesRepository, captura: pytest.LogCaptureFixture
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")

        with pytest.raises(EntradaInvalidaError):
            concluir_entrevista(cliente, {"renda_mensal": 8000.0}, repo=repo_clientes)

        assert "falta o campo despesas_mensais" in captura.text


class TestLogDoAumento:
    def test_registra_os_tres_passos_e_os_objetos(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        captura: pytest.LogCaptureFixture,
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")

        processar_pedido_aumento(
            cliente,
            6000.0,
            repo_solicitacoes=repo_solicitacoes,
            agora=datetime(2026, 8, 29, 15, 0),
        )

        texto = captura.text
        assert "[1/3] SolicitacaoAumento criada" in texto
        assert "[2/3] pedido gravado como pendente" in texto
        assert "[3/3] linha atualizada para rejeitado" in texto
        assert "ResultadoAvaliacao=" in texto
        assert "39053344705" not in texto

    def test_registra_a_gravacao_e_a_atualizacao_do_csv(
        self,
        repo_clientes: ClientesRepository,
        repo_solicitacoes: SolicitacoesRepository,
        captura: pytest.LogCaptureFixture,
    ) -> None:
        cliente = repo_clientes.buscar_por_cpf("52998224725")

        _, avaliacao = processar_pedido_aumento(
            cliente, 10000.0, repo_solicitacoes=repo_solicitacoes
        )

        assert avaliacao.status_pedido is StatusPedido.APROVADO
        texto = captura.text
        assert "criando arquivo com cabeçalho" in texto
        assert "atualizando status para aprovado" in texto
        assert "status persistido" in texto

    def test_solicitacao_perdida_registra_os_carimbos_do_arquivo(
        self, repo_solicitacoes: SolicitacoesRepository, captura: pytest.LogCaptureFixture
    ) -> None:
        cliente = Cliente(
            cpf="39053344705",
            nome="Beatriz Camargo Lopes",
            data_nascimento="1990-11-04",
            limite_atual=2500.0,
            score_atual=470,
        )
        processar_pedido_aumento(
            cliente, 6000.0, repo_solicitacoes=repo_solicitacoes, agora=datetime(2026, 8, 29, 15, 0)
        )
        captura.clear()

        with pytest.raises(Exception, match="solicitação"):
            repo_solicitacoes.atualizar_status(
                cliente.cpf, datetime(2020, 1, 1), StatusPedido.APROVADO
            )

        assert "carimbos no arquivo" in captura.text


class TestLogDasDemaisTools:
    """Autenticação, handoff, encerramento e câmbio também precisam deixar rastro."""

    def _chamar(self, ferramenta: Any, **kwargs: Any) -> Any:
        return ferramenta.invoke(
            {"args": kwargs, "name": ferramenta.name, "type": "tool_call", "id": "call-1"}
        )

    def test_autenticacao_registra_cpf_mascarado_e_nunca_o_documento(
        self, repo_clientes: ClientesRepository, captura: pytest.LogCaptureFixture
    ) -> None:
        from banco_agil.state import estado_inicial
        from banco_agil.tools.autenticacao import autenticar_cliente

        self._chamar(
            autenticar_cliente,
            cpf="390.533.447-05",
            data_nascimento="04/11/1990",
            state=estado_inicial(),
        )

        texto = captura.text
        assert "390.***.**7-05" in texto
        assert "39053344705" not in texto
        # A data de nascimento é credencial: junto com o CPF, não pode entrar no log.
        assert "04/11/1990" not in texto

    def test_autenticacao_falha_registra_motivo_e_tentativas(
        self, captura: pytest.LogCaptureFixture
    ) -> None:
        from banco_agil.state import estado_inicial
        from banco_agil.tools.autenticacao import autenticar_cliente

        self._chamar(
            autenticar_cliente,
            cpf="390.533.447-05",
            data_nascimento="01/01/1999",
            state={**estado_inicial(), "tentativas_auth": 2},
        )

        texto = captura.text
        assert "credenciais_incorretas" in texto
        assert "bloqueado=True" in texto

    def test_handoff_registra_o_destino(self, captura: pytest.LogCaptureFixture) -> None:
        from banco_agil.tools.handoff import transferir_para_cambio

        self._chamar(transferir_para_cambio)

        assert "handoff pedido para: cambio" in captura.text

    def test_encerramento_registra_o_motivo(self, captura: pytest.LogCaptureFixture) -> None:
        from banco_agil.tools.sistema import encerrar_atendimento

        self._chamar(encerrar_atendimento, motivo="cliente se despediu")

        assert "cliente se despediu" in captura.text

    def test_cambio_indisponivel_registra_a_falha_com_o_nome_da_tool(
        self, monkeypatch: pytest.MonkeyPatch, captura: pytest.LogCaptureFixture
    ) -> None:
        from banco_agil.tools.cambio import consultar_cotacao
        from banco_agil.utils.exceptions import CotacaoIndisponivelError

        def indisponivel(*a: Any, **k: Any) -> None:
            raise CotacaoIndisponivelError("Não consegui consultar a cotação agora.")

        monkeypatch.setattr("banco_agil.tools.cambio.obter_cotacao", indisponivel)
        self._chamar(consultar_cotacao, par="USD-BRL")

        assert "[consultar_cotacao]" in captura.text
