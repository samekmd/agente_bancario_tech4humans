"""Estado de sessão do Streamlit: thread_id e ciclo de vida da conversa.

A UI não conhece agentes, tools nem roteamento: ela manda uma mensagem e recebe uma
resposta. Cada mensagem do usuário é uma invocação do grafo, com o `thread_id` da sessão.
"""

from typing import Any
from uuid import uuid4

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from banco_agil.graph import build_graph, config_execucao
from banco_agil.observability.setup import configurar_mlflow
from banco_agil.state import estado_inicial
from banco_agil.utils.logging import configurar_logging, get_logger

SEM_RESPOSTA = "Desculpe, não consegui responder agora. Pode repetir?"
ERRO_ATENDIMENTO = (
    "Tive um problema técnico aqui e não consegui concluir. Pode tentar de novo em instantes?"
)

logger = get_logger("ui")


@st.cache_resource
def obter_grafo() -> CompiledStateGraph:
    """Compila o grafo uma vez por processo. O checkpointer separa as conversas por thread."""
    configurar_logging()
    configurar_mlflow()
    return build_graph()


def iniciar_sessao() -> None:
    """Garante os campos da sessão na primeira execução da página."""
    st.session_state.setdefault("thread_id", str(uuid4()))
    st.session_state.setdefault("historico", [])
    st.session_state.setdefault("encerrado", False)
    st.session_state.setdefault("primeiro_turno", True)


def reiniciar_sessao() -> None:
    """Começa um atendimento novo, com thread e histórico limpos."""
    st.session_state.thread_id = str(uuid4())
    st.session_state.historico = []
    st.session_state.encerrado = False
    st.session_state.primeiro_turno = True


def _ultima_fala(estado: dict[str, Any]) -> str:
    """Pega a última mensagem que o assistente de fato dirigiu ao cliente."""
    for mensagem in reversed(estado.get("messages", [])):
        if isinstance(mensagem, AIMessage) and mensagem.content:
            return str(mensagem.content)
    return SEM_RESPOSTA


def enviar_mensagem(texto: str) -> str:
    """Roda uma invocação do grafo e devolve a resposta ao cliente.

    Nenhuma exceção sobe para a página: falha de LLM ou de rede vira uma mensagem que o
    cliente entende, e o detalhe técnico fica no log.
    """
    entrada: dict[str, Any] = {"messages": [HumanMessage(content=texto)]}
    if st.session_state.primeiro_turno:
        entrada = {**estado_inicial(), **entrada}

    try:
        estado = obter_grafo().invoke(entrada, config=config_execucao(st.session_state.thread_id))
    except Exception:
        logger.exception("falha ao processar a mensagem do cliente")
        return ERRO_ATENDIMENTO

    st.session_state.primeiro_turno = False
    st.session_state.encerrado = bool(estado.get("encerrado"))
    return _ultima_fala(estado)
