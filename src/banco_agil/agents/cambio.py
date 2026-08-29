"""Agente de Câmbio: cotação de moedas e conversão."""

from langchain_core.language_models import BaseChatModel

from banco_agil.agents.base import construir_agente
from banco_agil.domain.enums import Agente
from banco_agil.state import AtendimentoState


def contexto(state: AtendimentoState) -> str:
    """Câmbio não depende de dado do cliente além de ele estar autenticado."""
    cliente = state.get("cliente")
    if cliente is None:
        return "O cliente ainda não foi autenticado."
    return f"Cliente: {cliente.nome.split()[0]}."


def construir(llm: BaseChatModel | None = None) -> object:
    """Monta o agente de Câmbio."""
    return construir_agente(Agente.CAMBIO, contexto=contexto, llm=llm)
