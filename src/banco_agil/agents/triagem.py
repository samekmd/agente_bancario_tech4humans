"""Agente de Triagem: acolhe o cliente, autentica e encaminha."""

from langchain_core.language_models import BaseChatModel

from banco_agil.agents.base import construir_agente
from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.state import AtendimentoState


def contexto(state: AtendimentoState) -> str:
    """Situação da autenticação, contada em Python e não pelo LLM."""
    if state.get("autenticado"):
        cliente = state.get("cliente")
        nome = cliente.nome.split()[0] if cliente else "o cliente"
        return f"O cliente já está autenticado e se chama {nome}. Não peça os dados de novo."

    tentativas = state.get("tentativas_auth", 0)
    restantes = max(0, get_settings().max_tentativas_auth - tentativas)
    if tentativas == 0:
        return "O cliente ainda não se identificou. Peça CPF e data de nascimento."
    return (
        f"O cliente já errou os dados {tentativas} vez(es) e ainda tem {restantes} "
        "tentativa(s). Informe isso a ele ao pedir os dados novamente."
    )


def construir(llm: BaseChatModel | None = None) -> object:
    """Monta o agente de Triagem."""
    return construir_agente(Agente.TRIAGEM, contexto=contexto, llm=llm)
