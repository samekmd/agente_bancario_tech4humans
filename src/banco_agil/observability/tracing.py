"""Spans manuais para os pontos cegos do autolog.

`mlflow.langchain.autolog()` enxerga o que passa por LangChain e LangGraph: nós, tool calls,
tokens. Fica de fora justamente a metade determinística deste projeto — roteamento, fórmula
de score, decisão de limite, autenticação, leitura e escrita de CSV, chamada HTTP de cotação.
É o que estes spans cobrem.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Protocol

from banco_agil.observability.setup import tracing_ativo
from banco_agil.utils.logging import get_logger

logger = get_logger("observability.tracing")

# Tipos de span usados no projeto, como texto para não importar o MLflow neste módulo.
CHAIN = "CHAIN"
TOOL = "TOOL"
TASK = "TASK"


class Span(Protocol):
    """O mínimo que o código instrumentado usa de um span."""

    def set_inputs(self, inputs: Any) -> Any: ...  # noqa: ANN401 - assinatura do MLflow

    def set_outputs(self, outputs: Any) -> Any: ...  # noqa: ANN401 - assinatura do MLflow

    def set_attributes(self, attributes: dict[str, Any]) -> Any: ...  # noqa: ANN401


class _SpanInerte:
    """Span que não faz nada, entregue quando o tracing está desligado.

    Existe para que o ponto de chamada nunca precise de `if span is not None`: a
    instrumentação fica legível e o service continua lendo como regra de negócio.
    """

    def set_inputs(self, inputs: Any) -> None:  # noqa: ANN401 - assinatura do MLflow
        return None

    def set_outputs(self, outputs: Any) -> None:  # noqa: ANN401 - assinatura do MLflow
        return None

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        return None


INERTE = _SpanInerte()


@contextmanager
def span(nome: str, tipo: str = "UNKNOWN", **entradas: Any) -> Iterator[Span]:  # noqa: ANN401
    """Abre um span manual, entregando um objeto sempre utilizável.

    Com o tracing desligado — ou se o MLflow falhar ao abrir o span — entrega um span
    inerte e segue em frente. Exceção levantada **dentro** do bloco continua subindo
    normalmente: o span registra o erro, mas observabilidade nunca engole erro de negócio.
    """
    if not tracing_ativo():
        yield INERTE
        return

    try:
        import mlflow

        gerenciador = mlflow.start_span(name=nome, span_type=tipo)
        aberto = gerenciador.__enter__()
    except Exception:
        logger.debug("não consegui abrir o span %r; seguindo sem tracing", nome, exc_info=True)
        yield INERTE
        return

    try:
        if entradas:
            aberto.set_inputs(entradas)
        yield aberto
    except BaseException as erro:
        gerenciador.__exit__(type(erro), erro, erro.__traceback__)
        raise
    else:
        gerenciador.__exit__(None, None, None)
