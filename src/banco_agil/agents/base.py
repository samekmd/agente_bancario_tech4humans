"""Infraestrutura comum aos agentes: montagem de prompt e binding de tools.

Todo agente é montado por aqui. O binding vem de `tools_de()`, que é o que garante a
regra 4: o escopo do agente é o conjunto de ferramentas que ele recebe, não uma instrução
de prompt.
"""

from collections.abc import Callable
from functools import cache

from langchain.agents import create_agent
from langchain.agents.middleware import dynamic_prompt
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from banco_agil.config import get_settings
from banco_agil.domain.enums import Agente
from banco_agil.state import AtendimentoState
from banco_agil.tools import tools_de

Contexto = Callable[[AtendimentoState], str]

PROMPT_BASE = "persona_base"

# Nome do arquivo de prompt de cada agente, quando difere do valor do enum.
ARQUIVO_PROMPT: dict[Agente, str] = {Agente.ENTREVISTA_CREDITO: "entrevista"}


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
) -> CompiledStateGraph:
    """Monta o subgrafo de um agente com suas tools e o prompt do seu domínio.

    `contexto` recebe o estado e devolve os fatos que o LLM não deve inferir — o campo que
    falta na entrevista, o limite do cliente, quantas tentativas de autenticação restam.
    """
    if llm is None:
        from banco_agil.llm import llm_dialogo

        llm = llm_dialogo()

    @dynamic_prompt
    def prompt_do_turno(request) -> str:  # noqa: ANN001 - ModelRequest do middleware
        return montar_prompt(agente, contexto(request.state) if contexto else "")

    return create_agent(
        model=llm,
        tools=list(tools_de(agente)),
        state_schema=AtendimentoState,
        middleware=[prompt_do_turno],
        name=agente.value,
    )
