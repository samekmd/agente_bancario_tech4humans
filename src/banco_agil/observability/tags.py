"""Tags no trace raiz, para filtrar execuções no UI do MLflow.

Cada função é uma pergunta que se quer fazer no UI: quais atendimentos foram deste cliente,
quais passaram pelo crédito, quais terminaram em pedido rejeitado, quais deram erro.
"""

from typing import Any

from banco_agil.observability.setup import tracing_ativo
from banco_agil.utils.logging import get_logger, mascarar_cpf

logger = get_logger("observability.tags")


def marcar(**tags: Any) -> None:  # noqa: ANN401 - valores viram texto na tag
    """Aplica tags ao trace raiz da execução em curso.

    Valores `None` são descartados. Nunca levanta: falha de tracing não pode interromper
    atendimento, então uma tag perdida vira no máximo uma linha de debug no log.
    """
    if not tracing_ativo():
        return

    limpas = {chave: str(valor) for chave, valor in tags.items() if valor is not None}
    if not limpas:
        return

    try:
        import mlflow

        mlflow.update_current_trace(tags=limpas)
    except Exception:
        logger.debug("não consegui aplicar as tags %s", sorted(limpas), exc_info=True)


def marcar_cliente(cpf: str | None) -> None:
    """Marca de quem é o atendimento, com o CPF mascarado.

    Mesma decisão já tomada para o log: o documento inteiro não entra. Um trace é dado
    armazenado e navegável por quem tiver acesso ao UI.
    """
    marcar(cliente=mascarar_cpf(cpf))


def marcar_agente(agente: Any) -> None:  # noqa: ANN401 - aceita o enum Agente ou texto
    """Marca qual especialidade atendeu, para filtrar por agente no UI."""
    marcar(agente=getattr(agente, "value", agente))


def marcar_desfecho_pedido(status: Any, limite_solicitado: float | None = None) -> None:  # noqa: ANN401
    """Marca o resultado de um pedido de aumento: aprovado, rejeitado ou pendente."""
    marcar(
        desfecho_pedido=getattr(status, "value", status),
        limite_solicitado=limite_solicitado,
    )


def marcar_entrevista(score_anterior: int, score_novo: int) -> None:
    """Marca que houve entrevista e se ela melhorou o perfil do cliente."""
    marcar(
        entrevista="concluida",
        entrevista_melhorou=score_novo > score_anterior,
        score_anterior=score_anterior,
        score_novo=score_novo,
    )


def marcar_erro(mensagem: str, origem: str = "") -> None:
    """Marca que a execução teve erro tratado, para achá-la depois no UI."""
    marcar(erro=mensagem, erro_origem=origem or None)
