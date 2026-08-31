"""Configuração do MLflow: tracking URI, experimento e autolog do LangGraph.

Único ponto que fala com o MLflow para configurá-lo. Chamado uma vez por processo, ao lado
do `configurar_logging()`.
"""

import os

from banco_agil.utils.logging import get_logger

logger = get_logger("observability.setup")

_ativo = False
_configurado = False


def configurar_mlflow(tracking_uri: str | None = None, experimento: str | None = None) -> bool:
    """Aponta o MLflow para o servidor, escolhe o experimento e liga o autolog.

    Idempotente: chamadas repetidas não reconfiguram nada. Devolve se o tracing ficou ativo.

    **Nunca levanta.** Servidor fora do ar, URI inválida ou qualquer falha do MLflow viram
    um aviso no log e tracing desligado pelo resto do processo — observabilidade não pode
    derrubar atendimento.
    """
    global _ativo, _configurado
    if _configurado:
        return _ativo

    from banco_agil.config import get_settings

    settings = get_settings()
    _configurado = True

    if not settings.mlflow_habilitado:
        logger.info("tracing do MLflow desligado por configuração")
        return False

    uri = tracking_uri or settings.mlflow_tracking_uri
    nome = experimento or settings.mlflow_experimento

    # Precisa vir antes de importar o cliente: sem isso, um servidor fora do ar deixa o
    # MLflow em retry por minutos, e o cliente fica esperando a resposta do atendimento.
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", str(int(settings.mlflow_timeout_s)))
    os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", str(settings.mlflow_max_retries))

    try:
        import mlflow

        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(nome)
        # Cobre o grafo inteiro: nós, tool calls, tokens e custo, agrupados pelo
        # `thread_id` que já vai no `config_execucao()`.
        mlflow.langchain.autolog()
    except Exception as erro:
        # Servidor desligado é situação normal em desenvolvimento: um aviso curto basta, e
        # o traceback fica no nível de debug para quem estiver investigando de fato.
        logger.warning(
            "tracing do MLflow indisponível em %s (%s); o atendimento segue sem observabilidade",
            uri,
            type(erro).__name__,
        )
        logger.debug("detalhe da falha do MLflow", exc_info=True)
        return False

    _ativo = True
    logger.info("tracing do MLflow ativo em %s, experimento %r", uri, nome)
    return True


def tracing_ativo() -> bool:
    """Indica se há tracing ligado. Consultado por `tracing.py` e `tags.py`.

    Enquanto for falso, nenhuma função de observabilidade toca o MLflow — nem para abrir
    span, nem para gravar tag. Sem essa guarda, um `start_span` solto criaria banco local
    em disco só por existir.
    """
    return _ativo


def desativar_tracing() -> None:
    """Desliga o tracing no processo. Existe para os testes rodarem offline."""
    global _ativo, _configurado
    _ativo = False
    _configurado = True
