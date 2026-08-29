"""Arestas condicionais determinísticas: roteamento lido do estado, nunca do LLM.

O LLM só chama uma handoff tool, que escreve `agente_atual`. A decisão de para onde ir, a
guarda de autenticação e o teto de entrevistas são Python puro, aqui.
"""

from collections.abc import Callable

from langgraph.graph import END

from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.state import AtendimentoState

NO_GUARDA = "guarda"


def destino_permitido(state: AtendimentoState, destino: Agente) -> Agente:
    """Aplica as guardas de negócio sobre um destino pretendido.

    Nenhum agente além da Triagem atua sem autenticação, e a entrevista tem teto por
    sessão. Verificado aqui, na aresta — nunca no prompt.
    """
    if destino is not Agente.TRIAGEM and not state.get("autenticado"):
        return Agente.TRIAGEM

    if destino is Agente.ENTREVISTA_CREDITO:
        teto = get_settings().max_entrevistas_por_sessao
        if state.get("entrevistas_realizadas", 0) >= teto:
            return Agente.CREDITO

    return destino


def _pretendido(state: AtendimentoState) -> Agente:
    return state.get("agente_atual") or Agente.TRIAGEM


def aplicar_guarda(state: AtendimentoState) -> dict[str, Agente]:
    """Nó que corrige `agente_atual` quando o destino pedido não passa nas guardas.

    Sem esta correção o estado ficaria apontando para um agente que a aresta recusou, e o
    roteamento voltaria a recusá-lo a cada passo — um laço até o `recursion_limit`.
    """
    return {"agente_atual": destino_permitido(state, _pretendido(state))}


def _rotear(state: AtendimentoState) -> str:
    """Nó de destino, ou a guarda quando o pretendido não é permitido."""
    pretendido = _pretendido(state)
    permitido = destino_permitido(state, pretendido)
    return permitido.value if permitido is pretendido else NO_GUARDA


def rota_inicial(state: AtendimentoState) -> str:
    """Escolhe por qual agente a invocação começa.

    Uma conversa nova entra pela Triagem. Nas mensagens seguintes, o checkpointer traz
    `agente_atual` e o cliente volta a falar com quem estava atendendo.
    """
    if state.get("encerrado"):
        return END
    return _rotear(state)


def rota_apos(origem: Agente) -> Callable[[AtendimentoState], str]:
    """Monta a aresta de saída do nó de `origem`.

    O turno termina quando o agente responde sem transferir. Se `agente_atual` mudou, houve
    handoff: o controle segue para o destino na mesma invocação.
    """

    def rota(state: AtendimentoState) -> str:
        if state.get("encerrado"):
            return END
        if _pretendido(state) is origem:
            return END
        return _rotear(state)

    return rota


def rota_apos_guarda(state: AtendimentoState) -> str:
    """Depois da guarda, `agente_atual` já é um destino válido."""
    if state.get("encerrado"):
        return END
    return _pretendido(state).value
