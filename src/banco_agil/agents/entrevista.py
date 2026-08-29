"""Agente de Entrevista de Crédito: slot filling para recálculo de score.

Quem decide qual pergunta fazer é o Python, em `services/entrevista.py`. O prompt do turno
carrega essa decisão pronta; ao LLM cabe só formular a pergunta e extrair o valor da fala.
"""

from langchain_core.language_models import BaseChatModel

from banco_agil.agents.base import construir_agente
from banco_agil.domain.enums import Agente
from banco_agil.services.entrevista import CAMPOS, PERGUNTAS, proximo_campo
from banco_agil.state import AtendimentoState


def contexto(state: AtendimentoState) -> str:
    """Diz exatamente qual campo perguntar agora e o que já foi respondido."""
    slots = state.get("entrevista_slots") or {}
    campo = proximo_campo(slots)

    respondidos = [c for c in CAMPOS if slots.get(c) is not None]
    ja_feitas = (
        f"Já respondidos: {', '.join(respondidos)}."
        if respondidos
        else "Nenhuma pergunta foi feita ainda."
    )

    if campo is None:
        return (
            f"{ja_feitas}\nOs cinco campos estão preenchidos. Chame `finalizar_entrevista` "
            "agora, sem fazer mais perguntas."
        )

    posicao = CAMPOS.index(campo) + 1
    return (
        f"{ja_feitas}\n"
        f"PERGUNTA ATUAL ({posicao} de {len(CAMPOS)}): {PERGUNTAS[campo]}.\n"
        f"Ao registrar a resposta, use o campo `{campo}`."
    )


def construir(llm: BaseChatModel | None = None) -> object:
    """Monta o agente de Entrevista de Crédito."""
    return construir_agente(Agente.ENTREVISTA_CREDITO, contexto=contexto, llm=llm)
