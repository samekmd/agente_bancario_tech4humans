"""Testes do contexto determinístico que cada agente injeta no prompt do turno."""

from typing import Any

import pytest

from banco_agil.agents import entrevista
from banco_agil.domain.enums import TipoEmprego
from banco_agil.state import estado_inicial

pytestmark = pytest.mark.unit


def estado(**campos: Any) -> dict[str, Any]:
    return {**estado_inicial(), **campos}


class TestContextoDaEntrevista:
    def test_oferece_as_tres_opcoes_de_vinculo_na_pergunta(self) -> None:
        slots = {"renda_mensal": 8000.0, "despesas_mensais": 3000.0}

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS: formal, autônomo ou desempregado." in texto
        assert "escolher uma delas" in texto
        assert "`tipo_emprego`" in texto

    def test_oferece_as_opcoes_de_dividas(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
        }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS: sim ou não." in texto

    @pytest.mark.parametrize("campo", ["renda_mensal", "num_dependentes"])
    def test_campo_aberto_nao_lista_opcoes(self, campo: str) -> None:
        slots: dict[str, Any] = {}
        if campo == "num_dependentes":
            slots = {
                "renda_mensal": 8000.0,
                "despesas_mensais": 3000.0,
                "tipo_emprego": TipoEmprego.FORMAL,
            }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "RESPOSTAS ACEITAS" not in texto

    def test_indica_a_posicao_da_pergunta(self) -> None:
        slots = {"renda_mensal": 8000.0, "despesas_mensais": 3000.0}

        assert "(3 de 5)" in entrevista.contexto(estado(entrevista_slots=slots))

    def test_entrevista_completa_manda_finalizar(self) -> None:
        slots = {
            "renda_mensal": 8000.0,
            "despesas_mensais": 3000.0,
            "tipo_emprego": TipoEmprego.FORMAL,
            "num_dependentes": 0,
            "tem_dividas": False,
        }

        texto = entrevista.contexto(estado(entrevista_slots=slots))

        assert "finalizar_entrevista" in texto
        assert "RESPOSTAS ACEITAS" not in texto
