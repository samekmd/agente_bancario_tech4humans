"""Testes da UI Streamlit, exercitando o script da página com `AppTest`."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from streamlit.testing.v1 import AppTest

import ui.session as sessao
from banco_agil.graph import build_graph
from tests.integration.conftest import chama, fala, roteiro

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
