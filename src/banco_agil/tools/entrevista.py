"""Tools da entrevista de crédito: registro de slots e recálculo de score."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.services.entrevista import (
    CAMPOS,
    PERGUNTAS,
    concluir_entrevista,
    proximo_campo,
    registrar_slot,
)
from banco_agil.state import AtendimentoState
from banco_agil.tools.base import falha, falha_de, responder, sucesso

SEM_CLIENTE = "Preciso confirmar a identidade do cliente antes de iniciar a entrevista."


@tool
def registrar_resposta_entrevista(
    campo: str,
    valor: str,
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Registra a resposta do cliente para um campo da entrevista de crédito.

    Campos aceitos: `renda_mensal`, `despesas_mensais`, `tipo_emprego` (formal, autônomo
    ou desempregado), `num_dependentes` e `tem_dividas` (sim ou não). Chame uma vez por
    campo, com o valor exatamente como o cliente falou. Retorna qual é o próximo campo a
    perguntar, ou `entrevista_completa` quando não faltar nenhum.
    """
    try:
        slots = registrar_slot(state.get("entrevista_slots") or {}, campo, valor)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    falta = proximo_campo(slots)
    payload = sucesso(
        campo_registrado=campo,
        valor_registrado=slots[campo],
        proximo_campo=falta,
        pergunta_seguinte=PERGUNTAS[falta] if falta else None,
        entrevista_completa=falta is None,
        campos_pendentes=[c for c in CAMPOS if slots.get(c) is None],
    )
    return responder(payload, tool_call_id, entrevista_slots=slots)


@tool
def finalizar_entrevista(
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Recalcula o score do cliente com as respostas da entrevista e salva o novo valor.

    Só use depois que os cinco campos estiverem registrados. Retorna o score anterior e o
    novo. Com o score atualizado, o pedido de aumento pode ser refeito.
    """
    cliente = state.get("cliente")
    if cliente is None:
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        atualizado = concluir_entrevista(cliente, state.get("entrevista_slots") or {})
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    payload = sucesso(
        score_anterior=cliente.score_atual,
        score_novo=atualizado.score_atual,
        melhorou=atualizado.score_atual > cliente.score_atual,
    )
    return responder(
        payload,
        tool_call_id,
        cliente=atualizado,
        entrevistas_realizadas=state.get("entrevistas_realizadas", 0) + 1,
    )
