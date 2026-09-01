"""Testes da política de modelos por agente.

Offline: o `ChatGroq` é instanciado e inspecionado, nunca chamado.
"""

import pytest

from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.llm import PERFIL_POR_AGENTE, PerfilLLM, llm_para

pytestmark = pytest.mark.unit

# O `langchain-groq` troca temperatura zero exata por um epsilon; é zero na prática.
QUASE_ZERO = 1e-6


@pytest.fixture(autouse=True)
def chave_de_teste(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestPerfilPorAgente:
    def test_entrevista_usa_o_perfil_de_extracao(self) -> None:
        """É o agente que transforma fala do cliente em dado gravado na base."""
        assert PERFIL_POR_AGENTE[Agente.ENTREVISTA_CREDITO] is PerfilLLM.EXTRACAO

    def test_credito_conversa_mas_com_o_modelo_robusto(self) -> None:
        """Decide pedido de crédito: erra caro, mas precisa conversar bem."""
        assert PERFIL_POR_AGENTE[Agente.CREDITO] is PerfilLLM.DIALOGO_ROBUSTO

    @pytest.mark.parametrize("agente", [Agente.TRIAGEM, Agente.CAMBIO])
    def test_agentes_de_leitura_usam_o_modelo_barato(self, agente: Agente) -> None:
        assert PERFIL_POR_AGENTE[agente] is PerfilLLM.DIALOGO

    def test_todo_agente_tem_perfil(self) -> None:
        """Anti-drift: um agente novo sem perfil cairia em modelo errado silenciosamente."""
        assert set(PERFIL_POR_AGENTE) == set(Agente)


class TestLlmPara:
    def test_entrevista_recebe_o_modelo_robusto_a_temperatura_zero(self) -> None:
        settings = get_settings()

        modelo = llm_para(Agente.ENTREVISTA_CREDITO)

        assert modelo.model_name == settings.modelo_robusto
        assert modelo.temperature < QUASE_ZERO

    def test_credito_recebe_o_modelo_robusto_com_temperatura_de_dialogo(self) -> None:
        """Os dois eixos são independentes: robusto não implica temperatura zero."""
        settings = get_settings()

        modelo = llm_para(Agente.CREDITO)

        assert modelo.model_name == settings.modelo_robusto
        assert modelo.temperature == settings.temperatura_dialogo

    @pytest.mark.parametrize("agente", [Agente.TRIAGEM, Agente.CAMBIO])
    def test_agentes_de_leitura_recebem_o_modelo_barato(self, agente: Agente) -> None:
        settings = get_settings()

        modelo = llm_para(agente)

        assert modelo.model_name == settings.modelo_barato
        assert modelo.temperature == settings.temperatura_dialogo

    def test_credito_e_entrevista_compartilham_modelo_mas_nao_temperatura(self) -> None:
        entrevista = llm_para(Agente.ENTREVISTA_CREDITO)
        credito = llm_para(Agente.CREDITO)

        assert entrevista.model_name == credito.model_name
        assert entrevista.temperature != credito.temperature

    def test_triagem_e_credito_nao_compartilham_modelo(self) -> None:
        assert llm_para(Agente.TRIAGEM).model_name != llm_para(Agente.CREDITO).model_name

    @pytest.mark.parametrize("agente", list(Agente))
    def test_todo_perfil_esconde_raciocinio_e_limita_a_geracao(self, agente: Agente) -> None:
        """A combinação que parou o vazamento de raciocínio vale para qualquer perfil."""
        modelo = llm_para(agente)

        assert modelo.reasoning_format == "hidden"
        assert modelo.max_tokens == get_settings().max_tokens_resposta
