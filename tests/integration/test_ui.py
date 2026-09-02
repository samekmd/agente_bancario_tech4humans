"""Testes da UI Streamlit, exercitando o script da página com `AppTest`."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from streamlit.testing.v1 import AppTest

import ui.session as sessao
from banco_agil.graph import build_graph
from tests.integration.conftest import LLMRoteirizado, chama, fala, roteiro

pytestmark = pytest.mark.integration

# `AppTest.from_file` resolve caminho relativo contra o arquivo que chama.
APP = str(Path(__file__).resolve().parents[2] / "app.py")

CPF = "390.533.447-05"
NASCIMENTO = "04/11/1990"
TIMEOUT_S = 30


@pytest.fixture
def pagina(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Monta a página com o grafo ligado a um LLM roteirizado."""

    def montar(*mensagens: Any) -> AppTest:
        # `obter_grafo` é `@st.cache_resource`: sem limpar, o grafo vaza entre testes.
        sessao.obter_grafo.clear()
        llm = roteiro(*mensagens)
        monkeypatch.setattr(sessao, "build_graph", lambda: build_graph(llm=llm))
        return AppTest.from_file(APP, default_timeout=TIMEOUT_S).run()

    yield montar
    sessao.obter_grafo.clear()


def responder(pagina: AppTest, texto: str) -> str:
    """Manda uma mensagem pelo chat e devolve a resposta crua do assistente.

    Vem do histórico, e não do markdown renderizado, porque a renderização escapa `$`.
    """
    pagina.chat_input[0].set_value(texto).run()
    return pagina.session_state["historico"][-1][1]


def renderizado(pagina: AppTest) -> str:
    """O texto como o Streamlit recebeu para renderizar."""
    return pagina.chat_message[-1].markdown[0].value


def test_pagina_abre_com_saudacao_e_campo_de_envio(pagina: Any) -> None:
    at = pagina(fala("nunca usado"))

    assert at.exception == []
    assert at.title[0].value == "Banco Ágil"
    assert "Banco Ágil" in at.chat_message[0].markdown[0].value
    assert len(at.chat_input) == 1


def test_conversa_mostra_pergunta_e_resposta(pagina: Any) -> None:
    at = pagina(
        chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
        fala("Olá, Beatriz! Como posso ajudar?"),
    )

    resposta = responder(at, f"oi, cpf {CPF}, nasci em {NASCIMENTO}")

    assert resposta == "Olá, Beatriz! Como posso ajudar?"
    assert at.exception == []
    papeis = [("user", f"oi, cpf {CPF}, nasci em {NASCIMENTO}"), ("assistant", resposta)]
    assert at.session_state["historico"] == papeis


def test_handoff_e_invisivel_para_o_cliente(pagina: Any) -> None:
    """O cliente vê um atendente só: nada de ToolMessage ou aviso de transferência."""
    at = pagina(
        chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
        fala("Olá!"),
        chama("transferir_para_credito", {}, "c2"),
        chama("consultar_limite", {}, "c3"),
        fala("Seu limite atual é R$ 2.500,00."),
    )
    responder(at, "oi")

    resposta = responder(at, "qual meu limite?")

    assert resposta == "Seu limite atual é R$ 2.500,00."
    exibido = " ".join(texto for _, texto in at.session_state["historico"])
    assert '"ok"' not in exibido
    assert "transfer" not in exibido.lower()


def test_encerramento_bloqueia_o_envio_e_oferece_recomeco(pagina: Any) -> None:
    at = pagina(
        chama("encerrar_atendimento", {"motivo": "cliente se despediu"}, "c1"),
        fala("Foi um prazer atender você. Até logo!"),
    )

    responder(at, "era só isso, obrigada")

    assert at.session_state["encerrado"] is True
    assert at.chat_input == []
    assert "encerrado" in at.info[0].value
    assert "Iniciar novo atendimento" in [b.label for b in at.button]


def test_novo_atendimento_troca_a_thread_e_limpa_o_historico(pagina: Any) -> None:
    at = pagina(
        chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
        fala("Olá!"),
    )
    responder(at, "oi")
    thread_antiga = at.session_state["thread_id"]

    at.sidebar.button[0].click().run()

    assert at.session_state["thread_id"] != thread_antiga
    assert at.session_state["historico"] == []
    assert at.session_state["primeiro_turno"] is True


