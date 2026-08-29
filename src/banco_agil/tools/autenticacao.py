"""Tools de autenticação do cliente por CPF e data de nascimento."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from banco_agil.services.autenticacao import autenticar
from banco_agil.state import AtendimentoState
from banco_agil.tools.base import falha, falha_de, responder, sucesso


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
    try:
        resultado = autenticar(
            cpf,
            data_nascimento,
            tentativas_atuais=state.get("tentativas_auth", 0),
        )
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    if not resultado.autenticado:
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
            encerrado=resultado.bloqueado,
        )

    cliente = resultado.cliente
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
    )
