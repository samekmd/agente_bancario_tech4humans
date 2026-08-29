"""Tools de crédito: consulta de limite e solicitação de aumento."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.services.limite import limite_maximo_permitido, processar_pedido_aumento
from banco_agil.state import AtendimentoState
from banco_agil.tools.base import falha, falha_de, responder, sucesso
from banco_agil.utils.validators import validar_valor_monetario

SEM_CLIENTE = "Preciso confirmar a identidade do cliente antes de falar sobre o limite."


@tool
def consultar_limite(
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Consulta o limite atual do cliente autenticado e o teto que o score dele permite.

    Use quando o cliente perguntar qual é o limite dele ou quanto poderia ter. Retorna o
    limite atual, o score e o limite máximo autorizado para a faixa desse score.
    """
    cliente = state.get("cliente")
    if cliente is None:
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        maximo = limite_maximo_permitido(cliente.score_atual)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    payload = sucesso(
        limite_atual=cliente.limite_atual,
        score_atual=cliente.score_atual,
        limite_maximo_permitido=maximo,
    )
    return responder(payload, tool_call_id)


@tool
def solicitar_aumento_limite(
    novo_limite: str,
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Registra e avalia um pedido de aumento de limite para o cliente autenticado.

    Use quando o cliente disser quanto quer de limite. O valor pode vir como "8000" ou
    "R$ 8.000,00". O pedido é sempre registrado antes da decisão. Retorna se foi aprovado
    ou rejeitado e qual o limite máximo permitido pelo score atual. Se for rejeitado,
    ofereça a entrevista de crédito ao cliente.
    """
    cliente = state.get("cliente")
    if cliente is None:
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        valor = validar_valor_monetario(novo_limite)
        pedido, avaliacao = processar_pedido_aumento(cliente, valor)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    payload = sucesso(
        aprovado=avaliacao.aprovado,
        status=avaliacao.status_pedido,
        limite_solicitado=avaliacao.limite_solicitado,
        limite_maximo_permitido=avaliacao.limite_maximo,
        limite_atual=cliente.limite_atual,
        score_atual=cliente.score_atual,
    )
    return responder(payload, tool_call_id, solicitacao_atual=pedido)
