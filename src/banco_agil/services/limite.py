"""Regra de limite: faixa de score aplicável e decisão de aprovação.

A decisão de aprovar ou rejeitar um aumento nunca fica com o LLM — sai daqui.
"""

from collections.abc import Sequence
from datetime import datetime

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import Cliente, FaixaLimite, ResultadoAvaliacao, SolicitacaoAumento
from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.utils.exceptions import DadosIndisponiveisError


def faixa_para_score(score: int, faixas: Sequence[FaixaLimite]) -> FaixaLimite:
    """Retorna a faixa que contém o score, com `score_max` inclusivo.

    Levanta `DadosIndisponiveisError` se nenhuma faixa cobrir o score — o que significa
    base de faixas malformada, já que o contrato exige cobertura contínua de 0 a 1000.
    """
    for faixa in faixas:
        if faixa.score_min <= score <= faixa.score_max:
            return faixa
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

    maximo = limite_maximo_permitido(score, faixas)
    aprovado = limite_solicitado <= maximo
    return ResultadoAvaliacao(
        aprovado=aprovado,
        status_pedido=StatusPedido.APROVADO if aprovado else StatusPedido.REJEITADO,
        score_considerado=score,
        limite_maximo=maximo,
        limite_solicitado=limite_solicitado,
    )


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

    pedido = repo_pedidos.registrar(
        SolicitacaoAumento(
            cpf_cliente=cliente.cpf,
            data_hora_solicitacao=momento,
            limite_atual=cliente.limite_atual,
            novo_limite_solicitado=novo_limite,
            status_pedido=StatusPedido.PENDENTE,
        )
    )

    avaliacao = avaliar_aumento(cliente.score_atual, novo_limite, faixas=faixas, repo=repo_score)
    decidido = repo_pedidos.atualizar_status(
        pedido.cpf_cliente, pedido.data_hora_solicitacao, avaliacao.status_pedido
    )
    return decidido, avaliacao
