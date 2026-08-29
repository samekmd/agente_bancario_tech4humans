"""Agente de Crédito: consulta e solicitação de aumento de limite."""

from langchain_core.language_models import BaseChatModel

from banco_agil.agents.base import construir_agente
from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente, StatusPedido
from banco_agil.state import AtendimentoState


def contexto(state: AtendimentoState) -> str:
    """Dados do cliente e situação do pedido, para o LLM não precisar deduzir nada."""
    cliente = state.get("cliente")
    if cliente is None:
        return "O cliente ainda não foi autenticado. Não fale sobre limite."

    linhas = [
        f"Cliente: {cliente.nome.split()[0]}.",
        f"Limite atual: R$ {cliente.limite_atual:.2f}.",
    ]

    pedido = state.get("solicitacao_atual")
    if pedido is not None:
        linhas.append(
            f"Último pedido nesta conversa: R$ {pedido.novo_limite_solicitado:.2f}, "
            f"resultado {pedido.status_pedido.value}."
        )

    if state.get("entrevistas_realizadas", 0) >= get_settings().max_entrevistas_por_sessao:
        linhas.append(
            "O cliente já passou pela entrevista nesta conversa. Não ofereça a entrevista "
            "de novo, mesmo que o pedido seja rejeitado."
        )
    elif pedido is not None and pedido.status_pedido is StatusPedido.REJEITADO:
        linhas.append("O pedido foi rejeitado e a entrevista ainda está disponível: ofereça.")

    return "\n".join(f"- {linha}" for linha in linhas)


def construir(llm: BaseChatModel | None = None) -> object:
    """Monta o agente de Crédito."""
    return construir_agente(Agente.CREDITO, contexto=contexto, llm=llm)
