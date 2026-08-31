"""Validadores puros: CPF, data de nascimento e valores monetários.

Funções sem I/O e sem dependência de framework. O LLM extrai o texto da fala; a decisão
sobre o dado ser válido é sempre destas funções.
"""

import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from banco_agil.utils.exceptions import EntradaInvalidaError

_SOMENTE_DIGITOS = re.compile(r"\D")
_FORMATOS_DATA = ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y")

# Decoração de moeda que pode acompanhar o número sem torná-lo ambíguo. Lista fechada:
# qualquer outra palavra faz o valor ser recusado, e não silenciosamente descartada.
_DECORACAO_MOEDA = re.compile(
    r"r\$|rs(?![a-z])|\$|brl|usd|eur|gbp|reais|real|dolares|dolar|euros|euro|libras|libra",
)

# Formas aceitas, mutuamente exclusivas. O que separa milhar de centavo é a quantidade de
# dígitos depois do ponto: três é grupo de milhar, um ou dois é centavo.
_INTEIRO = re.compile(r"^\d+$")
_MILHAR_PT = re.compile(r"^\d{1,3}(\.\d{3})+$")
_DECIMAL_VIRGULA = re.compile(r"^\d{1,3}(\.\d{3})*,\d{1,2}$|^\d+,\d{1,2}$")
_DECIMAL_PONTO = re.compile(r"^\d+\.\d{1,2}$")

VALOR_ILEGIVEL = "Não entendi o valor. Pode me dizer em números? Por exemplo: 8000 ou R$ 8.000,00."


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


def _limpar_moeda(texto: str) -> str:
    """Remove símbolo e nome de moeda, acento e espaço, preservando o resto intacto.

    O que sobrar precisa ser um número válido por si só — palavra desconhecida sobrevive
    à limpeza justamente para o valor ser recusado depois.
    """
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    sem_moeda = _DECORACAO_MOEDA.sub("", sem_acento.lower())
    return "".join(sem_moeda.split())


def validar_valor_monetario(valor: str | float | int) -> float:
    """Converte um valor monetário em `float`, aceitando as formas usuais em pt-BR.

    Aceita `8000`, `8.000`, `R$ 8.000,00`, `8000.50`, `12,5` e `100 dólares`. Recusa
    qualquer coisa cuja leitura seja ambígua — `8 mil`, `8k`, `2,5 mil`, `8,000.50` —
    porque devolver um número errado em silêncio é pior que pedir o valor de novo.

    `1.234` é lido como 1234: em real, ponto sem centavos é separador de milhar, e três
    casas decimais não existem.

    Levanta `EntradaInvalidaError` para valor ilegível ou negativo.
    """
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        numero = float(valor)
    else:
        texto = _limpar_moeda(str(valor or ""))
        if not texto:
            raise EntradaInvalidaError(VALOR_ILEGIVEL)

        if _INTEIRO.match(texto) or _DECIMAL_PONTO.match(texto):
            numero = float(texto)
        elif _MILHAR_PT.match(texto):
            numero = float(texto.replace(".", ""))
        elif _DECIMAL_VIRGULA.match(texto):
            numero = float(texto.replace(".", "").replace(",", "."))
        else:
            raise EntradaInvalidaError(VALOR_ILEGIVEL)

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
