"""Construção do grafo LangGraph do atendimento (build_graph).

Um nó por agente, nomeado com o valor do enum `Agente` — as handoff tools escrevem esse
mesmo valor em `agente_atual`, e é assim que a aresta condicional encontra o destino.
"""

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from banco_agil.agents import cambio, credito, entrevista, triagem
from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.llm import llm_para
from banco_agil.routing import NO_GUARDA, aplicar_guarda, rota_apos, rota_apos_guarda, rota_inicial
from banco_agil.state import AtendimentoState

CONSTRUTORES = {
    Agente.TRIAGEM: triagem.construir,
    Agente.CREDITO: credito.construir,
    Agente.ENTREVISTA_CREDITO: entrevista.construir,
    Agente.CAMBIO: cambio.construir,
}

# Tipos nossos que atravessam o checkpointer. Sem declarar, o LangGraph avisa a cada
# leitura e passará a bloquear a desserialização numa versão futura.
TIPOS_DO_CHECKPOINT = (
    ("banco_agil.domain.enums", "Agente"),
    ("banco_agil.domain.enums", "StatusPedido"),
    ("banco_agil.domain.enums", "TipoEmprego"),
    ("banco_agil.domain.models", "Cliente"),
    ("banco_agil.domain.models", "SolicitacaoAumento"),
)


def criar_checkpointer() -> BaseCheckpointSaver:
    """Checkpointer em memória que sabe desserializar os modelos do domínio."""
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=TIPOS_DO_CHECKPOINT))


def build_graph(
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Monta e compila o grafo do atendimento.

    `llm` sobrepõe **todos** os agentes — é como os testes injetam um modelo falso.
    Com `None`, cada agente recebe o modelo do seu perfil (`PERFIL_POR_AGENTE`).
    """
    grafo = StateGraph(AtendimentoState)

    for agente, construir in CONSTRUTORES.items():
        grafo.add_node(agente.value, construir(llm=llm or llm_para(agente)))
    grafo.add_node(NO_GUARDA, aplicar_guarda)

    nos_de_agente = {agente.value: agente.value for agente in CONSTRUTORES}
    destinos = nos_de_agente | {NO_GUARDA: NO_GUARDA, END: END}

    grafo.add_conditional_edges(START, rota_inicial, destinos)
    for agente in CONSTRUTORES:
        # Um agente nunca roteia para si mesmo: nesse caso o turno termina.
        saidas = {no: no for no in nos_de_agente if no != agente.value}
        grafo.add_conditional_edges(
            agente.value, rota_apos(agente), saidas | {NO_GUARDA: NO_GUARDA, END: END}
        )
    grafo.add_conditional_edges(NO_GUARDA, rota_apos_guarda, nos_de_agente | {END: END})

    return grafo.compile(checkpointer=checkpointer or criar_checkpointer())


def config_execucao(thread_id: str) -> RunnableConfig:
    """Config de uma invocação: a thread da conversa e o teto de recursão do grafo."""
    return {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": get_settings().recursion_limit,
    }


def exportar_grafo(destino: Path | None = None) -> Path:
    """Desenha o grafo compilado em PNG. Usado por `make grafo`."""
    caminho = destino or get_settings().base_dir / "docs" / "grafo.png"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(build_graph().get_graph().draw_mermaid_png())
    return caminho
