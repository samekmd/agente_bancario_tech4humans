"""Regra de limite: faixa de score aplicável e decisão de aprovação.

A decisão de aprovar ou rejeitar um aumento nunca fica com o LLM — sai daqui.
"""

import re
from collections.abc import Sequence
from datetime import datetime

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import Cliente, FaixaLimite, ResultadoAvaliacao, SolicitacaoAumento
from banco_agil.observability.tracing import TASK, span
from banco_agil.repositories.score_limite import ScoreLimiteRepository
from banco_agil.repositories.solicitacoes import SolicitacoesRepository
from banco_agil.utils.exceptions import (
    AumentoInvalidoError,
    DadosIndisponiveisError,
    ValorNaoInformadoError,
)
from banco_agil.utils.logging import dump_seguro, get_logger, mascarar_cpf
from banco_agil.utils.validators import validar_valor_monetario

logger = get_logger("services.limite")

# Um número possivelmente monetário no meio de uma frase: dígitos com separadores.
_NUMERO_NO_TEXTO = re.compile(r"\d[\d.,]*")

VALOR_NAO_INFORMADO = (
    "O cliente não disse de quanto quer o limite. Pergunte o valor em números antes "
    "de registrar o pedido."
)


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


def conferir_aumento_real(novo_limite: float, limite_atual: float) -> None:
    """Garante que o valor pedido é de fato maior que o limite em vigor.

    A avaliação compara o valor com o teto da faixa de score, e nunca com o limite que o
    cliente já tem — sem esta guarda, um pedido de R$ 100 para quem tem R$ 5.000 passava
    por "aprovado" e entrava no CSV de solicitações como aumento. Pedir o mesmo valor que
    já se tem também não é aumento, por isso a comparação é estrita.

    Levanta `AumentoInvalidoError`, que o agente verbaliza como um pedido de esclarecimento.
    """
    if novo_limite > limite_atual:
        return

    logger.warning(
        "pedido de R$ %.2f não é aumento sobre o limite atual de R$ %.2f",
        novo_limite,
        limite_atual,
    )
    raise AumentoInvalidoError(
        f"O cliente já tem R$ {limite_atual:.2f} de limite, e pediu R$ {novo_limite:.2f}. "
        "Um aumento precisa ser maior que o limite atual — pergunte para qual valor ele "
        "quer aumentar."
    )


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

    A validação de entrada vem antes do registro, e não contradiz essa ordem: "gravar
    antes de decidir" vale para a *decisão* de aprovar ou rejeitar. Um valor que não é
    aumento não chega a ser um pedido válido, e não deve sujar o CSV de solicitações.
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

    conferir_aumento_real(novo_limite, cliente.limite_atual)

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


def valores_citados(textos: Sequence[str]) -> set[float]:
    """Valores monetários que aparecem no que o cliente escreveu.

    Só o que passa por `validar_valor_monetario` entra: um token ambíguo é descartado aqui
    do mesmo jeito que seria recusado ao virar pedido.
    """
    encontrados: set[float] = set()
    for texto in textos:
        for token in _NUMERO_NO_TEXTO.findall(texto or ""):
            try:
                encontrados.add(validar_valor_monetario(token))
            except Exception:  # noqa: BLE001 - token que não é valor apenas não conta
                continue
    return encontrados


def conferir_valor_do_cliente(
    valor: float,
    textos_do_cliente: Sequence[str],
    valor_pendente: float | None = None,
) -> None:
    """Garante que o valor pedido saiu do cliente, e não da imaginação do modelo.

    Aceita duas procedências: o valor aparece em alguma mensagem que o cliente digitou, ou
    é a reoferta que ele acabou de confirmar (`limite_pendente_reavaliacao`). Fora disso,
    levanta `ValorNaoInformadoError`.

    Existe porque um modelo pediu R$ 25.000 para um cliente que só havia dito "quero
    aumentar este limite" — o número saiu do meio do caminho entre o limite atual e o teto,
    ambos ditos pelo próprio sistema.
    """
    if valor_pendente is not None and valor == valor_pendente:
        return
    if valor in valores_citados(textos_do_cliente):
        return

    logger.warning(
        "valor R$ %.2f não foi dito pelo cliente; citados: %s, pendente: %s",
        valor,
        sorted(valores_citados(textos_do_cliente)),
        valor_pendente,
    )
    raise ValorNaoInformadoError(VALOR_NAO_INFORMADO)
