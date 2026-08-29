"""Testes das tools como adaptadores: payload, atualização de estado e erros.

As tools são exercitadas com os services trocados por dublês. O caminho de negócio já
tem cobertura em `test_services_*`; aqui o que importa é o contrato com o grafo.
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from banco_agil.domain.enums import Agente, MotivoFalhaAuth, StatusPedido, TipoEmprego
from banco_agil.domain.models import (
    Cliente,
    Cotacao,
    ResultadoAutenticacao,
    ResultadoAvaliacao,
    SolicitacaoAumento,
)
from banco_agil.state import estado_inicial
from banco_agil.tools import TOOLS_POR_AGENTE, tools_de
from banco_agil.tools.autenticacao import autenticar_cliente
from banco_agil.tools.base import ERRO_INESPERADO
from banco_agil.tools.cambio import consultar_cotacao, converter_valor
from banco_agil.tools.credito import consultar_limite, solicitar_aumento_limite
from banco_agil.tools.entrevista import finalizar_entrevista, registrar_resposta_entrevista
from banco_agil.tools.handoff import (
    transferir_para_cambio,
    transferir_para_credito,
    transferir_para_entrevista_credito,
    transferir_para_triagem,
)
from banco_agil.tools.sistema import encerrar_atendimento
from banco_agil.utils.exceptions import CotacaoIndisponivelError, EntradaInvalidaError

pytestmark = pytest.mark.unit

CLIENTE = Cliente(
    cpf="39053344705",
    nome="Beatriz Camargo Lopes",
    data_nascimento="1990-11-04",
    limite_atual=2500.0,
    score_atual=470,
)

COTACAO = Cotacao(
    par="USD-BRL",
    moeda_origem="USD",
    moeda_destino="BRL",
    compra=5.2,
    venda=5.21,
    atualizado_em=datetime(2026, 8, 28, 15, 51, tzinfo=UTC),
    fonte="AwesomeAPI",
)


def payload_de(comando: Command) -> dict[str, Any]:
    """Extrai o payload JSON da ToolMessage devolvida pela tool."""
    mensagem = comando.update["messages"][0]
    assert isinstance(mensagem, ToolMessage)
    return json.loads(mensagem.content)


def estado(**campos: Any) -> dict[str, Any]:
    return {**estado_inicial(), **campos}


def chamar(ferramenta, **kwargs: Any) -> Command:
    """Invoca a tool como o ToolNode faria: um ToolCall completo, com id."""
    return ferramenta.invoke(
        {"args": kwargs, "name": ferramenta.name, "type": "tool_call", "id": "call-1"}
    )


class TestContratoComum:
    @pytest.mark.parametrize(
        "agente", [Agente.TRIAGEM, Agente.CREDITO, Agente.ENTREVISTA_CREDITO, Agente.CAMBIO]
    )
    def test_toda_tool_responde_com_tool_message(self, agente: Agente) -> None:
        for ferramenta in tools_de(agente):
            assert "tool_call_id" in ferramenta.args_schema.model_fields

    def test_estado_e_tool_call_id_nao_aparecem_para_o_llm(self) -> None:
        assert list(autenticar_cliente.args) == ["cpf", "data_nascimento"]
        assert list(consultar_limite.args) == []

    def test_toda_tool_tem_docstring_em_portugues(self) -> None:
        for ferramentas in TOOLS_POR_AGENTE.values():
            for ferramenta in ferramentas:
                assert ferramenta.description.strip()


class TestEscopoPorBinding:
    def test_cambio_nao_alcanca_consultar_limite(self) -> None:
        nomes = [t.name for t in tools_de(Agente.CAMBIO)]

        assert "consultar_limite" not in nomes
        assert "solicitar_aumento_limite" not in nomes

    def test_triagem_nao_opera_credito_nem_cambio(self) -> None:
        nomes = [t.name for t in tools_de(Agente.TRIAGEM)]

        assert "consultar_limite" not in nomes
        assert "consultar_cotacao" not in nomes

    def test_so_a_triagem_autentica(self) -> None:
        for agente, ferramentas in TOOLS_POR_AGENTE.items():
            tem_auth = "autenticar_cliente" in [t.name for t in ferramentas]
            assert tem_auth is (agente is Agente.TRIAGEM)

    def test_encerrar_esta_em_todos_os_agentes(self) -> None:
        for ferramentas in TOOLS_POR_AGENTE.values():
            assert "encerrar_atendimento" in [t.name for t in ferramentas]

    def test_entrevista_so_e_alcancavel_a_partir_do_credito(self) -> None:
        origens = [
            agente
            for agente, ferramentas in TOOLS_POR_AGENTE.items()
            if "transferir_para_entrevista_credito" in [t.name for t in ferramentas]
        ]

        assert origens == [Agente.CREDITO]


class TestAutenticarCliente:
    def test_sucesso_grava_cliente_e_cpf_no_estado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "banco_agil.tools.autenticacao.autenticar",
            lambda *a, **k: ResultadoAutenticacao(
                autenticado=True, cliente=CLIENTE, tentativas=0, tentativas_restantes=3
            ),
        )

        comando = chamar(
            autenticar_cliente, cpf="390.533.447-05", data_nascimento="04/11/1990", state=estado()
        )

        assert payload_de(comando)["ok"] is True
        assert payload_de(comando)["primeiro_nome"] == "Beatriz"
        assert comando.update["autenticado"] is True
        assert comando.update["cliente"] == CLIENTE
        assert comando.update["cpf"] == "39053344705"

    def test_falha_atualiza_contador_e_nao_vaza_cliente(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "banco_agil.tools.autenticacao.autenticar",
            lambda *a, **k: ResultadoAutenticacao(
                autenticado=False,
                cliente=None,
                tentativas=2,
                tentativas_restantes=1,
                motivo=MotivoFalhaAuth.CREDENCIAIS_INCORRETAS,
            ),
        )

        comando = chamar(
            autenticar_cliente, cpf="390.533.447-05", data_nascimento="01/01/1999", state=estado()
        )
        payload = payload_de(comando)

        assert payload["ok"] is False
        assert payload["tentativas_restantes"] == 1
        assert comando.update["tentativas_auth"] == 2
        assert comando.update["encerrado"] is False
        assert "cliente" not in comando.update
        assert "nome" not in payload

    def test_terceira_falha_encerra_o_atendimento(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "banco_agil.tools.autenticacao.autenticar",
            lambda *a, **k: ResultadoAutenticacao(
                autenticado=False,
                tentativas=3,
                tentativas_restantes=0,
                bloqueado=True,
                motivo=MotivoFalhaAuth.CREDENCIAIS_INCORRETAS,
            ),
        )

        comando = chamar(
            autenticar_cliente, cpf="390.533.447-05", data_nascimento="01/01/1999", state=estado()
        )

        assert payload_de(comando)["bloqueado"] is True
        assert comando.update["encerrado"] is True

    def test_passa_o_contador_do_estado_para_o_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        recebidos: dict[str, Any] = {}

        def espiao(cpf: str, data: str, tentativas_atuais: int = 0) -> ResultadoAutenticacao:
            recebidos["tentativas_atuais"] = tentativas_atuais
            return ResultadoAutenticacao(autenticado=False, tentativas=3, tentativas_restantes=0)

        monkeypatch.setattr("banco_agil.tools.autenticacao.autenticar", espiao)
        chamar(
            autenticar_cliente,
            cpf="x",
            data_nascimento="y",
            state=estado(tentativas_auth=2),
        )

        assert recebidos["tentativas_atuais"] == 2


class TestCredito:
    def test_consulta_exige_cliente_no_estado(self) -> None:
        comando = chamar(consultar_limite, state=estado())
        payload = payload_de(comando)

        assert payload["ok"] is False
        assert comando.update["ultimo_erro"] == payload["erro"]

    def test_consulta_devolve_limite_score_e_teto(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "banco_agil.tools.credito.limite_maximo_permitido", lambda *a, **k: 3000.0
        )

        payload = payload_de(chamar(consultar_limite, state=estado(cliente=CLIENTE)))

        assert payload == {
            "ok": True,
            "limite_atual": 2500.0,
            "score_atual": 470,
            "limite_maximo_permitido": 3000.0,
        }

    def test_pedido_rejeitado_guarda_solicitacao_no_estado(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pedido = SolicitacaoAumento(
            cpf_cliente=CLIENTE.cpf,
            data_hora_solicitacao=datetime(2026, 8, 28, 17, 0),
            limite_atual=2500.0,
            novo_limite_solicitado=6000.0,
            status_pedido=StatusPedido.REJEITADO,
        )
        avaliacao = ResultadoAvaliacao(
            aprovado=False,
            status_pedido=StatusPedido.REJEITADO,
            score_considerado=470,
            limite_maximo=3000.0,
            limite_solicitado=6000.0,
        )
        monkeypatch.setattr(
            "banco_agil.tools.credito.processar_pedido_aumento",
            lambda *a, **k: (pedido, avaliacao),
        )

        comando = chamar(
            solicitar_aumento_limite, novo_limite="R$ 6.000,00", state=estado(cliente=CLIENTE)
        )
        payload = payload_de(comando)

        assert payload["aprovado"] is False
        assert payload["limite_maximo_permitido"] == 3000.0
        assert comando.update["solicitacao_atual"] == pedido

    def test_valor_ilegivel_nao_chega_ao_service(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def nao_deveria(*a: Any, **k: Any) -> None:
            raise AssertionError("o service não deveria ser chamado")

        monkeypatch.setattr("banco_agil.tools.credito.processar_pedido_aumento", nao_deveria)

        payload = payload_de(
            chamar(solicitar_aumento_limite, novo_limite="bastante", state=estado(cliente=CLIENTE))
        )

        assert payload["ok"] is False


class TestEntrevista:
    def test_registra_slot_e_aponta_o_proximo_campo(self) -> None:
        comando = chamar(
            registrar_resposta_entrevista, campo="renda_mensal", valor="8000", state=estado()
        )
        payload = payload_de(comando)

        assert payload["ok"] is True
        assert payload["proximo_campo"] == "despesas_mensais"
        assert payload["entrevista_completa"] is False
        assert comando.update["entrevista_slots"] == {"renda_mensal": 8000.0}

    def test_ultimo_campo_marca_entrevista_completa(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
        }

        payload = payload_de(
            chamar(
                registrar_resposta_entrevista,
                campo="tem_dividas",
                valor="não",
                state=estado(entrevista_slots=slots),
            )
        )

        assert payload["entrevista_completa"] is True
        assert payload["proximo_campo"] is None
        assert payload["campos_pendentes"] == []

    def test_valor_invalido_vira_erro_tratado(self) -> None:
        comando = chamar(
            registrar_resposta_entrevista, campo="tipo_emprego", valor="empresário", state=estado()
        )

        assert payload_de(comando)["ok"] is False
        assert "entrevista_slots" not in comando.update

    def test_finalizar_incrementa_o_contador_de_entrevistas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        atualizado = CLIENTE.model_copy(update={"score_atual": 580})
        monkeypatch.setattr(
            "banco_agil.tools.entrevista.concluir_entrevista", lambda *a, **k: atualizado
        )

        comando = chamar(finalizar_entrevista, state=estado(cliente=CLIENTE))
        payload = payload_de(comando)

        assert payload["score_anterior"] == 470
        assert payload["score_novo"] == 580
        assert payload["melhorou"] is True
        assert comando.update["cliente"] == atualizado
        assert comando.update["entrevistas_realizadas"] == 1

    def test_finalizar_sem_todos_os_campos_falha_sem_levantar(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def incompleta(*a: Any, **k: Any) -> None:
            raise EntradaInvalidaError("A entrevista ainda não tem o campo tem_dividas.")

        monkeypatch.setattr("banco_agil.tools.entrevista.concluir_entrevista", incompleta)

        comando = chamar(finalizar_entrevista, state=estado(cliente=CLIENTE))

        assert payload_de(comando)["erro"] == "A entrevista ainda não tem o campo tem_dividas."
        assert "cliente" not in comando.update


class TestCambio:
    def test_cotacao_devolve_compra_venda_e_fonte(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("banco_agil.tools.cambio.obter_cotacao", lambda *a, **k: COTACAO)

        payload = payload_de(chamar(consultar_cotacao, par="USD-BRL"))

        assert payload["compra"] == 5.2
        assert payload["venda"] == 5.21
        assert payload["fonte"] == "AwesomeAPI"

    def test_fonte_fora_do_ar_vira_erro_verbalizavel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def indisponivel(*a: Any, **k: Any) -> None:
            raise CotacaoIndisponivelError("Não consegui consultar a cotação de USD-BRL agora.")

        monkeypatch.setattr("banco_agil.tools.cambio.obter_cotacao", indisponivel)

        comando = chamar(consultar_cotacao, par="USD-BRL")
        payload = payload_de(comando)

        assert payload["ok"] is False
        assert payload["erro"] == "Não consegui consultar a cotação de USD-BRL agora."
        assert comando.update["ultimo_erro"] == payload["erro"]

    def test_erro_inesperado_nao_vaza_detalhe_tecnico(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def explode(*a: Any, **k: Any) -> None:
            raise RuntimeError("connection reset by peer em 10.0.0.42")

        monkeypatch.setattr("banco_agil.tools.cambio.obter_cotacao", explode)

        payload = payload_de(chamar(consultar_cotacao, par="USD-BRL"))

        assert payload["erro"] == ERRO_INESPERADO
        assert "10.0.0.42" not in json.dumps(payload)

    def test_conversao_devolve_valor_e_taxa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "banco_agil.tools.cambio.converter_entre_moedas", lambda *a, **k: (520.0, COTACAO)
        )

        payload = payload_de(
            chamar(converter_valor, valor="R$ 100,00", de_moeda="usd", para_moeda="brl")
        )

        assert payload["valor_convertido"] == 520.0
        assert payload["de_moeda"] == "USD"
        assert payload["par_consultado"] == "USD-BRL"


class TestHandoff:
    @pytest.mark.parametrize(
        ("ferramenta", "destino"),
        [
            (transferir_para_credito, Agente.CREDITO),
            (transferir_para_entrevista_credito, Agente.ENTREVISTA_CREDITO),
            (transferir_para_cambio, Agente.CAMBIO),
            (transferir_para_triagem, Agente.TRIAGEM),
        ],
    )
    def test_salta_para_o_no_do_agente_no_grafo_pai(self, ferramenta, destino: Agente) -> None:
        comando = chamar(ferramenta)

        assert comando.goto == destino.value
        assert comando.graph == Command.PARENT
        assert comando.update["agente_atual"] is destino

    def test_handoff_nao_encerra_o_atendimento(self) -> None:
        comando = chamar(transferir_para_credito)

        assert comando.update.get("encerrado") is None
        assert comando.goto

    def test_nome_do_no_e_o_valor_do_enum(self) -> None:
        """O grafo da Fase 4 precisa nomear os nós exatamente assim."""
        assert chamar(transferir_para_entrevista_credito).goto == "entrevista_credito"


class TestSistema:
    def test_encerrar_marca_o_estado(self) -> None:
        comando = chamar(encerrar_atendimento, motivo="cliente se despediu")
        payload = payload_de(comando)

        assert payload["ok"] is True
        assert payload["motivo"] == "cliente se despediu"
        assert comando.update["encerrado"] is True

    def test_encerrar_nao_salta_de_no(self) -> None:
        # `Command.goto` vazio é a tupla `()`, não `None`.
        assert not chamar(encerrar_atendimento, motivo="fim").goto
