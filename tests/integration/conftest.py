"""Fixtures do grafo: bases em `tmp_path` e um LLM roteirizado, sem rede.

Os fakes do `langchain-core` não servem aqui: `FakeListChatModel` e
`FakeMessagesListChatModel` levantam `NotImplementedError` em `bind_tools`, e sem binding
não há tool call para testar roteamento.
"""

import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage

from banco_agil.config import get_settings

FIXTURES = Path(__file__).parent.parent / "fixtures"


class LLMRoteirizado(FakeMessagesListChatModel):
    """Devolve uma sequência fixa de mensagens, aceitando o binding de ferramentas."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "LLMRoteirizado":
        return self


def fala(texto: str) -> AIMessage:
    """Resposta do agente ao cliente, sem tool call."""
    return AIMessage(content=texto)


def chama(nome: str, args: dict[str, Any] | None = None, id_: str = "call") -> AIMessage:
    """Resposta do agente que aciona uma ferramenta."""
    return AIMessage(content="", tool_calls=[{"name": nome, "args": args or {}, "id": id_}])


def roteiro(*mensagens: BaseMessage) -> LLMRoteirizado:
    """Monta o LLM falso a partir das respostas esperadas, em ordem."""
    return LLMRoteirizado(responses=list(mensagens))


@pytest.fixture(autouse=True)
def bases_isoladas(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Aponta as bases para uma cópia descartável e nunca para `data/`."""
    destino = tmp_path / "data"
    destino.mkdir()
    shutil.copy(FIXTURES / "clientes.csv", destino / "clientes.csv")
    shutil.copy(FIXTURES / "score_limite.csv", destino / "score_limite.csv")

    monkeypatch.setenv("DATA_DIR", str(destino))
    monkeypatch.setenv("GROQ_API_KEY", "chave-de-teste")
    # A suíte roda offline: sem isso o app tentaria alcançar o servidor do MLflow.
    monkeypatch.setenv("MLFLOW_HABILITADO", "false")
    get_settings.cache_clear()
    yield destino
    get_settings.cache_clear()
