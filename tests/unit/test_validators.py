"""Testes dos validadores puros."""

from datetime import date

import pytest

from banco_agil.utils.exceptions import EntradaInvalidaError
from banco_agil.utils.validators import (
    arredondar,
    normalizar_cpf,
    validar_cpf,
    validar_data_nascimento,
    validar_valor_monetario,
)

pytestmark = pytest.mark.unit


class TestValidarCpf:
    @pytest.mark.parametrize(
        "entrada",
        ["52998224725", "529.982.247-25", " 529 982 247 25 "],
    )
    def test_aceita_cpf_valido_com_e_sem_pontuacao(self, entrada: str) -> None:
        assert validar_cpf(entrada) == "52998224725"

    @pytest.mark.parametrize(
        ("entrada", "motivo"),
        [
            ("529982247", "menos de 11 dígitos"),
            ("529982247250", "mais de 11 dígitos"),
            ("11111111111", "dígitos repetidos"),
            ("52998224724", "dígito verificador errado"),
            ("", "vazio"),
        ],
    )
    def test_rejeita_cpf_invalido(self, entrada: str, motivo: str) -> None:
        with pytest.raises(EntradaInvalidaError):
            validar_cpf(entrada)

    def test_normalizar_nao_valida(self) -> None:
        assert normalizar_cpf("111.222.333-44") == "11122233344"


class TestValidarDataNascimento:
    @pytest.mark.parametrize("entrada", ["12/03/1985", "1985-03-12", "12-03-1985"])
    def test_aceita_formatos_suportados(self, entrada: str) -> None:
        assert validar_data_nascimento(entrada) == date(1985, 3, 12)

    def test_rejeita_data_futura(self) -> None:
        with pytest.raises(EntradaInvalidaError):
            validar_data_nascimento("01/01/2100", hoje=date(2026, 8, 28))

    @pytest.mark.parametrize("entrada", ["ontem", "31/02/1985", ""])
    def test_rejeita_entrada_invalida(self, entrada: str) -> None:
        with pytest.raises(EntradaInvalidaError):
            validar_data_nascimento(entrada)


class TestValidarValorMonetario:
    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("R$ 10.000,00", 10000.0),
            ("10000.50", 10000.5),
            ("1.234,56", 1234.56),
            ("8000", 8000.0),
            (7500.25, 7500.25),
            (3000, 3000.0),
        ],
    )
    def test_converte_formatos_aceitos(self, entrada: str | float, esperado: float) -> None:
        assert validar_valor_monetario(entrada) == esperado

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("8.000", 8000.0),
            ("R$ 3.000", 3000.0),
            ("1.234", 1234.0),
            ("1.234.567", 1234567.0),
            ("R$8000", 8000.0),
            ("12,5", 12.5),
            ("  8000  ", 8000.0),
        ],
    )
    def test_ponto_sem_centavos_e_separador_de_milhar(self, entrada: str, esperado: float) -> None:
        """Em real, `8.000` é oito mil — não oito. Três dígitos após o ponto é milhar."""
        assert validar_valor_monetario(entrada) == esperado

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [("3000 reais", 3000.0), ("100 dólares", 100.0), ("50 EUR", 50.0), ("R$ 2.500", 2500.0)],
    )
    def test_nome_de_moeda_acompanha_o_valor(self, entrada: str, esperado: float) -> None:
        assert validar_valor_monetario(entrada) == esperado

    @pytest.mark.parametrize(
        "entrada",
        [
            "8 mil",
            "8k",
            "2,5 mil",
            "uns 3 mil",
            "mil reais",
            "uns oito mil",
            "8,000.50",
            "1.2345",
            "1.2.3",
            "muito dinheiro",
            "",
            "-500",
        ],
    )
    def test_rejeita_entrada_invalida(self, entrada: str) -> None:
        with pytest.raises(EntradaInvalidaError):
            validar_valor_monetario(entrada)

    @pytest.mark.parametrize(
        ("entrada", "valor_corrompido"),
        [("8 mil", 8.0), ("R$ 3.000", 3.0), ("2,5 mil", 2.5), ("8k", 8.0)],
    )
    def test_regressao_nao_devolve_numero_errado_em_silencio(
        self, entrada: str, valor_corrompido: float
    ) -> None:
        """A versão antiga descartava letras e lia `8.000` como decimal.

        `8 mil` virava R$ 8,00 e `R$ 3.000` virava R$ 3,00, sem erro nenhum — o score da
        entrevista saía calculado em cima disso. Recusar é obrigatório; devolver o número
        errado, nunca.
        """
        try:
            resultado = validar_valor_monetario(entrada)
        except EntradaInvalidaError:
            return
        assert resultado != valor_corrompido


class TestArredondar:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (166.665, 166.67),
            (166.664, 166.66),
            (0.005, 0.01),
            (10.0, 10.0),
            (5000.0, 5000.0),
        ],
    )
    def test_arredonda_meio_para_cima_em_duas_casas(self, valor: float, esperado: float) -> None:
        assert arredondar(valor) == esperado

    @pytest.mark.parametrize(("valor", "esperado"), [(500.5, 501.0), (500.4, 500.0), (0.5, 1.0)])
    def test_arredonda_para_inteiro(self, valor: float, esperado: float) -> None:
        assert arredondar(valor, casas=0) == esperado

    def test_difere_do_round_embutido_no_caso_de_meio(self) -> None:
        assert round(166.665, 2) == 166.66
        assert arredondar(166.665) == 166.67
