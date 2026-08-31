"""Regra da entrevista de crédito: quais campos faltam e como normalizar cada resposta.

O Python decide qual dos cinco campos perguntar; o LLM só extrai o valor da fala. A
ordem das perguntas é fixa e nenhuma é pulada.
"""

import re
import unicodedata
from collections.abc import Mapping

from banco_agil.domain.enums import TipoEmprego
from banco_agil.domain.models import Cliente, DadosEntrevista
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.services.score import calcular_score
from banco_agil.utils.exceptions import EntradaInvalidaError, RespostaNaoSolicitadaError
from banco_agil.utils.logging import get_logger, mascarar_cpf
from banco_agil.utils.validators import validar_valor_monetario

logger = get_logger("services.entrevista")

# O que o LLM extrai da fala (sempre texto, na prática) e o que fica guardado no slot.
ValorBruto = str | float | int | bool | TipoEmprego
ValorSlot = float | int | bool | TipoEmprego
Slots = Mapping[str, ValorSlot | None]

CAMPOS: tuple[str, ...] = (
    "renda_mensal",
    "despesas_mensais",
    "tipo_emprego",
    "num_dependentes",
    "tem_dividas",
)

PERGUNTAS: dict[str, str] = {
    "renda_mensal": "qual é a renda mensal do cliente",
    "despesas_mensais": "qual é o total de despesas mensais do cliente",
    "tipo_emprego": "qual das três opções descreve o vínculo de trabalho do cliente",
    "num_dependentes": "quantos dependentes o cliente tem — peça um número, sendo 0 nenhum",
    "tem_dividas": "se o cliente tem dívidas em aberto",
}

# Campos de resposta fechada. A lista mora aqui, ao lado de quem valida, para que a
# pergunta feita ao cliente não possa divergir do que o normalizador aceita.
OPCOES: dict[str, tuple[str, ...]] = {
    "tipo_emprego": ("formal", "autônomo", "desempregado"),
    "tem_dividas": ("sim", "não"),
}

_PONTUACAO_DE_BORDA = ".,;:!?'\"()[]"

# Substantivo que costuma acompanhar a contagem sem torná-la ambígua. Lista fechada:
# qualquer outra palavra sobrevive à limpeza e faz o valor ser recusado.
_DECORACAO_DEPENDENTES = re.compile(
    r"dependentes|dependente|filhos|filho|filhas|filha|pessoas|pessoa|criancas|crianca"
)

# Contagem inteira, aceitando `3,0`/`3.0` como o inteiro que são. `\d` não casa `_`, o que
# fecha a brecha do `int("1_000")`.
_CONTAGEM = re.compile(r"^\d+([.,]0+)?$")

NUMERO_ILEGIVEL = (
    "Não entendi o número de dependentes. Responda com um número, por exemplo 0, 1 ou 2."
)

_AFIRMATIVOS = {"sim", "s", "true", "verdadeiro", "tenho", "possuo", "1"}
_NEGATIVOS = {"nao", "n", "false", "falso", "nenhuma", "nenhum", "0"}

_EMPREGOS: dict[str, TipoEmprego] = {
    "formal": TipoEmprego.FORMAL,
    "autonomo": TipoEmprego.AUTONOMO,
    "autonoma": TipoEmprego.AUTONOMO,
    "desempregado": TipoEmprego.DESEMPREGADO,
    "desempregada": TipoEmprego.DESEMPREGADO,
}


