"""Tools de sistema: encerramento do atendimento e utilidades transversais.

Disponíveis para todos os agentes — encerrar por pedido do cliente é sempre possível.
"""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from banco_agil.tools.base import responder, sucesso
from banco_agil.utils.logging import get_logger

logger = get_logger("tools.sistema")


@tool
def encerrar_atendimento(
    motivo: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Encerra o atendimento a pedido do cliente.

    Use quando o cliente disser que não precisa de mais nada, quiser se despedir ou pedir
    para encerrar. Informe em `motivo` o que o cliente disse, em poucas palavras. Depois
    de chamar, despeça-se com cordialidade na mesma resposta.
    """
    logger.info("encerrar_atendimento: motivo=%r", motivo)
    payload = sucesso(motivo=motivo, mensagem="Atendimento encerrado.")
    return responder(payload, tool_call_id, encerrado=True)
