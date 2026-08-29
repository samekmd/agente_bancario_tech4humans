"""Tools expostas aos agentes: adaptadores finos sobre os services.

`TOOLS_POR_AGENTE` é a garantia da regra 4: o escopo de cada agente é o conjunto de
ferramentas que ele recebe no binding, não uma instrução de prompt. Câmbio não tem como
consultar limite porque a ferramenta não está na lista dele.
"""

from langchain_core.tools import BaseTool

from banco_agil.domain.enums import Agente
from banco_agil.tools.autenticacao import autenticar_cliente
from banco_agil.tools.cambio import consultar_cotacao, converter_valor
from banco_agil.tools.credito import consultar_limite, solicitar_aumento_limite
from banco_agil.tools.entrevista import finalizar_entrevista, registrar_resposta_entrevista
from banco_agil.tools.handoff import (
    transferir_para_cambio,
    transferir_para_credito,
    transferir_para_entrevista_credito,
    transferir_para_triagem,
)
from banco_agil.tools.sistema import encerrar_atendimento

TOOLS_POR_AGENTE: dict[Agente, tuple[BaseTool, ...]] = {
    Agente.TRIAGEM: (
        autenticar_cliente,
        transferir_para_credito,
        transferir_para_cambio,
        encerrar_atendimento,
    ),
    Agente.CREDITO: (
        consultar_limite,
        solicitar_aumento_limite,
        transferir_para_entrevista_credito,
        transferir_para_cambio,
        transferir_para_triagem,
        encerrar_atendimento,
    ),
    Agente.ENTREVISTA_CREDITO: (
        registrar_resposta_entrevista,
        finalizar_entrevista,
        transferir_para_credito,
        encerrar_atendimento,
    ),
    Agente.CAMBIO: (
        consultar_cotacao,
        converter_valor,
        transferir_para_credito,
        transferir_para_triagem,
        encerrar_atendimento,
    ),
}


def tools_de(agente: Agente) -> tuple[BaseTool, ...]:
    """Retorna as ferramentas do agente. É o único caminho para montar um binding."""
    return TOOLS_POR_AGENTE[agente]


__all__ = [
    "TOOLS_POR_AGENTE",
    "autenticar_cliente",
    "consultar_cotacao",
    "consultar_limite",
    "converter_valor",
    "encerrar_atendimento",
    "finalizar_entrevista",
    "registrar_resposta_entrevista",
    "solicitar_aumento_limite",
    "tools_de",
    "transferir_para_cambio",
    "transferir_para_credito",
    "transferir_para_entrevista_credito",
    "transferir_para_triagem",
]
