"""Tools de crédito: consulta de limite e solicitação de aumento."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.observability.tags import marcar_desfecho_pedido
from banco_agil.services.limite import (
    conferir_valor_do_cliente,
    limite_maximo_permitido,
    processar_pedido_aumento,
)
from banco_agil.state import AtendimentoState, falas_do_cliente
from banco_agil.tools.base import falha, falha_de, responder, sucesso
from banco_agil.utils.exceptions import ValorNaoInformadoError
from banco_agil.utils.logging import dump_seguro, get_logger, mascarar_cpf
from banco_agil.utils.validators import validar_valor_monetario

logger = get_logger("tools.credito")

SEM_CLIENTE = "Preciso confirmar a identidade do cliente antes de falar sobre o limite."


@tool
def consultar_limite(
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Consulta o limite atual do cliente autenticado e o teto que o score dele permite.

    Use quando o cliente perguntar qual é o limite dele ou quanto poderia ter. Retorna o
    limite atual, o score e o limite máximo autorizado para a faixa desse score.
    """
    cliente = state.get("cliente")
    logger.info("-> consultar_limite(cpf=%s)", mascarar_cpf(cliente.cpf if cliente else None))
    if cliente is None:
        logger.warning("<- consultar_limite: sem cliente autenticado no estado")
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        maximo = limite_maximo_permitido(cliente.score_atual)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro, "consultar_limite"), tool_call_id)

    logger.info(
        "<- consultar_limite: atual=R$ %.2f, score=%d, teto=R$ %.2f",
        cliente.limite_atual,
        cliente.score_atual,
        maximo,
    )

    payload = sucesso(
        limite_atual=cliente.limite_atual,
        score_atual=cliente.score_atual,
        limite_maximo_permitido=maximo,
    )
    return responder(payload, tool_call_id)


@tool
def solicitar_aumento_limite(
    novo_limite: str,
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Registra e avalia um pedido de aumento de limite para o cliente autenticado.

    Use quando o cliente disser quanto quer de limite. O valor pode vir como "8000" ou
    "R$ 8.000,00". O pedido é sempre registrado antes da decisão. Retorna se foi aprovado
    ou rejeitado e qual o limite máximo permitido pelo score atual. Se for rejeitado,
    ofereça a entrevista de crédito ao cliente.
    """
    cliente = state.get("cliente")
    logger.info(
        "-> solicitar_aumento_limite(novo_limite=%r, cpf=%s)",
        novo_limite,
        mascarar_cpf(cliente.cpf if cliente else None),
    )
    if cliente is None:
        logger.warning("<- solicitar_aumento_limite: sem cliente autenticado no estado")
        return responder(falha(SEM_CLIENTE), tool_call_id)

    try:
        valor = validar_valor_monetario(novo_limite)
        logger.debug("valor solicitado normalizado: %r -> %.2f", novo_limite, valor)
        # O valor precisa ter saído do cliente: um modelo já pediu R$ 25.000 para quem só
        # havia dito "quero aumentar este limite".
        conferir_valor_do_cliente(
            valor,
            falas_do_cliente(state),
            state.get("limite_pendente_reavaliacao"),
        )
        pedido, avaliacao = processar_pedido_aumento(cliente, valor)
    except ValorNaoInformadoError as erro:
        payload = falha_de(erro, "solicitar_aumento_limite")
        payload["precisa_perguntar"] = True
        return responder(payload, tool_call_id)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro, "solicitar_aumento_limite"), tool_call_id)

    logger.info(
        "<- solicitar_aumento_limite: %s | SolicitacaoAumento=%s",
        avaliacao.status_pedido.value,
        dump_seguro(pedido),
    )
    marcar_desfecho_pedido(avaliacao.status_pedido, avaliacao.limite_solicitado)

    payload = sucesso(
        aprovado=avaliacao.aprovado,
        status=avaliacao.status_pedido,
        limite_solicitado=avaliacao.limite_solicitado,
        limite_maximo_permitido=avaliacao.limite_maximo,
        limite_atual=cliente.limite_atual,
        score_atual=cliente.score_atual,
        # Aprovar registra a decisão do pedido; não muda o limite em vigor. Sai no payload
        # como dado para o agente não prometer ao cliente um limite que ainda não vale.
        limite_ja_aplicado=False,
    )
    return responder(
        payload,
        tool_call_id,
        solicitacao_atual=pedido,
        # Consumido: o pedido acabou de ser avaliado com o score atual, então não há
        # mais o que reoferecer — é o que impede o agente de propor o valor em laço.
        limite_pendente_reavaliacao=None,
    )
