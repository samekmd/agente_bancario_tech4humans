"""Agente de Entrevista de Crédito: slot filling para recálculo de score.

Quem decide qual pergunta fazer é o Python, em `services/entrevista.py`. O prompt do turno
carrega essa decisão pronta; ao LLM cabe só formular a pergunta e extrair o valor da fala.
"""

from typing import Any

from langchain.agents.middleware import after_model
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from banco_agil.agents.base import construir_agente
from banco_agil.domain.enums import Agente
from banco_agil.services.entrevista import CAMPOS, OPCOES, PERGUNTAS, proximo_campo
from banco_agil.state import AtendimentoState
from banco_agil.utils.logging import get_logger

logger = get_logger("agents.entrevista")


def contexto(state: AtendimentoState) -> str:
    """Diz exatamente qual campo perguntar agora e o que já foi respondido."""
    slots = state.get("entrevista_slots") or {}
    campo = proximo_campo(slots)

    respondidos = [c for c in CAMPOS if slots.get(c) is not None]
    ja_feitas = (
        f"Já respondidos: {', '.join(respondidos)}."
        if respondidos
        else "Nenhuma pergunta foi feita ainda."
    )

    if campo is None:
        return (
            f"{ja_feitas}\nOs cinco campos estão preenchidos. Chame `finalizar_entrevista` "
            "agora, sem fazer mais perguntas."
        )

    posicao = CAMPOS.index(campo) + 1
    linhas = [
        ja_feitas,
        f"PERGUNTA ATUAL ({posicao} de {len(CAMPOS)}): {PERGUNTAS[campo]}.",
    ]

    opcoes = OPCOES.get(campo)
    if opcoes:
        lista = ", ".join(opcoes[:-1]) + f" ou {opcoes[-1]}"
        linhas.append(
            f"RESPOSTAS ACEITAS: {lista}. Ofereça as {len(opcoes)} opções na própria "
            "pergunta e deixe claro que o cliente precisa escolher uma delas."
        )

    linhas.append(f"Ao registrar a resposta, use o campo `{campo}`.")
    return "\n".join(linhas)


@after_model(state_schema=AtendimentoState, name="MarcarCampoPerguntado")
def marcar_campo_perguntado(state: AtendimentoState, runtime: object) -> dict[str, Any] | None:
    """Registra no estado qual campo o agente acabou de perguntar ao cliente.

    Roda depois de cada chamada ao modelo. Resposta com tool call não é pergunta: só uma
    resposta em texto significa que o agente devolveu a palavra ao cliente. É esse registro
    que a tool exige para aceitar um valor — sem ele, o LLM poderia preencher um slot com
    algo tirado do histórico da conversa.
    """
    ultima = state["messages"][-1] if state.get("messages") else None
    if not isinstance(ultima, AIMessage) or ultima.tool_calls or not ultima.content:
        return None

    campo = proximo_campo(state.get("entrevista_slots") or {})
    logger.info("agente perguntou ao cliente sobre: %s", campo)
    return {"entrevista_campo_perguntado": campo}


def construir(llm: BaseChatModel | None = None) -> CompiledStateGraph:
    """Monta o agente de Entrevista de Crédito."""
    return construir_agente(
        Agente.ENTREVISTA_CREDITO,
        contexto=contexto,
        llm=llm,
        middlewares=[marcar_campo_perguntado],
    )
