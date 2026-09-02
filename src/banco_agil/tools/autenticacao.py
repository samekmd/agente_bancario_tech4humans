"""Tools de autenticação do cliente por CPF e data de nascimento."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.observability.tags import marcar, marcar_cliente
from banco_agil.services.autenticacao import autenticar
from banco_agil.state import AtendimentoState, falas_do_cliente
from banco_agil.tools.base import falha, falha_de, responder, sucesso
from banco_agil.utils.logging import get_logger, mascarar_cpf

logger = get_logger("tools.autenticacao")


@tool
def autenticar_cliente(
    cpf: str,
    data_nascimento: str,
    state: Annotated[AtendimentoState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Confere o CPF e a data de nascimento informados pelo cliente contra a base do banco.

    Use assim que o cliente fornecer os dois dados. O CPF pode vir com ou sem pontuação e
    a data em DD/MM/AAAA. Retorna `ok` indicando se autenticou, o nome do cliente em caso
    de sucesso, e quantas tentativas ainda restam em caso de falha. Quando `bloqueado` for
    verdadeiro, o limite de tentativas acabou e o atendimento precisa ser encerrado com
    cordialidade.
    """
    tentativas_antes = state.get("tentativas_auth", 0)
    # Cada invocação do grafo acrescenta exatamente uma fala do cliente, então a contagem
    # delas identifica o turno. Não é o contador de tentativas — esse vive em
    # `tentativas_auth`; aqui só se pergunta se este turno já foi cobrado.
    turno = len(falas_do_cliente(state))
    ja_contabilizada = state.get("turno_ultima_tentativa_auth") == turno

    # A data de nascimento nunca entra no log: junto com o CPF ela é a credencial.
    logger.info(
        "-> autenticar_cliente(cpf=%s) | tentativas antes=%d, turno=%d, ja contabilizada=%s",
        mascarar_cpf(cpf),
        tentativas_antes,
        turno,
        ja_contabilizada,
    )
    if ja_contabilizada:
        logger.warning(
            "segunda chamada de autenticar_cliente no turno %d; não gasta nova tentativa",
            turno,
        )
    try:
        resultado = autenticar(
            cpf,
            data_nascimento,
            tentativas_atuais=tentativas_antes,
            ja_contabilizada=ja_contabilizada,
        )
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro, "autenticar_cliente"), tool_call_id)

    if not resultado.autenticado:
        logger.warning(
            "<- autenticar_cliente: falhou (%s) | tentativas=%d, restantes=%d, bloqueado=%s",
            resultado.motivo.value if resultado.motivo else "?",
            resultado.tentativas,
            resultado.tentativas_restantes,
            resultado.bloqueado,
        )
        marcar(autenticado=False, motivo_falha_auth=resultado.motivo)
        payload = falha(
            "Os dados não conferem com a nossa base.",
            tentativas_restantes=resultado.tentativas_restantes,
            bloqueado=resultado.bloqueado,
            motivo=resultado.motivo,
        )
        return responder(
            payload,
            tool_call_id,
            tentativas_auth=resultado.tentativas,
            turno_ultima_tentativa_auth=turno,
            encerrado=resultado.bloqueado,
        )

    cliente = resultado.cliente
    logger.info("<- autenticar_cliente: autenticado cpf=%s", mascarar_cpf(cliente.cpf))
    marcar_cliente(cliente.cpf)
    marcar(autenticado=True)
    payload = sucesso(
        nome=cliente.nome,
        primeiro_nome=cliente.nome.split()[0],
        mensagem="Cliente autenticado.",
    )
    return responder(
        payload,
        tool_call_id,
        autenticado=True,
        cpf=cliente.cpf,
        cliente=cliente,
        tentativas_auth=resultado.tentativas,
        turno_ultima_tentativa_auth=turno,
    )
