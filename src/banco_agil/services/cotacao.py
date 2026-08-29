"""Regra de cotação de câmbio: consulta à fonte externa e conversão de valores.

Se a cotação não puder ser obtida, levanta `CotacaoIndisponivelError`. Nunca devolve
valor estimado ou inventado.
"""

import re
import time
from datetime import UTC, datetime

import httpx

from banco_agil.domain.models import Cotacao
from banco_agil.utils.exceptions import CotacaoIndisponivelError, EntradaInvalidaError
from banco_agil.utils.logging import get_logger
from banco_agil.utils.validators import arredondar

FONTE = "AwesomeAPI"
PAR_PADRAO = "USD-BRL"
BACKOFF_BASE_S = 0.5

_PAR = re.compile(r"^[A-Z]{3}-[A-Z]{3}$")

logger = get_logger(__name__)


def normalizar_par(par: str) -> str:
    """Normaliza o par de moedas para o formato `XXX-YYY`.

    Levanta `EntradaInvalidaError` se o par não tiver esse formato.
    """
    normalizado = (par or "").strip().upper()
    if not _PAR.match(normalizado):
        raise EntradaInvalidaError("Par de moedas inválido. Use o formato USD-BRL.")
    return normalizado


def _para_modelo(par: str, dados: dict[str, str]) -> Cotacao:
    """Traduz o payload da AwesomeAPI para o modelo de domínio."""
    return Cotacao(
        par=par,
        moeda_origem=dados["code"],
        moeda_destino=dados["codein"],
        compra=float(dados["bid"]),
        venda=float(dados["ask"]),
        atualizado_em=datetime.fromtimestamp(int(dados["timestamp"]), tz=UTC),
        fonte=FONTE,
    )


def obter_cotacao(
    par: str = PAR_PADRAO,
    client: httpx.Client | None = None,
    base_url: str | None = None,
    timeout_s: float | None = None,
    max_retries: int | None = None,
) -> Cotacao:
    """Consulta a cotação atual do par de moedas na fonte externa.

    Tenta `max_retries + 1` vezes, com backoff exponencial entre as tentativas. Erros de
    rede e respostas 5xx são retentados; 4xx (par inexistente) não, por não ser transitório.
    Levanta `CotacaoIndisponivelError` quando todas as tentativas falham.
    """
    if base_url is None or timeout_s is None or max_retries is None:
        from banco_agil.config import get_settings

        settings = get_settings()
        base_url = base_url if base_url is not None else settings.cotacao_base_url
        timeout_s = timeout_s if timeout_s is not None else settings.cotacao_timeout_s
        max_retries = max_retries if max_retries is not None else settings.cotacao_max_retries

    par_normalizado = normalizar_par(par)
    url = f"{base_url.rstrip('/')}/{par_normalizado}"
    chave = par_normalizado.replace("-", "")

    proprio_client = client is None
    client = client or httpx.Client(timeout=timeout_s)
    try:
        for tentativa in range(max_retries + 1):
            try:
                resposta = client.get(url, timeout=timeout_s)
                resposta.raise_for_status()
                return _para_modelo(par_normalizado, resposta.json()[chave])
            except httpx.HTTPStatusError as erro:
                logger.warning("cotacao: %s respondeu %s", url, erro.response.status_code)
                if erro.response.status_code < 500:
                    raise CotacaoIndisponivelError(
                        f"Não consegui consultar a cotação de {par_normalizado} agora."
                    ) from erro
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as erro:
                logger.warning("cotacao: falha ao consultar %s (%s)", url, erro)

            if tentativa < max_retries:
                time.sleep(BACKOFF_BASE_S * (2**tentativa))
    finally:
        if proprio_client:
            client.close()

    raise CotacaoIndisponivelError(f"Não consegui consultar a cotação de {par_normalizado} agora.")


def converter(valor: float, cotacao: Cotacao) -> float:
    """Converte um valor da moeda de origem para a de destino, pelo preço de compra."""
    return arredondar(valor * cotacao.compra)


def converter_inverso(valor: float, cotacao: Cotacao) -> float:
    """Converte um valor da moeda de destino para a de origem, pelo preço de venda."""
    return arredondar(valor / cotacao.venda)


def converter_entre_moedas(
    valor: float,
    de_moeda: str,
    para_moeda: str,
    client: httpx.Client | None = None,
) -> tuple[float, Cotacao]:
    """Converte um valor entre duas moedas, escolhendo o par que a fonte publica.

    A AwesomeAPI cota `XXX-BRL`; para o sentido inverso (real para moeda estrangeira)
    consulta o mesmo par e divide pelo preço de venda. Devolve o valor convertido e a
    cotação usada, para o agente poder citar a taxa.
    """
    origem = (de_moeda or "").strip().upper()
    destino = (para_moeda or "").strip().upper()
    if origem == destino:
        raise EntradaInvalidaError("As moedas de origem e destino são a mesma.")

    if origem == "BRL":
        cotacao = obter_cotacao(f"{destino}-{origem}", client=client)
        return converter_inverso(valor, cotacao), cotacao

    cotacao = obter_cotacao(f"{origem}-{destino}", client=client)
    return converter(valor, cotacao), cotacao
