"""Testes das arestas condicionais, isoladas do grafo e do LLM."""

from typing import Any

import pytest
from langgraph.graph import END

from banco_agil.domain.enums import Agente
from banco_agil.routing import (
    NO_GUARDA,
    aplicar_guarda,
    destino_permitido,
    rota_apos,
    rota_apos_guarda,
    rota_inicial,
)
from banco_agil.state import estado_inicial

pytestmark = pytest.mark.unit


def estado(**campos: Any) -> dict[str, Any]:
    return {**estado_inicial(), **campos}


AUTENTICADO = {"autenticado": True}


class TestRotaInicial:
    def test_conversa_nova_entra_pela_triagem(self) -> None:
        assert rota_inicial(estado()) == "triagem"

    def test_conversa_encerrada_termina(self) -> None:
        assert rota_inicial(estado(encerrado=True)) == END

    def test_retoma_no_agente_que_estava_atendendo(self) -> None:
        st = estado(**AUTENTICADO, agente_atual=Agente.CAMBIO)

        assert rota_inicial(st) == "cambio"

    def test_sem_autenticacao_nao_retoma_em_outro_agente(self) -> None:
        assert rota_inicial(estado(agente_atual=Agente.CREDITO)) == NO_GUARDA


class TestRotaApos:
    def test_agente_que_nao_transferiu_encerra_o_turno(self) -> None:
        st = estado(**AUTENTICADO, agente_atual=Agente.CREDITO)

        assert rota_apos(Agente.CREDITO)(st) == END

    def test_handoff_segue_para_o_destino(self) -> None:
        st = estado(**AUTENTICADO, agente_atual=Agente.CAMBIO)

        assert rota_apos(Agente.CREDITO)(st) == "cambio"

    def test_encerramento_vence_o_handoff(self) -> None:
        st = estado(**AUTENTICADO, agente_atual=Agente.CAMBIO, encerrado=True)

        assert rota_apos(Agente.TRIAGEM)(st) == END

    def test_destino_recusado_passa_pela_guarda(self) -> None:
        st = estado(agente_atual=Agente.CREDITO)

        assert rota_apos(Agente.TRIAGEM)(st) == NO_GUARDA


class TestGuardaDeAutenticacao:
    @pytest.mark.parametrize("destino", [Agente.CREDITO, Agente.ENTREVISTA_CREDITO, Agente.CAMBIO])
    def test_nenhum_agente_atua_sem_autenticacao(self, destino: Agente) -> None:
        assert destino_permitido(estado(), destino) is Agente.TRIAGEM

    def test_triagem_atua_sem_autenticacao(self) -> None:
        assert destino_permitido(estado(), Agente.TRIAGEM) is Agente.TRIAGEM

    def test_autenticado_passa(self) -> None:
        assert destino_permitido(estado(**AUTENTICADO), Agente.CREDITO) is Agente.CREDITO


class TestTetoDeEntrevistas:
    def test_primeira_entrevista_e_permitida(self) -> None:
        st = estado(**AUTENTICADO, entrevistas_realizadas=0)

        assert destino_permitido(st, Agente.ENTREVISTA_CREDITO) is Agente.ENTREVISTA_CREDITO

    def test_segunda_entrevista_volta_para_credito(self) -> None:
        st = estado(**AUTENTICADO, entrevistas_realizadas=1)

        assert destino_permitido(st, Agente.ENTREVISTA_CREDITO) is Agente.CREDITO

    def test_teto_nao_afeta_os_outros_agentes(self) -> None:
        st = estado(**AUTENTICADO, entrevistas_realizadas=1)

        assert destino_permitido(st, Agente.CAMBIO) is Agente.CAMBIO


class TestNoDeGuarda:
    def test_corrige_o_agente_atual_no_estado(self) -> None:
        st = estado(agente_atual=Agente.CREDITO)

        assert aplicar_guarda(st) == {"agente_atual": Agente.TRIAGEM}

    def test_depois_da_guarda_o_destino_ja_e_valido(self) -> None:
        st = estado(agente_atual=Agente.CREDITO)
        corrigido = {**st, **aplicar_guarda(st)}

        assert rota_apos_guarda(corrigido) == "triagem"
        # Sem novo desvio: o destino corrigido passa nas guardas.
        assert rota_inicial(corrigido) == "triagem"

    def test_guarda_nao_reencaminha_indefinidamente(self) -> None:
        """Um segundo passo pela guarda significaria laço até o recursion_limit."""
        st = estado(**AUTENTICADO, entrevistas_realizadas=1, agente_atual=Agente.ENTREVISTA_CREDITO)
        corrigido = {**st, **aplicar_guarda(st)}

        assert corrigido["agente_atual"] is Agente.CREDITO
        assert rota_apos(Agente.CREDITO)(corrigido) == END