def test_falha_do_llm_vira_mensagem_ao_cliente(
    pagina: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nenhuma exceção chega à página: o detalhe técnico fica no log."""
    at = pagina(fala("nunca usado"))

    def explodir(*a: Any, **k: Any) -> None:
        raise RuntimeError("Invalid API Key")

    monkeypatch.setattr(sessao.obter_grafo(), "invoke", explodir)
    resposta = responder(at, "oi")

    assert resposta == sessao.ERRO_ATENDIMENTO
    assert at.exception == []


def _erro_de_validacao() -> ValidationError:
    class Config(BaseModel):
        groq_api_key: str

    try:
        Config()
    except ValidationError as erro:
        return erro
    raise AssertionError


def test_configuracao_ausente_orienta_em_vez_de_quebrar(monkeypatch: pytest.MonkeyPatch) -> None:
    def sem_config() -> None:
        raise _erro_de_validacao()

    # `ui.chat` importa a função por nome: o patch precisa ser onde ela é usada.
    monkeypatch.setattr("ui.chat.obter_grafo", sem_config)
    at = AppTest.from_file(APP, default_timeout=TIMEOUT_S).run()

    assert at.exception == []
    assert "GROQ_API_KEY" in at.error[0].value
    assert at.chat_input == []


def test_cifrao_e_escapado_para_nao_virar_latex(pagina: Any) -> None:
    """`st.markdown` lê `$...$` como fórmula: dois valores em reais perdiam os cifrões.

    Foi o que chegou ao cliente como "R 5.000,00 ... R 1.000,00" no lugar de "R$ ...".
    """
    at = pagina(
        chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}, "c1"),
        fala("Não aprovei R$ 5.000,00. Seu perfil permite até R$ 1.000,00."),
    )

    resposta = responder(at, "quero 5000 de limite")

    # O texto do agente continua intacto no histórico...
    assert resposta == "Não aprovei R$ 5.000,00. Seu perfil permite até R$ 1.000,00."
    # ...e chega escapado ao Streamlit, para os dois cifrões sobreviverem na tela.
    assert renderizado(at) == "Não aprovei R\\$ 5.000,00. Seu perfil permite até R\\$ 1.000,00."


def test_cifrao_do_cliente_tambem_e_escapado(pagina: Any) -> None:
    at = pagina(fala("Certo."))

    responder(at, "quero R$ 5.000,00 de limite")

    exibido = [m.markdown[0].value for m in at.chat_message]
    assert any("R\\$ 5.000,00" in texto for texto in exibido)


def test_barra_lateral_mostra_que_a_observabilidade_esta_desligada(pagina: Any) -> None:
    """Sem isso, o cliente conversa e nada é gravado sem ninguém notar."""
    at = pagina(fala("Olá!"))

    legendas = [c.value for c in at.sidebar.caption]
    assert any("Observabilidade: desligada" in texto for texto in legendas)
    assert any("make mlflow" in texto for texto in legendas)


def test_cada_mensagem_tenta_reconectar_a_observabilidade(
    pagina: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """O conserto do bug: a tentativa saiu do `obter_grafo()` cacheado.

    Antes, uma falha na subida do app desligava o tracing pelo resto do processo. Agora
    cada mensagem tenta de novo, então subir o servidor no meio da conversa passa a gravar.
    """
    at = pagina(fala("Primeira."), fala("Segunda."))
    tentativas: list[int] = []
    monkeypatch.setattr(sessao, "configurar_mlflow", lambda: tentativas.append(1))

    responder(at, "oi")
    responder(at, "e agora?")

    assert len(tentativas) == 2


ERRO_CRU_DO_GROQ = (
    "Error code: 400 - {'error': {'message': \"Tool call validation failed: attempted to "
    "call tool 'solicitar_aumento_limite<|channel|>commentary' which was not in "
    "request.tools\", 'code': 'tool_use_failed'}}"
)


class TestNadaTecnicoChegaAoCliente:
    """O erro cru do Groq chegou à tela depois de três tentativas. Não pode voltar a acontecer."""

    def test_falha_persistente_vira_mensagem_amigavel(
        self, pagina: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        at = pagina(fala("nunca usado"))

        class LLMSempreQuebrado(LLMRoteirizado):
            def _generate(self, messages, *args: Any, **kwargs: Any):  # noqa: ANN002, ANN003
                raise RuntimeError(ERRO_CRU_DO_GROQ)

        monkeypatch.setattr(
            sessao, "build_graph", lambda: build_graph(llm=LLMSempreQuebrado(responses=[]))
        )
        sessao.obter_grafo.clear()

        resposta = responder(at, "quero aumentar meu limite")

        assert at.exception == []
        for vazamento in ("Error code", "400", "tool_use_failed", "<|channel|>", "Model call"):
            assert vazamento not in resposta

    @pytest.mark.parametrize(
        "tecnico",
        [
            "Model call failed after 3 attempts with BadRequestError: Error code: 400",
            "Error code: 400 - invalid_request_error",
            "attempted to call tool 'x<|channel|>commentary'",
            "Traceback (most recent call last): ...",
        ],
    )
    def test_filtro_mascara_texto_tecnico_de_qualquer_origem(self, tecnico: str) -> None:
        assert sessao.resposta_segura(tecnico) == sessao.ERRO_ATENDIMENTO

    @pytest.mark.parametrize(
        "legitima",
        [
            "Seu limite atual é R$ 400,00.",
            "Não foi possível aprovar o limite de R$ 8.000,00. O seu perfil permite R$ 3.000,00.",
            "Sua solicitação foi aprovada. O novo limite será aplicado em breve.",
            "Olá, Beatriz! Como posso ajudar?",
        ],
    )
    def test_filtro_nao_mascara_resposta_legitima(self, legitima: str) -> None:
        """Um filtro que engole atendimento válido é pior que o problema que resolve."""
        assert sessao.resposta_segura(legitima) == legitima

    def test_texto_bloqueado_vai_para_o_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """O diagnóstico não pode sumir junto com o mascaramento."""
        import logging

        caplog.set_level(logging.ERROR, logger="banco_agil")

        sessao.resposta_segura("Error code: 400 - tool_use_failed")

        assert "bloqueada antes de chegar ao cliente" in caplog.text
        assert "tool_use_failed" in caplog.text


class TestBloqueioPorAutenticacao:
    """O bloqueio precisa sobreviver ao botão que a própria tela oferece.

    Nos logs de 02/09 o cliente foi bloqueado às 13:56:05 e voltou a tentar às 13:57:07
    com `tentativas antes=0`. O caminho era "Novo atendimento": thread nova, contador
    zerado. A única ação oferecida a quem foi bloqueado desfazia o bloqueio.
    """

    ERRADO = {"cpf": CPF, "data_nascimento": "01/01/1999"}

    def _bloquear(self, pagina: Any) -> Any:
        at = pagina(
            chama("autenticar_cliente", self.ERRADO, "c1"),
            fala("Não confere. Restam 2 tentativas."),
            chama("autenticar_cliente", self.ERRADO, "c2"),
            fala("Ainda não confere. Resta 1 tentativa."),
            chama("autenticar_cliente", self.ERRADO, "c3"),
            fala("Não consegui confirmar sua identidade."),
        )
        for _ in range(3):
            responder(at, "meus dados")
        return at

    def test_tres_mensagens_bloqueiam_a_sessao(self, pagina: Any) -> None:
        at = self._bloquear(pagina)

        assert at.session_state["bloqueado_auth"] is True
        assert at.exception == []

    def test_a_tela_de_bloqueio_nao_oferece_reiniciar(self, pagina: Any) -> None:
        at = self._bloquear(pagina)

        rotulos = [botao.label for botao in at.button]
        assert "Novo atendimento" not in rotulos
        assert "Iniciar novo atendimento" not in rotulos

    def test_a_tela_de_bloqueio_nao_aceita_mais_mensagens(self, pagina: Any) -> None:
        at = self._bloquear(pagina)

        assert at.chat_input == []

    def test_reiniciar_sessao_nao_apaga_o_bloqueio(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A garantia central: `bloqueado_auth` é a única chave que sobrevive ao reinício.

        Testada direto na função, e não pela tela, porque a tela deixou de oferecer o botão
        — mas a garantia precisa valer para qualquer caminho que chame `reiniciar_sessao`.
        """
        estado = SimpleNamespace(
            thread_id="thread-antiga",
            historico=[("user", "oi")],
            encerrado=True,
            primeiro_turno=False,
            bloqueado_auth=True,
        )
        monkeypatch.setattr(sessao.st, "session_state", estado)

        sessao.reiniciar_sessao()

        assert estado.bloqueado_auth is True
        assert estado.thread_id != "thread-antiga"
        assert estado.historico == []
        assert estado.encerrado is False
        assert estado.primeiro_turno is True

    def test_sessao_normal_nao_marca_bloqueio(self, pagina: Any) -> None:
        at = pagina(
            chama("autenticar_cliente", {"cpf": CPF, "data_nascimento": NASCIMENTO}),
            fala("Olá, Beatriz!"),
        )
        responder(at, f"meu cpf é {CPF}, nasci em {NASCIMENTO}")

        assert at.session_state["bloqueado_auth"] is False
        assert len(at.chat_input) == 1
