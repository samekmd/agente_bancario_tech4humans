"""Testes do grafo: roteamento determinístico, handoff e ciclo crédito/entrevista."""

from typing import Any

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from banco_agil.domain.enums import Agente
from banco_agil.graph import build_graph, config_execucao
from banco_agil.state import estado_inicial
from tests.integration.conftest import LLMRoteirizado, chama, fala, roteiro

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

    def test_duas_chamadas_na_mesma_mensagem_gastam_uma_tentativa(self) -> None:
        """Regressão dos logs de 02/09: o agente insistiu sozinho e queimou duas chances.

        Entre as duas chamadas passaram 515 ms — o laço do agente rodou de novo dentro da
        mesma invocação. O limite é de tentativas do cliente, não de chamadas da tool.
        """
        errado = {"cpf": CPF, "data_nascimento": "01/01/1999"}
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", errado, "c1"),
                chama("autenticar_cliente", errado, "c2"),
                fala("Os dados não conferem. Pode conferir e me dizer de novo?"),
            )
        )

        estado = conversar(grafo, "meus dados")

        assert estado["tentativas_auth"] == 1
        assert estado["encerrado"] is False
        assert orfas(estado) == []

    def test_bloqueio_chega_na_terceira_mensagem_mesmo_com_insistencia(self) -> None:
        """Três mensagens bloqueiam, ainda que o agente chame a tool duas vezes em cada."""
        errado = {"cpf": CPF, "data_nascimento": "01/01/1999"}
        grafo = build_graph(
            llm=roteiro(
                chama("autenticar_cliente", errado, "c1a"),
                chama("autenticar_cliente", errado, "c1b"),
                fala("Não confere. Restam 2 tentativas."),
                chama("autenticar_cliente", errado, "c2a"),
                chama("autenticar_cliente", errado, "c2b"),
                fala("Ainda não confere. Resta 1 tentativa."),
                chama("autenticar_cliente", errado, "c3a"),
                fala("Não consegui confirmar sua identidade."),
            )
        )

        for numero in range(3):
            estado = conversar(grafo, "meus dados", primeira=numero == 0)
            if numero < 2:
                assert estado["encerrado"] is False, f"bloqueou cedo, na mensagem {numero + 1}"

        assert estado["tentativas_auth"] == 3
        assert estado["encerrado"] is True
        assert orfas(estado) == []


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


class TestModeloPorAgente:
    def test_llm_injetado_sobrepoe_todos_os_agentes(self) -> None:
        """Com dois modelos reais em jogo, a suíte precisa continuar offline.

        Se `build_graph(llm=...)` deixasse de sobrepor algum nó, aquele agente tentaria
        falar com o Groq de verdade no meio dos testes.
        """
        falso = roteiro(fala("resposta única"))

        grafo = build_graph(llm=falso)

        nos = grafo.get_graph().nodes
        assert {"triagem", "credito", "entrevista_credito", "cambio"} <= set(nos)
        # Uma conversa completa sem rede é a prova de que nenhum nó resolveu modelo real.
        estado = conversar(grafo, "oi")
        assert estado["messages"][-1].content == "resposta única"


