"""Tools de câmbio: cotação e conversão de valores."""

from typing import Annotated

from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command

from banco_agil.services.cotacao import converter_entre_moedas, obter_cotacao
from banco_agil.tools.base import falha_de, responder, sucesso
from banco_agil.utils.validators import validar_valor_monetario


@tool
def consultar_cotacao(
    par: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Consulta a cotação atual de um par de moedas, no formato `USD-BRL`.

    Use quando o cliente perguntar quanto está o dólar, o euro ou outra moeda. Retorna o
    preço de compra e de venda e o horário da última atualização. Se a cotação não puder
    ser obtida, retorna `ok: false` — nesse caso informe o cliente e não estime valores.
    """
    try:
        cotacao = obter_cotacao(par)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    payload = sucesso(
        par=cotacao.par,
        compra=cotacao.compra,
        venda=cotacao.venda,
        atualizado_em=cotacao.atualizado_em,
        fonte=cotacao.fonte,
    )
    return responder(payload, tool_call_id)


@tool
def converter_valor(
    valor: str,
    de_moeda: str,
    para_moeda: str,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Converte um valor entre duas moedas pela cotação do momento.

    As moedas vêm no código de três letras (`USD`, `BRL`, `EUR`). Use quando o cliente
    pedir o equivalente de um valor em outra moeda. Retorna o valor convertido e a taxa
    usada, para você poder citá-la.
    """
    try:
        quantia = validar_valor_monetario(valor)
        convertido, cotacao = converter_entre_moedas(quantia, de_moeda, para_moeda)
    except Exception as erro:  # noqa: BLE001 - nenhuma tool levanta exceção para o grafo
        return responder(falha_de(erro), tool_call_id)

    payload = sucesso(
        valor_original=quantia,
        de_moeda=de_moeda.strip().upper(),
        para_moeda=para_moeda.strip().upper(),
        valor_convertido=convertido,
        par_consultado=cotacao.par,
        compra=cotacao.compra,
        venda=cotacao.venda,
        atualizado_em=cotacao.atualizado_em,
        fonte=cotacao.fonte,
    )
    return responder(payload, tool_call_id)
