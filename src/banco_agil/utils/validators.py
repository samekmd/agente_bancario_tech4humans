"""Validadores puros: CPF, data de nascimento e valores monetários.

Funções sem I/O e sem dependência de framework. O LLM extrai o texto da fala; a decisão
sobre o dado ser válido é sempre destas funções.
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from banco_agil.utils.exceptions import EntradaInvalidaError

_SOMENTE_DIGITOS = re.compile(r"\D")
_FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y")


def normalizar_cpf(valor: str) -> str:
    """Remove qualquer pontuação do CPF, devolvendo apenas os dígitos."""
    return _SOMENTE_DIGITOS.sub("", valor or "")


def _digitos_verificadores(base: str) -> str:
    """Calcula os dois dígitos verificadores a partir dos 9 primeiros dígitos do CPF."""
    digitos = [int(c) for c in base]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(digitos[:tamanho]))
        resto = (soma * 10) % 11
        digitos.append(0 if resto == 10 else resto)
    return "".join(str(d) for d in digitos[9:])


def validar_cpf(valor: str) -> str:
    """Valida um CPF e devolve os 11 dígitos normalizados.

    Levanta `EntradaInvalidaError` se o CPF não tiver 11 dígitos, for uma sequência de
    dígitos repetidos ou falhar na conferência dos dígitos verificadores.
    """
    cpf = normalizar_cpf(valor)
    if len(cpf) != 11:
        raise EntradaInvalidaError("O CPF precisa ter 11 dígitos.")
    if cpf == cpf[0] * 11:
        raise EntradaInvalidaError("CPF inválido.")
    if _digitos_verificadores(cpf[:9]) != cpf[9:]:
        raise EntradaInvalidaError("CPF inválido.")
    return cpf


def validar_data_nascimento(valor: str, hoje: date | None = None) -> date:
    """Converte uma data de nascimento em `date`, aceitando `DD/MM/AAAA` ou ISO.

    Levanta `EntradaInvalidaError` para formato desconhecido ou data no futuro.
    """
    texto = (valor or "").strip()
    for formato in _FORMATOS_DATA:
        try:
            nascimento = datetime.strptime(texto, formato).date()
        except ValueError:
            continue
        if nascimento > (hoje or date.today()):
            raise EntradaInvalidaError("A data de nascimento não pode estar no futuro.")
        return nascimento
    raise EntradaInvalidaError("Data de nascimento inválida. Use o formato DD/MM/AAAA.")


def validar_valor_monetario(valor: str | float | int) -> float:
    """Converte um valor monetário em `float`, aceitando `R$ 10.000,00` ou `10000.50`.

    Levanta `EntradaInvalidaError` para texto não numérico ou valor negativo.
    """
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        numero = float(valor)
    else:
        texto = re.sub(r"[^\d,.\-]", "", str(valor or ""))
        if not texto:
            raise EntradaInvalidaError("Valor inválido.")
        # Em pt-BR a vírgula é o separador decimal e o ponto é o de milhar.
        if "," in texto:
            texto = texto.replace(".", "").replace(",", ".")
        try:
            numero = float(texto)
        except ValueError as erro:
            raise EntradaInvalidaError("Valor inválido.") from erro
    if numero < 0:
        raise EntradaInvalidaError("O valor não pode ser negativo.")
    return numero


def arredondar(valor: float, casas: int = 2) -> float:
    """Arredonda meio-para-cima, como se espera de valor monetário e de score.

    O `round()` embutido usa arredondamento bancário (`round(166.665, 2) == 166.66`),
    que num extrato pareceria erro de cálculo.
    """
    quantum = Decimal(1).scaleb(-casas)
    return float(Decimal(repr(valor)).quantize(quantum, rounding=ROUND_HALF_UP))
