"""Testes da fórmula de score, incluindo as fronteiras 0 e 1000."""

import pytest

from banco_agil.domain.enums import TipoEmprego
from banco_agil.domain.models import DadosEntrevista
from banco_agil.services.score import calcular_score, peso_dependentes, peso_dividas

pytestmark = pytest.mark.unit


def _dados(
    renda: float = 5000.0,
    despesas: float = 2000.0,
    emprego: TipoEmprego = TipoEmprego.FORMAL,
    dependentes: int = 0,
    dividas: bool = False,
) -> DadosEntrevista:
    return DadosEntrevista(
        renda_mensal=renda,
        despesas_mensais=despesas,
        tipo_emprego=emprego,
        num_dependentes=dependentes,
        tem_dividas=dividas,
    )


class TestPesos:
    @pytest.mark.parametrize(
        ("dependentes", "esperado"),
        [(0, 100), (1, 80), (2, 60), (3, 30), (7, 30)],
    )
    def test_peso_dependentes(self, dependentes: int, esperado: int) -> None:
        assert peso_dependentes(dependentes) == esperado

    @pytest.mark.parametrize(("dividas", "esperado"), [(True, -100), (False, 100)])
    def test_peso_dividas(self, dividas: bool, esperado: int) -> None:
        assert peso_dividas(dividas) == esperado


class TestCalcularScore:
    def test_aplica_a_formula_do_contrato(self) -> None:
        # (5000 / 2001) * 30 = 74.96 + 300 (formal) + 100 (0 dep) + 100 (sem dívidas)
        assert calcular_score(_dados()) == 575

    @pytest.mark.parametrize(
        ("emprego", "esperado"),
        [(TipoEmprego.FORMAL, 575), (TipoEmprego.AUTONOMO, 475), (TipoEmprego.DESEMPREGADO, 275)],
    )
    def test_peso_do_emprego_entra_no_total(self, emprego: TipoEmprego, esperado: int) -> None:
        assert calcular_score(_dados(emprego=emprego)) == esperado

    def test_despesas_zero_nao_divide_por_zero(self) -> None:
        # O `+ 1` do denominador aparece no resultado: (10 / 1) * 30 = 300, + 500 de pesos.
        assert calcular_score(_dados(renda=10.0, despesas=0.0)) == 800

    def test_piso_e_zero(self) -> None:
        dados = _dados(
            renda=0.0,
            despesas=5000.0,
            emprego=TipoEmprego.DESEMPREGADO,
            dependentes=4,
            dividas=True,
        )
        # 0 + 0 + 30 - 100 = -70, truncado para 0
        assert calcular_score(dados) == 0

    def test_teto_e_mil(self) -> None:
        dados = _dados(renda=1_000_000.0, despesas=100.0)
        assert calcular_score(dados) == 1000

    def test_resultado_e_sempre_inteiro_no_intervalo(self) -> None:
        for renda in (0.0, 1.0, 1234.56, 50_000.0, 10_000_000.0):
            score = calcular_score(_dados(renda=renda, despesas=1500.0))
            assert isinstance(score, int)
            assert 0 <= score <= 1000

    def test_cenario_de_entrevista_do_seed(self) -> None:
        """Perfil que reprova com score 470 e passa a aprovar depois da entrevista."""
        dados = _dados(renda=8000.0, despesas=3000.0, emprego=TipoEmprego.FORMAL)
        assert calcular_score(dados) == 580
