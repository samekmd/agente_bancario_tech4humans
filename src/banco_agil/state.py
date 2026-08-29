"""AtendimentoState: contrato de estado compartilhado pelo grafo."""

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from banco_agil.domain.enums import Agente
from banco_agil.domain.models import Cliente, SolicitacaoAumento


class AtendimentoState(TypedDict):
    """Estado único do atendimento. As arestas condicionais leem estes campos."""

    # Histórico da conversa. `messages` é a chave default dos prebuilts do LangGraph.
    messages: Annotated[list, add_messages]

    # Agente que detém o turno. Escrito apenas pelas handoff tools.
    agente_atual: Agente

    # Autenticação
    autenticado: bool
    tentativas_auth: int
    cpf: str | None
    cliente: Cliente | None

    # Crédito
    solicitacao_atual: SolicitacaoAumento | None

    # Entrevista de crédito
    entrevista_slots: dict[str, Any]
    entrevistas_realizadas: int

    # Ciclo de vida
    encerrado: bool
    ultimo_erro: str | None


def estado_inicial() -> AtendimentoState:
    """Retorna o estado de uma conversa recém-aberta, antes da primeira mensagem."""
    return AtendimentoState(
        messages=[],
        agente_atual=Agente.TRIAGEM,
        autenticado=False,
        tentativas_auth=0,
        cpf=None,
        cliente=None,
        solicitacao_atual=None,
        entrevista_slots={},
        entrevistas_realizadas=0,
        encerrado=False,
        ultimo_erro=None,
    )
