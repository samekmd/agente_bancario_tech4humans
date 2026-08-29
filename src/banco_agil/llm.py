"""Factory de modelos de linguagem (ChatGroq) a partir da configuração.

Único ponto que instancia um LLM. A chave sai de `config.py`, nunca de `os.getenv`.
"""

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from banco_agil.config import get_settings


def criar_llm(modelo: str | None = None, temperatura: float | None = None) -> BaseChatModel:
    """Instancia o modelo do Groq com o modelo e a temperatura informados.

    `reasoning_format="hidden"` é essencial: sem isso, modelos de raciocínio (a família
    `gpt-oss`, por exemplo) misturam o rascunho do raciocínio na resposta, e o cliente lê
    coisas como "We need to continue after they answer" no meio do atendimento.
    """
    settings = get_settings()
    return ChatGroq(
        model=modelo or settings.modelo_dialogo,
        temperature=settings.temperatura_dialogo if temperatura is None else temperatura,
        api_key=settings.groq_api_key.get_secret_value(),
        reasoning_format="hidden",
    )


def llm_dialogo() -> BaseChatModel:
    """Modelo para conversa com o cliente: temperatura baixa, mas não zero."""
    settings = get_settings()
    return criar_llm(settings.modelo_dialogo, settings.temperatura_dialogo)


def llm_extracao() -> BaseChatModel:
    """Modelo para extração e classificação: temperatura zero."""
    settings = get_settings()
    return criar_llm(settings.modelo_extracao, settings.temperatura_extracao)
