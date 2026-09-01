"""Factory de modelos de linguagem (ChatGroq) a partir da configuração.

Único ponto que instancia um LLM. A chave sai de `config.py`, nunca de `os.getenv`.

Os agentes não usam todos o mesmo modelo: `PERFIL_POR_AGENTE` é a política inteira num
lugar só, no mesmo espírito do `TOOLS_POR_AGENTE`.
"""

from enum import StrEnum

from langchain_core.language_models import BaseChatModel
from langchain_groq import ChatGroq

from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.utils.logging import get_logger

logger = get_logger("llm")


def criar_llm(modelo: str | None = None, temperatura: float | None = None) -> BaseChatModel:
    """Instancia o modelo do Groq com o modelo e a temperatura informados.

    `reasoning_format="hidden"` é essencial: sem isso, modelos de raciocínio (a família
    `gpt-oss`, por exemplo) misturam o rascunho do raciocínio na resposta, e o cliente lê
    coisas como "We need to continue after they answer" no meio do atendimento.

    `max_tokens` é a rede de segurança para o outro sintoma observado: repetição
    degenerada, em que o modelo repete o mesmo fragmento dezenas de vezes.
    """
    settings = get_settings()
    return ChatGroq(
        model=modelo or settings.modelo_barato,
        temperature=settings.temperatura_dialogo if temperatura is None else temperatura,
        api_key=settings.groq_api_key.get_secret_value(),
        reasoning_format="hidden",
        max_tokens=settings.max_tokens_resposta,
    )


def llm_dialogo() -> BaseChatModel:
    """Conversa com o cliente no modelo barato: temperatura baixa, mas não zero."""
    settings = get_settings()
    return criar_llm(settings.modelo_barato, settings.temperatura_dialogo)


def llm_dialogo_robusto() -> BaseChatModel:
    """Conversa com o cliente no modelo robusto, mantendo a temperatura de diálogo."""
    settings = get_settings()
    return criar_llm(settings.modelo_robusto, settings.temperatura_dialogo)


def llm_extracao() -> BaseChatModel:
    """Extração e classificação: modelo robusto a temperatura zero."""
    settings = get_settings()
    return criar_llm(settings.modelo_robusto, settings.temperatura_extracao)


class PerfilLLM(StrEnum):
    """Combinação de modelo e temperatura que um agente usa.

    São dois eixos independentes: a robustez do modelo e a temperatura. O crédito precisa
    do primeiro sem precisar do segundo — ele conversa, mas erra caro.
    """

    DIALOGO = "dialogo"
    DIALOGO_ROBUSTO = "dialogo_robusto"
    EXTRACAO = "extracao"


# A política de modelos do sistema, num lugar só.
#
# Crédito e entrevista usam o modelo robusto porque são os agentes que escrevem estado
# permanente: um decide pedido de crédito, o outro grava score na base. Só a entrevista
# roda a temperatura zero, porque lá a fala do cliente vira dado e criatividade é defeito;
# o crédito conversa, então mantém a temperatura de diálogo.
PERFIL_POR_AGENTE: dict[Agente, PerfilLLM] = {
    Agente.TRIAGEM: PerfilLLM.DIALOGO,
    Agente.CREDITO: PerfilLLM.DIALOGO_ROBUSTO,
    Agente.ENTREVISTA_CREDITO: PerfilLLM.EXTRACAO,
    Agente.CAMBIO: PerfilLLM.DIALOGO,
}

_FABRICAS = {
    PerfilLLM.DIALOGO: llm_dialogo,
    PerfilLLM.DIALOGO_ROBUSTO: llm_dialogo_robusto,
    PerfilLLM.EXTRACAO: llm_extracao,
}


def llm_para(agente: Agente) -> BaseChatModel:
    """Instancia o modelo do perfil daquele agente."""
    perfil = PERFIL_POR_AGENTE[agente]
    modelo = _FABRICAS[perfil]()
    logger.info(
        "agente %s usará o perfil %s: modelo %s, temperatura %s",
        agente.value,
        perfil.value,
        modelo.model_name,
        modelo.temperature,
    )
    return modelo
