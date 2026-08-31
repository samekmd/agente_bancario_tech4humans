"""Regra de limite: faixa de score aplicável e decisão de aprovação.

A decisão de aprovar ou rejeitar um aumento nunca fica com o LLM — sai daqui.
"""

from collections.abc import Sequence
from datetime import datetime

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import Cliente, FaixaLimite, ResultadoAvaliacao, SolicitacaoAumento
from banco_agil.observability.tracing import TASK, span
from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.utils.exceptions import DadosIndisponiveisError
from banco_agil.utils.logging import dump_seguro, get_logger, mascarar_cpf

logger = get_logger("services.limite")


def faixa_para_score(score: int, faixas: Sequence[FaixaLimite]) -> FaixaLimite:
    """Retorna a faixa que contém o score, com `score_max` inclusivo.

    Levanta `DadosIndisponiveisError` se nenhuma faixa cobrir o score — o que significa
    base de faixas malformada, já que o contrato exige cobertura contínua de 0 a 1000.
    """
    for faixa in faixas:
        if faixa.score_min <= score <= faixa.score_max:
            logger.debug(
                "score %d cai na faixa %d-%d, teto R$ %.2f",
                score,
                faixa.score_min,
                faixa.score_max,
                faixa.limite_maximo,
            )
            return faixa
    logger.error(
        "nenhuma faixa cobre o score %d | faixas carregadas: %s",
        score,
        [(f.score_min, f.score_max) for f in faixas],
    )
    raise DadosIndisponiveisError(f"Nenhuma faixa de limite cobre o score {score}.")


def limite_maximo_permitido(
    score: int,
    faixas: Sequence[FaixaLimite] | None = None,
    repo: ScoreLimiteRepository | None = None,
) -> float:
    """Limite máximo autorizado para o score informado.

    Recebe as faixas já carregadas ou o repositório de onde lê-las.
    """
    if faixas is None:
        faixas = (repo or ScoreLimiteRepository()).listar_faixas()
    return faixa_para_score(score, faixas).limite_maximo


def avaliar_aumento(
    score: int,
    limite_solicitado: float,
    faixas: Sequence[FaixaLimite] | None = None,
    repo: ScoreLimiteRepository | None = None,
) -> ResultadoAvaliacao:
    """Decide um pedido de aumento: aprovado se o valor couber na faixa do score.

    Recebe as faixas já carregadas ou o repositório de onde lê-las.
    """
    if faixas is None:
        faixas = (repo or ScoreLimiteRepository()).listar_faixas()

    with span("avaliar_aumento", TASK, score=score, limite_solicitado=limite_solicitado) as obs:
        return _avaliar(score, limite_solicitado, faixas, obs)


def _avaliar(
    score: int,
    limite_solicitado: float,
    faixas: Sequence[FaixaLimite],
    observado: object,
) -> ResultadoAvaliacao:
    maximo = limite_maximo_permitido(score, faixas)
    aprovado = limite_solicitado <= maximo
    resultado = ResultadoAvaliacao(
        aprovado=aprovado,
        status_pedido=StatusPedido.APROVADO if aprovado else StatusPedido.REJEITADO,
        score_considerado=score,
        limite_maximo=maximo,
        limite_solicitado=limite_solicitado,
    )
    logger.info(
        "avaliação: score=%d, solicitado=R$ %.2f, teto=R$ %.2f -> %s | ResultadoAvaliacao=%s",
        score,
        limite_solicitado,
        maximo,
        resultado.status_pedido.value,
        resultado.model_dump(mode="json"),
    )
    observado.set_outputs(resultado.model_dump(mode="json"))
    return resultado


def valor_para_nova_tentativa(solicitacao: SolicitacaoAumento | None) -> float | None:
    """Valor que vale a pena reoferecer ao cliente depois da entrevista.

    Só um pedido rejeitado merece nova tentativa: um aprovado não se reabre, e não havendo
    pedido não há o que reoferecer. Quem chama guarda o resultado no estado, e é a presença
    dele que autoriza o agente de crédito a propor o mesmo valor de novo — sem isso ele
    perguntaria o valor do zero, ou reoferecia em laço.
    """
    if solicitacao is None or solicitacao.status_pedido is not StatusPedido.REJEITADO:
        return None
    return solicitacao.novo_limite_solicitado


def processar_pedido_aumento(
    cliente: Cliente,
    novo_limite: float,
    faixas: Sequence[FaixaLimite] | None = None,
    repo_score: ScoreLimiteRepository | None = None,
    repo_solicitacoes: SolicitacoesRepository | None = None,
    agora: datetime | None = None,
) -> tuple[SolicitacaoAumento, ResultadoAvaliacao]:
    """Registra o pedido como pendente, avalia e atualiza a linha com o desfecho.

    A ordem é a do CLAUDE.md: o pedido é gravado antes da decisão, para que fique
    registrado mesmo que a avaliação falhe. Devolve a solicitação já com o status final
    e a avaliação que o produziu.
    """
    repo_pedidos = repo_solicitacoes or SolicitacoesRepository()
    momento = agora or datetime.now()
    logger.info(
        "pedido de aumento: cpf=%s, limite atual=R$ %.2f, solicitado=R$ %.2f, score=%d",
        mascarar_cpf(cliente.cpf),
        cliente.limite_atual,
        novo_limite,
        cliente.score_atual,
    )

    solicitacao = SolicitacaoAumento(
        cpf_cliente=cliente.cpf,
        data_hora_solicitacao=momento,
        limite_atual=cliente.limite_atual,
        novo_limite_solicitado=novo_limite,
        status_pedido=StatusPedido.PENDENTE,
    )
    logger.info("[1/3] SolicitacaoAumento criada: %s", dump_seguro(solicitacao))

    pedido = repo_pedidos.registrar(solicitacao)
    logger.info("[2/3] pedido gravado como pendente, avaliando")

    avaliacao = avaliar_aumento(cliente.score_atual, novo_limite, faixas=faixas, repo=repo_score)
    decidido = repo_pedidos.atualizar_status(
        pedido.cpf_cliente, pedido.data_hora_solicitacao, avaliacao.status_pedido
    )
    logger.info("[3/3] linha atualizada para %s", decidido.status_pedido.value)
    return decidido, avaliacao