def _normalizar_texto(texto: str) -> str:
    """Tira acento, caixa, espaços e pontuação de borda: `"Autônomo."` vira `autonomo`."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return sem_acento.strip().strip(_PONTUACAO_DE_BORDA).strip().lower()


def _inteiro_de(valor: ValorBruto) -> int:
    """Converte uma contagem para `int`, aceitando só o que é inequívoco.

    Levanta `EntradaInvalidaError` para texto com palavra desconhecida, número fracionário
    ou booleano. `bool` é testado primeiro de propósito: em Python é subclasse de `int`, e
    sem essa guarda `True` viraria 1.
    """
    if isinstance(valor, bool):
        raise EntradaInvalidaError(NUMERO_ILEGIVEL)

    if isinstance(valor, int):
        return valor

    if isinstance(valor, float):
        if not valor.is_integer():
            raise EntradaInvalidaError(NUMERO_ILEGIVEL)
        return int(valor)

    texto = _DECORACAO_DEPENDENTES.sub("", _normalizar_texto(str(valor or ""))).strip()
    if not _CONTAGEM.match(texto):
        raise EntradaInvalidaError(NUMERO_ILEGIVEL)
    return int(texto.split(",")[0].split(".")[0])


def proximo_campo(slots: Slots) -> str | None:
    """Retorna o primeiro campo ainda não preenchido, ou `None` se a entrevista acabou."""
    for campo in CAMPOS:
        if slots.get(campo) is None:
            return campo
    return None


def slots_completos(slots: Slots) -> bool:
    """Indica se os cinco campos da entrevista já foram preenchidos."""
    return proximo_campo(slots) is None


def normalizar_valor(campo: str, valor: ValorBruto) -> ValorSlot:
    """Converte a resposta do cliente para o tipo do campo.

    Levanta `EntradaInvalidaError` para campo desconhecido ou valor que não se encaixa.
    """
    logger.debug("normalizando campo=%s valor bruto=%r (%s)", campo, valor, type(valor).__name__)

    if campo not in CAMPOS:
        logger.warning("campo de entrevista desconhecido: %r", campo)
        raise EntradaInvalidaError(f"Campo de entrevista desconhecido: {campo}.")

    if campo in ("renda_mensal", "despesas_mensais"):
        numero = validar_valor_monetario(valor)
        logger.info("campo %s normalizado: %r -> %.2f", campo, valor, numero)
        return numero

    if campo == "tipo_emprego":
        if isinstance(valor, TipoEmprego):
            logger.info("campo tipo_emprego já veio tipado: %s", valor.value)
            return valor
        chave = _normalizar_texto(str(valor))
        emprego = _EMPREGOS.get(chave)
        if emprego is None:
            logger.warning(
                "vínculo recusado: %r (normalizado para %r); aceitos: %s",
                valor,
                chave,
                sorted(_EMPREGOS),
            )
            raise EntradaInvalidaError("Vínculo inválido. Use formal, autônomo ou desempregado.")
        logger.info("campo tipo_emprego normalizado: %r -> %s", valor, emprego.value)
        return emprego

    if campo == "num_dependentes":
        try:
            numero_dep = _inteiro_de(valor)
        except EntradaInvalidaError:
            logger.warning("número de dependentes ilegível: %r (%s)", valor, type(valor).__name__)
            raise
        if numero_dep < 0:
            logger.warning("número de dependentes negativo: %r", valor)
            raise EntradaInvalidaError(NUMERO_ILEGIVEL)
        logger.info("campo num_dependentes normalizado: %r -> %d", valor, numero_dep)
        return numero_dep

    if isinstance(valor, bool):
        logger.info("campo tem_dividas já veio tipado: %s", valor)
        return valor
    texto = _normalizar_texto(str(valor))
    if texto in _AFIRMATIVOS:
        logger.info("campo tem_dividas normalizado: %r -> True", valor)
        return True
    if texto in _NEGATIVOS:
        logger.info("campo tem_dividas normalizado: %r -> False", valor)
        return False
    logger.warning("resposta de dívidas não reconhecida: %r (normalizada para %r)", valor, texto)
    raise EntradaInvalidaError("Não entendi se há dívidas em aberto. Responda sim ou não.")


def conferir_pergunta_feita(campo: str, campo_perguntado: str | None) -> None:
    """Garante que o campo a registrar é o que foi perguntado ao cliente.

    Sem esta conferência, o LLM pode preencher um slot com valor tirado do histórico da
    conversa em vez da resposta do cliente — foi assim que uma renda de R$ 8.000 entrou na
    entrevista sem ninguém perguntar. Levanta `RespostaNaoSolicitadaError`.
    """
    if campo_perguntado is None:
        raise RespostaNaoSolicitadaError(
            f"Ainda não perguntei sobre {campo} ao cliente. Faça a pergunta e aguarde a resposta."
        )
    if campo != campo_perguntado:
        raise RespostaNaoSolicitadaError(
            f"A pergunta feita ao cliente foi sobre {campo_perguntado}, não {campo}. "
            "Registre a resposta do campo perguntado."
        )


def registrar_slot(slots: Slots, campo: str, valor: ValorBruto) -> dict[str, ValorSlot]:
    """Devolve uma cópia dos slots com o campo preenchido e normalizado."""
    logger.info(
        "registrando slot %s | preenchidos antes: %s",
        campo,
        sorted(k for k in slots if slots[k] is not None),
    )
    novos = {**slots, campo: normalizar_valor(campo, valor)}
    logger.info(
        "slots agora: %s | próximo campo: %s",
        {k: str(v) for k, v in novos.items()},
        proximo_campo(novos),
    )
    return novos


def montar_dados(slots: Slots) -> DadosEntrevista:
    """Converte os slots preenchidos no modelo de entrada da fórmula de score.

    Levanta `EntradaInvalidaError` se algum campo ainda estiver faltando.
    """
    faltando = proximo_campo(slots)
    if faltando is not None:
        logger.warning(
            "montar_dados abortado: falta o campo %s | slots=%s",
            faltando,
            {k: str(v) for k, v in slots.items()},
        )
        raise EntradaInvalidaError(f"A entrevista ainda não tem o campo {faltando}.")

    bruto = {campo: slots[campo] for campo in CAMPOS}
    logger.debug(
        "construindo DadosEntrevista a partir de %s", {k: str(v) for k, v in bruto.items()}
    )
    dados = DadosEntrevista(**bruto)
    logger.info("DadosEntrevista criado: %s", dados.model_dump(mode="json"))
    return dados


def concluir_entrevista(
    cliente: Cliente,
    slots: Slots,
    repo: ClientesRepository | None = None,
) -> Cliente:
    """Recalcula o score a partir da entrevista, persiste e devolve o cliente atualizado."""
    logger.info(
        "concluindo entrevista de cpf=%s | score atual=%d",
        mascarar_cpf(cliente.cpf),
        cliente.score_atual,
    )
    dados = montar_dados(slots)
    novo_score = calcular_score(dados)
    atualizado = (repo or ClientesRepository()).atualizar_score(cliente.cpf, novo_score)
    logger.info(
        "entrevista concluída: score %d -> %d (%s)",
        cliente.score_atual,
        atualizado.score_atual,
        "melhorou" if atualizado.score_atual > cliente.score_atual else "não melhorou",
    )
    return atualizado
