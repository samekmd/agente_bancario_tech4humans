"""Testes do contexto determinístico que cada agente injeta no prompt do turno."""

from datetime import datetime
from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from banco_agil.agents import credito, entrevista
from banco_agil.domain.enums import StatusPedido, TipoEmprego
from banco_agil.domain.models import Cliente, SolicitacaoAumento
from banco_agil.state import estado_inicial

pytestmark = pytest.mark.unit


def estado(**campos: Any) -> dict[str, Any]:
    return {**estado_inicial(), **campos}


class TestContextoDaEntrevista:
    def test_oferece_as_tres_opcoes_de_vinculo_na_pergunta(self) -> None:
        slots = {"renda_mensal": 8000.0, "despesas_mensais": 3000.0}

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS: formal, autônomo ou desempregado." in texto
        assert "escolher uma delas" in texto
        assert "`tipo_emprego`" in texto

    def test_oferece_as_opcoes_de_dividas(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
        }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS: sim ou não." in texto

    @pytest.mark.parametrize("campo", ["renda_mensal", "num_dependentes"])
    def test_campo_aberto_nao_lista_opcoes(self, campo: str) -> None:
        slots: dict[str, Any] = {}
        if campo == "num_dependentes":
            slots = {
                "renda_mensal": 8000.0,
                "despesas_mensais": 3000.0,
                "tipo_emprego": TipoEmprego.FORMAL,
            }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS" not in texto

    def test_pergunta_de_dependentes_pede_numero(self) -> None:
        """A pergunta e o validador andam juntos: quem só aceita número, pede número."""
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
        }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "`num_dependentes`" in texto
        assert "número" in texto
        assert "0" in texto

    def test_indica_a_posicao_da_pergunta(self) -> None:
        slots = {"renda_mensal": 8000.0, "despesas_mensais": 3000.0}

        assert "(3 de 5)" in entrevista.contexto(estado(entrevista_slots=slots))

    def test_entrevista_completa_manda_finalizar(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
            "tem_dividas": False,
        }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "finalizar_entrevista" in texto
        assert "RESPOSTAS ACEITAS" not in texto


CLIENTE = Cliente(
    cpf="39053344705",
    nome="Beatriz Camargo Lopes",
    data_nascimento="1990-11-04",
    limite_atual=2500.0,
    score_atual=580,
)


def _pedido(status: StatusPedido) -> SolicitacaoAumento:
    return SolicitacaoAumento(
        cpf_cliente=CLIENTE.cpf,
        data_hora_solicitacao=datetime(2026, 8, 29, 17, 0),
        limite_atual=2500.0,
        novo_limite_solicitado=6000.0,
        status_pedido=status,
    )


class TestContextoDoCredito:
    def test_pedido_aprovado_avisa_que_o_limite_em_vigor_nao_mudou(self) -> None:
        st = estado(cliente=CLIENTE, solicitacao_atual=_pedido(StatusPedido.APROVADO))

        texto = credito.contexto(st)

        assert "aprovado" in texto
        assert "limite em vigor continua sendo R$ 2500.00" in texto
        assert "nunca que ele já está valendo" in texto

    def test_pedido_rejeitado_nao_fala_de_limite_em_vigor(self) -> None:
        st = estado(cliente=CLIENTE, solicitacao_atual=_pedido(StatusPedido.REJEITADO))

        texto = credito.contexto(st)

        assert "limite em vigor" not in texto
        assert "entrevista ainda está disponível" in texto


class TestMiddlewareCampoPerguntado:
    """O middleware é o que registra, de forma determinística, que a pergunta foi feita."""

    def _rodar(self, ultima: Any, **campos: Any) -> dict[str, Any] | None:
        st = estado(messages=[HumanMessage(content="oi"), ultima], **campos)
        return entrevista.marcar_campo_perguntado.after_model(st, None)

    def test_resposta_em_texto_marca_o_campo_da_vez(self) -> None:
        assert self._rodar(AIMessage(content="Qual é a sua renda mensal?")) == {
            "entrevista_campo_perguntado": "renda_mensal"
        }

    def test_resposta_com_tool_call_nao_marca_nada(self) -> None:
        chamada = AIMessage(
            content="",
            tool_calls=[{"name": "registrar_resposta_entrevista", "args": {}, "id": "c1"}],
        )

        assert self._rodar(chamada) is None

    def test_marca_o_proximo_campo_pendente(self) -> None:
        slots = {"renda_mensal": 8000.0, "despesas_mensais": 3000.0}

        resultado = self._rodar(AIMessage(content="Qual seu vínculo?"), entrevista_slots=slots)

        assert resultado == {"entrevista_campo_perguntado": "tipo_emprego"}

    def test_entrevista_completa_nao_marca_campo(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
            "tem_dividas": False,
        }

        resultado = self._rodar(AIMessage(content="Análise atualizada."), entrevista_slots=slots)

        assert resultado == {"entrevista_campo_perguntado": None}


class TestContextoReofertaDoValor:
    def test_oferece_o_valor_pedido_antes_da_entrevista(self) -> None:
        st = estado(
            cliente=CLIENTE,
            entrevistas_realizadas=1,
            limite_pendente_reavaliacao=6000.0,
        )

        texto = credito.contexto(st)

        assert "R$ 6000.00 antes da entrevista" in texto
        assert "não pergunte o valor do zero" in texto
        assert "depois que ele confirmar" in texto

    def test_sem_valor_pendente_nao_reoferece(self) -> None:
        st = estado(cliente=CLIENTE, entrevistas_realizadas=1)

        assert "antes da entrevista" not in credito.contexto(st)
