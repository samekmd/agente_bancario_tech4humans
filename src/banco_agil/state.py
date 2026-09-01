"""AtendimentoState: contrato de estado compartilhado pelo grafo."""

from typing import Annotated, Any, TypedDict

from langchain_core.messages import HumanMessage
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
    # Valor que o cliente pediu antes da entrevista e ainda não foi reavaliado com o
    # score novo. Existir aqui é o que autoriza o crédito a reoferecer esse valor.
    limite_pendente_reavaliacao: float | None

    # Entrevista de crédito
    entrevista_slots: dict[str, Any]
    entrevistas_realizadas: int
    # Campo que o agente de fato perguntou ao cliente. Só ele pode ser registrado —
    # é o que impede o LLM de preencher um slot com valor tirado do histórico.
    entrevista_campo_perguntado: str | None

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
        limite_pendente_reavaliacao=None,
        entrevista_slots={},
        entrevistas_realizadas=0,
        entrevista_campo_perguntado=None,
        encerrado=False,
        ultimo_erro=None,
    )


def falas_do_cliente(state: AtendimentoState) -> list[str]:
    """Tudo o que o cliente escreveu nesta conversa, na ordem.

    Só `HumanMessage`: o que o agente ou uma tool disse não conta como informação dada pelo
    cliente. É essa distinção que impede um valor citado pelo próprio sistema — o limite
    atual, o teto da faixa — de ser tratado como pedido do cliente.
    """
    return [str(m.content) for m in state.get("messages", []) if isinstance(m, HumanMessage)]


def ultima_fala_do_cliente(state: AtendimentoState) -> str:
    """A última mensagem do cliente, ou vazio se ele ainda não falou."""
    falas = falas_do_cliente(state)
    return falas[-1] if falas else ""
