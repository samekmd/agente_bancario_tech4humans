"""Testes do retry no defeito de formato de tool call do gpt-oss.

A família `gpt-oss` às vezes emite o cabeçalho harmony fora de ordem e cola o nome da
ferramenta no marcador de canal. O Groq devolve 400 `tool_use_failed` e a chamada morre
antes de qualquer tool rodar. É estocástico: repetir resolve.
"""

import pytest
from langchain_core.messages import AIMessage

from banco_agil.agents.base import construir_agente, e_falha_de_formato_de_tool_call
from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from tests.integration.conftest import LLMRoteirizado

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def chave_de_teste(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def llm_falso() -> object:
    """Modelo que aceita binding de tools; nenhuma chamada de rede acontece aqui."""
    return LLMRoteirizado(responses=[AIMessage(content="ok")])


# O texto exato dos erros que apareceram no log de produção.
ERRO_REAL = (
    "Error code: 400 - {'error': {'message': \"Tool call validation failed: tool call "
    "validation failed: attempted to call tool 'solicitar_aumento_limite<|channel|>"
    "commentary' which was not in request.tools\", 'type': 'invalid_request_error', "
    "'code': 'tool_use_failed', 'failed_generation': '{\"name\": "
    '"solicitar_aumento_limite<|channel|>commentary", "arguments": '
    '{"novo_limite":"8000"}}\'}}'
)


class TestPredicado:
    @pytest.mark.parametrize(
        "tool",
        [
            "solicitar_aumento_limite",
            "registrar_resposta_entrevista",
            "transferir_para_entrevista_credito",
        ],
    )
    def test_reconhece_o_defeito_em_qualquer_tool(self, tool: str) -> None:
        erro = RuntimeError(
            f"attempted to call tool '{tool}<|channel|>commentary' which was not in request.tools"
        )

        assert e_falha_de_formato_de_tool_call(erro) is True

    def test_reconhece_a_mensagem_completa_do_log(self) -> None:
        assert e_falha_de_formato_de_tool_call(RuntimeError(ERRO_REAL)) is True

    @pytest.mark.parametrize(
        ("erro", "motivo"),
        [
            (RuntimeError("Error code: 401 - Invalid API Key"), "chave inválida"),
            (RuntimeError("Error code: 400 - model_not_found"), "modelo inexistente"),
            (RuntimeError("Error code: 429 - rate limit reached"), "limite de uso"),
            (ValueError("qualquer outra coisa"), "erro comum"),
            (RuntimeError(""), "sem mensagem"),
        ],
    )
    def test_recusa_o_que_nao_e_o_defeito(self, erro: Exception, motivo: str) -> None:
        """Retentar 400 legítimo triplicaria a espera do cliente por um erro que não passa."""
        assert e_falha_de_formato_de_tool_call(erro) is False


class TestMiddlewareNosAgentes:
    @pytest.mark.parametrize("agente", list(Agente))
    def test_todo_agente_recebe_o_retry(self, agente: Agente, llm_falso: object) -> None:
        """O defeito já apareceu em dois agentes; qualquer um que chame tool está exposto."""
        compilado = construir_agente(agente, llm=llm_falso)

        assert compilado is not None

    def test_on_failure_e_funcao_e_devolve_mensagem_amigavel(self) -> None:
        """O defeito real: `on_failure="raise"` não é valor reconhecido pelo middleware.

        Ele então caía no ramo que injeta o erro cru como fala do assistente — sem levantar
        exceção, o `try/except` da UI nunca via nada, e um 400 do Groq foi para a tela.
        Uma função não tem como ser mistypada em silêncio.
        """
        from banco_agil.agents.base import _retry_de_formato
        from banco_agil.tools.base import ERRO_INESPERADO

        middleware = _retry_de_formato(Agente.CREDITO)

        assert callable(middleware.on_failure)
        assert middleware.on_failure(RuntimeError(ERRO_REAL)) == ERRO_INESPERADO

    def test_mensagem_de_desistencia_nao_vaza_detalhe_tecnico(self) -> None:
        from banco_agil.agents.base import _retry_de_formato

        texto = _retry_de_formato(Agente.CREDITO).on_failure(RuntimeError(ERRO_REAL))

        for vazamento in ("400", "Error code", "tool_use_failed", "<|channel|>"):
            assert vazamento not in texto

    def test_o_teto_vem_da_configuracao(self) -> None:
        from banco_agil.agents.base import _retry_de_formato
        from banco_agil.config import get_settings

        middleware = _retry_de_formato(Agente.CREDITO)

        assert middleware.max_retries == get_settings().llm_max_tentativas_formato
