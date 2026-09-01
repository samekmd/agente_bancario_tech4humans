"""Infraestrutura comum aos agentes: montagem de prompt e binding de tools.

Todo agente é montado por aqui. O binding vem de `tools_de()`, que é o que garante a
regra 4: o escopo do agente é o conjunto de ferramentas que ele recebe, não uma instrução
de prompt.
"""

from collections.abc import Callable, Sequence
from functools import cache

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelRetryMiddleware, dynamic_prompt
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.state import AtendimentoState
from banco_agil.tools import tools_de
from banco_agil.tools.base import ERRO_INESPERADO
from banco_agil.utils.logging import get_logger

logger = get_logger("agents.base")

Contexto = Callable[[AtendimentoState], str]

PROMPT_BASE = "persona_base"

# Nome do arquivo de prompt de cada agente, quando difere do valor do enum.
ARQUIVO_PROMPT: dict[Agente, str] = {Agente.ENTREVISTA_CREDITO: "entrevista"}

# Assinaturas do defeito de formato do gpt-oss. `<|channel|>` é token de controle do
# formato harmony, e `tool_use_failed` é o código que o Groq devolve quando o nome da
# ferramenta extraído do cabeçalho não bate com nenhuma das enviadas.
_ASSINATURAS_FALHA_DE_FORMATO = ("tool_use_failed", "<|channel|>")


def e_falha_de_formato_de_tool_call(erro: BaseException) -> bool:
    """Diz se o erro é o defeito de geração do gpt-oss, e só ele.

    O predicado precisa ser estreito: retentar 400 indiscriminadamente faria uma
    requisição de fato malformada repetir até esgotar as tentativas, gastando tokens e
    triplicando a espera do cliente por um erro que nunca vai passar.
    """
    texto = str(erro)
    return any(assinatura in texto for assinatura in _ASSINATURAS_FALHA_DE_FORMATO)


@cache
def carregar_prompt(nome: str) -> str:
    """Lê um prompt versionado de `prompts/<nome>.md`."""
    return (get_settings().prompts_dir / f"{nome}.md").read_text(encoding="utf-8").strip()


def montar_prompt(agente: Agente, contexto: str = "") -> str:
    """Compõe persona base, prompt do agente e o contexto determinístico do turno."""
    partes = [
        carregar_prompt(PROMPT_BASE),
        carregar_prompt(ARQUIVO_PROMPT.get(agente, agente.value)),
    ]
    if contexto:
        partes.append(f"# Contexto deste atendimento\n\n{contexto}")
    return "\n\n---\n\n".join(partes)


def construir_agente(
    agente: Agente,
    contexto: Contexto | None = None,
    llm: BaseChatModel | None = None,
    middlewares: Sequence[AgentMiddleware] = (),
) -> CompiledStateGraph:
    """Monta o subgrafo de um agente com suas tools e o prompt do seu domínio.

    `contexto` recebe o estado e devolve os fatos que o LLM não deve inferir — o campo que
    falta na entrevista, o limite do cliente, quantas tentativas de autenticação restam.

    `middlewares` são os hooks específicos do agente, somados ao prompt dinâmico. Hoje só
    a entrevista usa, para marcar no estado qual campo foi de fato perguntado.
    """
    if llm is None:
        # Sem modelo injetado, vale o perfil do agente — nunca um default de diálogo
        # silencioso, que faria a entrevista cair no modelo errado sem ninguém notar.
        from banco_agil.llm import llm_para

        llm = llm_para(agente)

    @dynamic_prompt
    def prompt_do_turno(request) -> str:  # noqa: ANN001 - ModelRequest do middleware
        return montar_prompt(agente, contexto(request.state) if contexto else "")

    return create_agent(
        model=llm,
        tools=list(tools_de(agente)),
        state_schema=AtendimentoState,
        middleware=[prompt_do_turno, _retry_de_formato(agente), *middlewares],
        name=agente.value,
    )


def _retry_de_formato(agente: Agente) -> AgentMiddleware:
    """Repete a chamada quando o modelo erra o formato da tool call.

    Vale para todos os agentes: o defeito já apareceu em dois deles, e qualquer agente que
    chame ferramenta está exposto. Backoff curto de propósito — o cliente está esperando a
    resposta, e a falha é estocástica, não de sobrecarga.
    """

    def retentar(erro: BaseException) -> bool:
        if not e_falha_de_formato_de_tool_call(erro):
            return False
        logger.warning(
            "[%s] o modelo devolveu tool call com formato inválido; repetindo a chamada",
            agente.value,
        )
        return True

    def desistir(erro: BaseException) -> str:
        """Texto que o cliente vê quando as tentativas acabam."""
        logger.error("[%s] falha de formato persistiu após as tentativas: %s", agente.value, erro)
        return ERRO_INESPERADO

    return ModelRetryMiddleware(
        max_retries=get_settings().llm_max_tentativas_formato,
        retry_on=retentar,
        initial_delay=0.5,
        backoff_factor=2.0,
        # Uma função, e não a string "error": o middleware compara `on_failure` com valores
        # conhecidos e, no que não reconhece, injeta o erro cru como fala do assistente.
        # Foi assim que um `on_failure="raise"` mandou um 400 do Groq para a tela do
        # cliente sem levantar exceção nenhuma. Função errada quebra no import; string
        # errada vira comportamento silencioso.
        on_failure=desistir,
    )
