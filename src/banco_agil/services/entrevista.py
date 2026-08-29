"""Regra da entrevista de crédito: quais campos faltam e como normalizar cada resposta.

O Python decide qual dos cinco campos perguntar; o LLM só extrai o valor da fala. A
ordem das perguntas é fixa e nenhuma é pulada.
"""

import unicodedata
from collections.abc import Mapping

from banco_agil.domain.enums import TipoEmprego
from banco_agil.domain.models import Cliente, DadosEntrevista
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.services.score import calcular_score
from banco_agil.utils.exceptions import EntradaInvalidaError
from banco_agil.utils.validators import validar_valor_monetario

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
    "num_dependentes": "quantos dependentes o cliente tem",
    "tem_dividas": "se o cliente tem dívidas em aberto",
}

# Campos de resposta fechada. A lista mora aqui, ao lado de quem valida, para que a
# pergunta feita ao cliente não possa divergir do que o normalizador aceita.
OPCOES: dict[str, tuple[str, ...]] = {
    "tipo_emprego": ("formal", "autônomo", "desempregado"),
    "tem_dividas": ("sim", "não"),
}

_PONTUACAO_DE_BORDA = ".,;:!?'\"()[]"

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
    if campo not in CAMPOS:
        raise EntradaInvalidaError(f"Campo de entrevista desconhecido: {campo}.")

    if campo in ("renda_mensal", "despesas_mensais"):
        return validar_valor_monetario(valor)

    if campo == "tipo_emprego":
        if isinstance(valor, TipoEmprego):
            return valor
        emprego = _EMPREGOS.get(_normalizar_texto(str(valor)))
        if emprego is None:
            raise EntradaInvalidaError("Vínculo inválido. Use formal, autônomo ou desempregado.")
        return emprego

    if campo == "num_dependentes":
        try:
            numero = int(str(valor).strip())
        except (TypeError, ValueError) as erro:
            raise EntradaInvalidaError("Número de dependentes inválido.") from erro
        if numero < 0:
            raise EntradaInvalidaError("Número de dependentes inválido.")
        return numero

    if isinstance(valor, bool):
        return valor
    texto = _normalizar_texto(str(valor))
    if texto in _AFIRMATIVOS:
        return True
    if texto in _NEGATIVOS:
        return False
    raise EntradaInvalidaError("Não entendi se há dívidas em aberto. Responda sim ou não.")


def registrar_slot(slots: Slots, campo: str, valor: ValorBruto) -> dict[str, ValorSlot]:
    """Devolve uma cópia dos slots com o campo preenchido e normalizado."""
    return {**slots, campo: normalizar_valor(campo, valor)}


def montar_dados(slots: Slots) -> DadosEntrevista:
    """Converte os slots preenchidos no modelo de entrada da fórmula de score.

    Levanta `EntradaInvalidaError` se algum campo ainda estiver faltando.
    """
    faltando = proximo_campo(slots)
    if faltando is not None:
        raise EntradaInvalidaError(f"A entrevista ainda não tem o campo {faltando}.")
    return DadosEntrevista(**{campo: slots[campo] for campo in CAMPOS})


def concluir_entrevista(
    cliente: Cliente,
    slots: Slots,
    repo: ClientesRepository | None = None,
) -> Cliente:
    """Recalcula o score a partir da entrevista, persiste e devolve o cliente atualizado."""
    novo_score = calcular_score(montar_dados(slots))
    return (repo or ClientesRepository()).atualizar_score(cliente.cpf, novo_score)
