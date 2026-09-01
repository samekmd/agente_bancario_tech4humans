"""Configuração do MLflow: tracking URI, experimento e autolog do LangGraph.

Único ponto que fala com o MLflow para configurá-lo. Chamado a cada mensagem do cliente:
uma vez ativo, retorna de imediato; se o servidor estiver fora do ar, tenta de novo mais
tarde, para que subir o `make mlflow` no meio da conversa passe a gravar sem reiniciar o
app.
"""

import os
import time
from collections.abc import Callable

from banco_agil.utils.logging import get_logger

logger = get_logger("observability.setup")

# Espera entre tentativas de conexão. Sem ela, um servidor fora do ar custaria o timeout
# do MLflow a cada mensagem, e o cliente pagaria por isso na latência da resposta.
ESPERA_ENTRE_TENTATIVAS_S = 30.0

_ativo = False
_resolvido = False
_ultima_tentativa: float | None = None


def configurar_mlflow(
    tracking_uri: str | None = None,
    experimento: str | None = None,
    agora: Callable[[], float] = time.monotonic,
) -> bool:
    """Aponta o MLflow para o servidor, escolhe o experimento e liga o autolog.

    Devolve se o tracing ficou ativo. Sucesso e desligamento por configuração são
    definitivos; **falha de conexão não é** — ela só adia a próxima tentativa por
    `ESPERA_ENTRE_TENTATIVAS_S`. Foi o que faltou uma vez: o app subiu segundos antes do
    servidor MLflow, marcou a falha como definitiva, e ficou sem gravar nada até alguém
    reiniciar o Streamlit.

    **Nunca levanta.** Servidor fora do ar ou URI inválida viram aviso no log e tracing
    desligado — observabilidade não pode derrubar atendimento.
    """
    global _ativo, _resolvido, _ultima_tentativa
    if _resolvido:
        return _ativo

    from banco_agil.config import get_settings

    settings = get_settings()

    if not settings.mlflow_habilitado:
        # Decisão explícita de quem configurou: não há o que retentar.
        _resolvido = True
        logger.info("tracing do MLflow desligado por configuração")
        return False

    instante = agora()
    if _ultima_tentativa is not None and instante - _ultima_tentativa < ESPERA_ENTRE_TENTATIVAS_S:
        return False
    primeira_tentativa = _ultima_tentativa is None
    _ultima_tentativa = instante

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
        # `thread_id` que já vai no `config_execucao()`. Funciona mesmo ligado depois de o
        # grafo ter sido construído — o autolog age sobre as classes do LangChain.
        mlflow.langchain.autolog()
    except Exception as erro:
        # Servidor desligado é situação normal em desenvolvimento: um aviso curto basta, e
        # o traceback fica no nível de debug para quem estiver investigando de fato.
        logger.warning(
            "tracing do MLflow indisponível em %s (%s); seguindo sem observabilidade, "
            "nova tentativa em %.0fs",
            uri,
            type(erro).__name__,
            ESPERA_ENTRE_TENTATIVAS_S,
        )
        logger.debug("detalhe da falha do MLflow", exc_info=True)
        return False

    _ativo = True
    _resolvido = True
    if primeira_tentativa:
        logger.info("tracing do MLflow ativo em %s, experimento %r", uri, nome)
    else:
        logger.info("tracing do MLflow reconectado em %s; a partir daqui há traces", uri)
    return True


def tracing_ativo() -> bool:
    """Indica se há tracing ligado. Consultado por `tracing.py` e `tags.py`.

    Enquanto for falso, nenhuma função de observabilidade toca o MLflow — nem para abrir
    span, nem para gravar tag. Sem essa guarda, um `start_span` solto criaria banco local
    em disco só por existir.
    """
    return _ativo


def desativar_tracing() -> None:
    """Desliga o tracing no processo, de forma definitiva. Usado pelos testes."""
    global _ativo, _resolvido, _ultima_tentativa
    _ativo = False
    _resolvido = True
    _ultima_tentativa = None
