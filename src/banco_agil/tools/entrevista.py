"""Tools da entrevista de crédito: registro de slots e recálculo de score."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.observability.tags import marcar_entrevista
from banco_agil.services.entrevista import (
    CAMPOS,
    PERGUNTAS,
    concluir_entrevista,
    conferir_pergunta_feita,
    proximo_campo,
    registrar_slot,
)
from banco_agil.services.limite import valor_para_nova_tentativa
from banco_agil.state import AtendimentoState
from banco_agil.tools.base import falha, falha_de, responder, sucesso
from banco_agil.utils.exceptions import RespostaNaoSolicitadaError
from banco_agil.utils.logging import get_logger, mascarar_cpf

logger = get_logger("tools.entrevista")

SEM_CLIENTE = "Preciso confirmar a identidade do cliente antes de iniciar a entrevista."


@tool
def registrar_resposta_entrevista(
    campo: str,
    valor: str,
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Registra a resposta do cliente para um campo da entrevista de crédito.

    Campos aceitos: `renda_mensal`, `despesas_mensais`, `tipo_emprego` (formal, autônomo
    ou desempregado), `num_dependentes` e `tem_dividas` (sim ou não). Chame uma vez por
    campo, com o valor exatamente como o cliente falou. Retorna qual é o próximo campo a
    perguntar, ou `entrevista_completa` quando não faltar nenhum.
    """
    slots_atuais = state.get("entrevista_slots") or {}
    perguntado = state.get("entrevista_campo_perguntado")
    logger.info(
        "-> registrar_resposta_entrevista(campo=%r, valor=%r) | campo perguntado=%r",
        campo,
        valor,
        perguntado,
    )
    try:
        conferir_pergunta_feita(campo, perguntado)
        slots = registrar_slot(slots_atuais, campo, valor)
    except RespostaNaoSolicitadaError as erro:
        payload = falha_de(erro, "registrar_resposta_entrevista")
        payload["campo_esperado"] = proximo_campo(slots_atuais)
        return responder(payload, tool_call_id)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro, "registrar_resposta_entrevista"), tool_call_id)

    falta = proximo_campo(slots)
    logger.info(
        "<- registrar_resposta_entrevista: ok | próximo=%s | completa=%s",
        falta,
        falta is None,
    )
    payload = sucesso(
        campo_registrado=campo,
        valor_registrado=slots[campo],
        proximo_campo=falta,
        pergunta_seguinte=PERGUNTAS[falta] if falta else None,
        entrevista_completa=falta is None,
        campos_pendentes=[c for c in CAMPOS if slots.get(c) is None],
    )
    return responder(
        payload,
        tool_call_id,
        entrevista_slots=slots,
        # Consumido: o próximo campo precisa ser perguntado antes de ser registrado.
        entrevista_campo_perguntado=None,
    )


@tool
def finalizar_entrevista(
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Recalcula o score do cliente com as respostas da entrevista e salva o novo valor.

    Só use depois que os cinco campos estiverem registrados. Retorna o score anterior e o
    novo. Com o score atualizado, o pedido de aumento pode ser refeito.
    """
    cliente = state.get("cliente")
    slots = state.get("entrevista_slots") or {}
    logger.info(
        "-> finalizar_entrevista(cpf=%s, slots=%s)",
        mascarar_cpf(cliente.cpf if cliente else None),
        {k: str(v) for k, v in slots.items()},
    )
    if cliente is None:
        logger.warning("<- finalizar_entrevista: sem cliente autenticado no estado")
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        atualizado = concluir_entrevista(cliente, slots)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro, "finalizar_entrevista"), tool_call_id)

    logger.info(
        "<- finalizar_entrevista: score %d -> %d",
        cliente.score_atual,
        atualizado.score_atual,
    )
    marcar_entrevista(cliente.score_atual, atualizado.score_atual)

    pendente = valor_para_nova_tentativa(state.get("solicitacao_atual"))
    if pendente is not None:
        logger.info("pedido de R$ %.2f fica disponível para nova tentativa", pendente)

    payload = sucesso(
        score_anterior=cliente.score_atual,
        score_novo=atualizado.score_atual,
        melhorou=atualizado.score_atual > cliente.score_atual,
        valor_pedido_antes=pendente,
    )
    return responder(
        payload,
        tool_call_id,
        cliente=atualizado,
        entrevistas_realizadas=state.get("entrevistas_realizadas", 0) + 1,
        limite_pendente_reavaliacao=pendente,
    )
