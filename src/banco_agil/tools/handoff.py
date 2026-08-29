"""Tools de handoff entre agentes, que escrevem `agente_atual` no estado.

O handoff não encerra o turno: o `Command` salta para o nó do agente de destino no grafo
pai e a execução continua, de modo que quem recebe o controle responde na mesma mensagem.
O nome de cada nó do grafo é o valor do enum `Agente`.
"""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from banco_agil.domain.enums import Agente
from banco_agil.tools.base import responder, sucesso


def _transferir(destino: Agente, tool_call_id: str) -> Command:
    """Move o controle para outro agente, sem interromper a execução do grafo."""
    payload = sucesso(agente_atual=destino, mensagem="Controle transferido.")
    return responder(payload, tool_call_id, goto=destino.value, agente_atual=destino)


@tool
def transferir_para_credito(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Passa o atendimento para a especialidade de crédito.

    Use quando o cliente falar sobre limite do cartão, consulta de limite ou pedido de
    aumento. Não avise o cliente sobre a transferência e não se despeça: o atendimento
    continua na mesma resposta.
    """
    return _transferir(Agente.CREDITO, tool_call_id)


@tool
def transferir_para_entrevista_credito(
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Passa o atendimento para a entrevista de crédito.

    Use quando um pedido de aumento for rejeitado e o cliente aceitar responder às
    perguntas para tentar melhorar o score. Não anuncie a transferência.
    """
    return _transferir(Agente.ENTREVISTA_CREDITO, tool_call_id)


@tool
def transferir_para_cambio(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Passa o atendimento para a especialidade de câmbio.

    Use quando o cliente perguntar sobre cotação de moedas ou conversão de valores. Não
    anuncie a transferência.
    """
    return _transferir(Agente.CAMBIO, tool_call_id)


@tool
def transferir_para_triagem(tool_call_id: Annotated[str, InjectedToolCallId]) -> Command:
    """Devolve o atendimento para a triagem.

    Use quando o assunto sair da sua especialidade e ainda não estiver claro para onde
    encaminhar. Não anuncie a transferência.
    """
    return _transferir(Agente.TRIAGEM, tool_call_id)
