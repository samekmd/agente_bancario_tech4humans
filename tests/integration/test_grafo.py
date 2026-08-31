"""Testes do grafo: roteamento determinístico, handoff e ciclo crédito/entrevista."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from banco_agil.domain.enums import Agente
from banco_agil.graph import build_graph, config_execucao
from banco_agil.state import estado_inicial
from tests.integration.conftest import chama, fala, roteiro

pytestmark = pytest.mark.integration

CPF = "390.533.447-05"
NASCIMENTO = "04/11/1990"


def conversar(grafo: Any, texto: str, thread: str = "t1", primeira: bool = True) -> dict[str, Any]:
    """Uma invocação do grafo, como a UI faria: uma por mensagem do usuário."""
    entrada = {"messages": [HumanMessage(content=texto)]}
    if primeira:
        entrada = {**estado_inicial(), **entrada}
    return grafo.invoke(entrada, config=config_execucao(thread))


def orfas(estado: dict[str, Any]) -> list[str]:
    """ToolMessages sem a AIMessage que as originou — histórico que o Groq rejeita."""
    ids_chamados = {
        chamada["id"]
        for msg in estado["messages"]
        for chamada in (getattr(msg, "tool_calls", None) or [])
    }
    return [
        msg.tool_call_id
        for msg in estado["messages"]
        if isinstance(msg, ToolMessage) and msg.tool_call_id not in ids_chamados
    ]


class TestAutenticacao:
    def test_autentica_e_cumprimenta(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}),
                fala("Olá, Beatriz! Como posso ajudar?"),
            )
        )

        estado = conversar(grafo, f"oi, meu cpf é {CPF} e nasci em {NASCIMENTO}")

        assert estado["autenticado"] is True
        assert estado["cliente"].nome == "Beatriz Camargo Lopes"
        assert estado["agente_atual"] is Agente.TRIAGEM
        assert estado["messages"][-1].content == "Olá, Beatriz! Como posso ajudar?"
        assert orfas(estado) == []

    def test_tres_falhas_encerram_o_atendimento(self) -> None:
        errado = {"cpf": CPF, "data_nascimento": "01/01/1999"}
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", errado, "c1"),
                fala("Os dados não conferem. Restam 2 tentativas."),
                chama("autenticar_cliente", errado, "c2"),
                fala("Ainda não confere. Resta 1 tentativa."),
                chama("autenticar_cliente", errado, "c3"),
                fala("Não consegui confirmar sua identidade. Procure um canal oficial."),
            )
        )

        for _ in range(3):
            estado = conversar(grafo, "meus dados", primeira=_ == 0)

        assert estado["tentativas_auth"] == 3
        assert estado["encerrado"] is True
        assert orfas(estado) == []

    def test_contador_vem_do_estado_e_nao_das_mensagens(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": "01/01/1999"}),
                fala("Não confere."),
            )
        )

        estado = conversar(grafo, "meus dados")

        assert estado["tentativas_auth"] == 1
        assert estado["encerrado"] is False


class TestHandoff:
    def test_credito_responde_na_mesma_invocacao(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá, Beatriz!"),
                chama("transferir_para_credito", {}, "c2"),
                chama("consultar_limite", {}, "c3"),
                fala("Seu limite hoje é R$ 2.500,00."),
            )
        )
        conversar(grafo, "oi, sou a Beatriz")

        estado = conversar(grafo, "quero ver meu limite", primeira=False)

        assert estado["agente_atual"] is Agente.CREDITO
        assert estado["messages"][-1].content == "Seu limite hoje é R$ 2.500,00."

    def test_triagem_nao_anuncia_a_transferencia(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá!"),
                chama("transferir_para_credito", {}, "c2"),
                fala("Seu limite é R$ 2.500,00."),
            )
        )
        conversar(grafo, "oi")

        estado = conversar(grafo, "meu limite", primeira=False)

        conversa = [m.content for m in estado["messages"] if isinstance(m, AIMessage) and m.content]
        assert not any("transfer" in c.lower() or "aguarde" in c.lower() for c in conversa)

    def test_handoff_nao_deixa_tool_message_orfa(self) -> None:
        """O motivo de o handoff não usar `Command(graph=Command.PARENT)`."""
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá!"),
                chama("transferir_para_credito", {}, "c2"),
                fala("Seu limite é R$ 2.500,00."),
            )
        )
        conversar(grafo, "oi")
        estado = conversar(grafo, "meu limite", primeira=False)

        assert orfas(estado) == []

    def test_retoma_no_agente_atual_na_mensagem_seguinte(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá!"),
                chama("transferir_para_credito", {}, "c2"),
                fala("Seu limite é R$ 2.500,00."),
                fala("Posso ajudar com mais alguma coisa no seu limite?"),
            )
        )
        conversar(grafo, "oi")
        conversar(grafo, "meu limite", primeira=False)

        estado = conversar(grafo, "e sobre o limite?", primeira=False)

        assert estado["agente_atual"] is Agente.CREDITO
        assert estado["messages"][-1].content.startswith("Posso ajudar")


class TestGuardaDeAutenticacao:
    def test_sem_autenticar_o_controle_volta_para_a_triagem(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("transferir_para_credito", {}, "c1"),
                fala("Antes preciso confirmar seus dados. Qual seu CPF e data de nascimento?"),
            )
        )

        estado = conversar(grafo, "quero aumentar meu limite")

        assert estado["autenticado"] is False
        assert estado["messages"][-1].content.startswith("Antes preciso")


class TestCicloCreditoEntrevista:
    def test_rejeitado_vira_aprovado_depois_da_entrevista(self) -> None:
        """O ciclo inteiro, com a entrevista perguntando antes de registrar cada campo."""
        respostas = [
            chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
            fala("Olá, Beatriz!"),
            chama("transferir_para_credito", {}, "c2"),
            chama("solicitar_aumento_limite", {"novo_limite": "6000"}, "c3"),
            fala("Não consegui aprovar esse valor. Quer responder cinco perguntas?"),
            chama("transferir_para_entrevista_credito", {}, "c4"),
            fala("Qual é a sua renda mensal?"),
        ]
        # Cada campo exige um turno: o agente pergunta, o cliente responde, aí registra.
        campos = [
            ("renda_mensal", "8000", "Qual é o total de despesas mensais?"),
            ("despesas_mensais", "3000", "Qual é o seu vínculo de trabalho?"),
            ("tipo_emprego", "formal", "Quantos dependentes você tem?"),
            ("num_dependentes", "0", "Você tem dívidas em aberto?"),
        ]
        for i, (campo, valor, proxima) in enumerate(campos, start=5):
            respostas.append(
                chama("registrar_resposta_entrevista", {"campo": campo, "valor": valor}, f"c{i}")
            )
            respostas.append(fala(proxima))
        respostas += [
            chama("registrar_resposta_entrevista", {"campo": "tem_dividas", "valor": "não"}, "c9"),
            chama("finalizar_entrevista", {}, "c10"),
            chama("transferir_para_credito", {}, "c11"),
            chama("solicitar_aumento_limite", {"novo_limite": "6000"}, "c12"),
            fala("Boa notícia: seu pedido de R$ 6.000,00 foi aprovado."),
        ]

        grafo = build_graph(llm=roteiro(*respostas))
        conversar(grafo, "oi")
        conversar(grafo, "quero 6000 de limite", primeira=False)
        conversar(grafo, "aceito a entrevista", primeira=False)
        for resposta_do_cliente in ["8000", "3000", "formal", "0"]:
            conversar(grafo, resposta_do_cliente, primeira=False)

        estado = conversar(grafo, "não tenho dívidas", primeira=False)

        assert estado["cliente"].score_atual == 580
        assert estado["entrevistas_realizadas"] == 1
        assert estado["solicitacao_atual"].status_pedido.value == "aprovado"
        assert estado["agente_atual"] is Agente.CREDITO
        assert orfas(estado) == []

    def test_entrevista_nao_registra_campo_que_nao_perguntou(self) -> None:
        """O bug do `conversa_real.md`: renda tirada do histórico, sem pergunta nenhuma."""
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá, Beatriz!"),
                # A entrevista só é alcançável a partir do crédito.
                chama("transferir_para_credito", {}, "c2"),
                chama("solicitar_aumento_limite", {"novo_limite": "6000"}, "c3"),
                fala("Não consegui aprovar. Quer responder cinco perguntas?"),
                chama("transferir_para_entrevista_credito", {}, "c4"),
                # No mesmo turno do handoff, tenta preencher a renda com o valor do pedido.
                chama(
                    "registrar_resposta_entrevista",
                    {"campo": "renda_mensal", "valor": "6000"},
                    "c5",
                ),
                fala("Qual é a sua renda mensal? Informe em números."),
            )
        )
        conversar(grafo, "oi")
        conversar(grafo, "quero 6000 de limite", primeira=False)

        estado = conversar(grafo, "aceito a entrevista", primeira=False)

        assert estado["entrevista_slots"] == {}
        assert estado["entrevista_campo_perguntado"] == "renda_mensal"
        assert estado["messages"][-1].content.startswith("Qual é a sua renda")
        assert orfas(estado) == []

    def test_teto_de_entrevistas_redireciona_para_credito(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                fala("Olá!"),
                chama("transferir_para_entrevista_credito", {}, "c2"),
                fala("A análise pode ser refeita mais para frente."),
            )
        )
        conversar(grafo, "oi")

        grafo.update_state(
            config_execucao("t1"),
            {"agente_atual": Agente.CREDITO, "entrevistas_realizadas": 1},
        )
        estado = conversar(grafo, "quero a entrevista de novo", primeira=False)

        # A guarda recusou o destino e corrigiu o estado: o controle ficou no crédito.
        assert estado["agente_atual"] is Agente.CREDITO
        assert estado["entrevistas_realizadas"] == 1
        assert estado["messages"][-1].content == "A análise pode ser refeita mais para frente."


class TestEncerramento:
    def test_encerrar_em_qualquer_agente_finaliza(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("encerrar_atendimento", {"motivo": "cliente se despediu"}),
                fala("Foi um prazer atender você. Até logo!"),
            )
        )

        estado = conversar(grafo, "não preciso de mais nada, obrigada")

        assert estado["encerrado"] is True
        assert orfas(estado) == []

    def test_conversa_encerrada_nao_reentra_em_agente(self) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama("encerrar_atendimento", {"motivo": "tchau"}),
                fala("Até logo!"),
            )
        )
        conversar(grafo, "tchau")

        estado = conversar(grafo, "ainda está aí?", primeira=False)

        assert estado["messages"][-1].content == "ainda está aí?"
