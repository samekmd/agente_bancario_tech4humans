"""Fórmula de score de crédito. Única fonte de verdade do cálculo.

Função pura: sem I/O, sem LangChain, sem LLM. O agente coleta os cinco campos da
entrevista; quem transforma isso em número é este módulo.
"""

from banco_agil.domain.enums import TipoEmprego
from banco_agil.domain.models import DadosEntrevista
from banco_agil.utils.validators import arredondar

SCORE_MINIMO = 0
SCORE_MAXIMO = 1000

FATOR_RENDA = 30

PESO_EMPREGO: dict[TipoEmprego, int] = {
    TipoEmprego.FORMAL: 300,
    TipoEmprego.AUTONOMO: 200,
    TipoEmprego.DESEMPREGADO: 0,
}

PESO_DEPENDENTES: dict[int, int] = {0: 100, 1: 80, 2: 60}
PESO_DEPENDENTES_TRES_OU_MAIS = 30

PESO_COM_DIVIDAS = -100
PESO_SEM_DIVIDAS = 100


def peso_dependentes(num_dependentes: int) -> int:
    """Peso do número de dependentes: 0 → 100, 1 → 80, 2 → 60, 3 ou mais → 30."""
    return PESO_DEPENDENTES.get(num_dependentes, PESO_DEPENDENTES_TRES_OU_MAIS)


def peso_dividas(tem_dividas: bool) -> int:
    """Peso das dívidas em aberto: sim → -100, não → 100."""
    return PESO_COM_DIVIDAS if tem_dividas else PESO_SEM_DIVIDAS


def calcular_score(dados: DadosEntrevista) -> int:
    """Calcula o score de crédito a partir dos dados da entrevista.

    `score = (renda / (despesas + 1)) * 30 + peso_emprego + peso_dependentes + peso_dividas`,
    arredondado para inteiro e truncado ao intervalo 0–1000.
    """
    bruto = (
        (dados.renda_mensal / (dados.despesas_mensais + 1)) * FATOR_RENDA
        + PESO_EMPREGO[dados.tipo_emprego]
        + peso_dependentes(dados.num_dependentes)
        + peso_dividas(dados.tem_dividas)
    )
    return max(SCORE_MINIMO, min(SCORE_MAXIMO, int(arredondar(bruto, casas=0))))