class TestRetryDeFormatoDeToolCall:
    """Reprodução do erro real: o modelo erra o formato da tool call e o Groq devolve 400.

    A falha acontece na chamada do LLM, antes de qualquer tool rodar — por isso o
    tratamento de erro das tools não pega. O que salva o turno é repetir a chamada.
    """

    def test_conversa_sobrevive_a_uma_falha_de_formato(self) -> None:
        falhas = {"restantes": 1}
        erro_real = (
            "Error code: 400 - Tool call validation failed: attempted to call tool "
            "'autenticar_cliente<|channel|>commentary' which was not in request.tools "
            "(code: tool_use_failed)"
        )

        class LLMQueFalhaUmaVez(LLMRoteirizado):
            def _generate(self, messages, *args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
                if falhas["restantes"] > 0:
                    falhas["restantes"] -= 1
                    raise RuntimeError(erro_real)
                return super()._generate(messages, *args, **kwargs)

        grafo = build_graph(
            llm=LLMQueFalhaUmaVez(
                responses=[
                    chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
                    fala("Olá, Beatriz! Como posso ajudar?"),
                ]
            )
        )

        estado = conversar(grafo, f"oi, cpf {CPF}, nasci em {NASCIMENTO}")

        assert falhas["restantes"] == 0, "a falha precisa ter sido injetada de fato"
        assert estado["autenticado"] is True
        assert estado["messages"][-1].content == "Olá, Beatriz! Como posso ajudar?"
        assert orfas(estado) == []

    def test_erro_nao_retentavel_nao_e_repetido(self) -> None:
        """Chave inválida não pode custar três tentativas: o cliente esperaria o triplo."""
        tentativas: list[int] = []

        class LLMComChaveInvalida(LLMRoteirizado):
            def _generate(self, messages, *args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
                tentativas.append(1)
                raise RuntimeError("Error code: 401 - Invalid API Key")

        grafo = build_graph(llm=LLMComChaveInvalida(responses=[fala("nunca usado")]))

        with pytest.raises(RuntimeError, match="Invalid API Key"):
            conversar(grafo, "oi")

        assert len(tentativas) == 1


class TestValorInventadoPeloModelo:
    """Reprodução de `conversa_real_erro_solicatao_credito.md`.

    O cliente disse só "Quero aumentar este limite". O modelo pediu R$ 25.000 — número que
    ficava no meio entre o limite atual (20.000) e o teto (30.000), ambos ditos pelo
    próprio sistema. O pedido foi gravado e aprovado.
    """

    # Helena tem o mesmo formato do caso real: limite 5.000, teto 15.000.
    CPF_CLIENTE = "529.982.247-25"
    NASCIMENTO_CLIENTE = "12/03/1985"

    def test_pedido_sem_valor_do_cliente_e_recusado(self, bases_isoladas: Any) -> None:
        grafo = build_graph(
            llm=roteiro(
                chama(
                    "autenticar_cliente",
                    {"cpf": self.CPF_CLIENTE, "data_nascimento": self.NASCIMENTO_CLIENTE},
                    "c1",
                ),
                fala("Olá, Helena! Seu limite atual é R$ 5.000,00."),
                chama("transferir_para_credito", {}, "c2"),
                # O cliente não disse valor nenhum; o modelo inventa um.
                chama("solicitar_aumento_limite", {"novo_limite": "10000"}, "c3"),
                fala("De quanto você gostaria que fosse o novo limite?"),
            )
        )
        conversar(grafo, f"oi, cpf {self.CPF_CLIENTE}, nasci em {self.NASCIMENTO_CLIENTE}")

        estado = conversar(grafo, "Quero aumentar este limite", primeira=False)

        # A tool recusou, então nada foi para o estado nem para o CSV.
        assert estado["solicitacao_atual"] is None
        assert not (bases_isoladas / "solicitacoes_aumento_limite.csv").exists()
        # E o agente teve que perguntar, em vez de anunciar aprovação.
        assert "quanto" in estado["messages"][-1].content.lower()

    def test_pedido_com_valor_dito_pelo_cliente_passa(self, bases_isoladas: Any) -> None:
        """O contraponto: quando o cliente diz o valor, o fluxo funciona como antes."""
        grafo = build_graph(
            llm=roteiro(
                chama(
                    "autenticar_cliente",
                    {"cpf": self.CPF_CLIENTE, "data_nascimento": self.NASCIMENTO_CLIENTE},
                    "c1",
                ),
                fala("Olá, Helena!"),
                chama("transferir_para_credito", {}, "c2"),
                chama("solicitar_aumento_limite", {"novo_limite": "10000"}, "c3"),
                fala("Sua solicitação de R$ 10.000,00 foi aprovada."),
            )
        )
        conversar(grafo, "oi")

        estado = conversar(grafo, "quero aumentar para 10000", primeira=False)

        assert estado["solicitacao_atual"] is not None
        assert estado["solicitacao_atual"].novo_limite_solicitado == 10000.0
