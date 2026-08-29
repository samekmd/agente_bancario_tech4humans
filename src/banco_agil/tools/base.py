"""Infraestrutura comum às tools: payload estruturado e atualização de estado.

Nenhuma tool levanta exceção para o grafo. Erro esperado vira `{"ok": False, "erro": ...}`
com uma mensagem que o agente possa verbalizar, e o motivo também vai para `ultimo_erro`
no estado.
"""

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from banco_agil.utils.exceptions import BancoAgilError

ERRO_INESPERADO = "Tive um problema técnico aqui. Pode tentar de novo em instantes?"


def sucesso(**dados: Any) -> dict[str, Any]:  # noqa: ANN401 - payload varia por tool
    """Monta o payload de uma tool bem-sucedida."""
    return {"ok": True, **dados}


def falha(erro: str, **dados: Any) -> dict[str, Any]:  # noqa: ANN401 - payload varia por tool
    """Monta o payload de uma tool que falhou de forma esperada."""
    return {"ok": False, "erro": erro, **dados}


def falha_de(excecao: Exception) -> dict[str, Any]:
    """Converte uma exceção em payload de erro.

    Exceções de domínio carregam mensagem verbalizável; qualquer outra vira uma mensagem
    genérica, para não vazar detalhe de implementação na conversa.
    """
    if isinstance(excecao, BancoAgilError):
        return falha(excecao.mensagem)
    return falha(ERRO_INESPERADO)


def _serializar(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def responder(
    payload: dict[str, Any],
    tool_call_id: str,
    **atualizacoes: Any,  # noqa: ANN401 - campos do AtendimentoState
) -> Command:
    """Devolve o payload ao agente e aplica as atualizações de estado no mesmo passo.

    `ultimo_erro` é preenchido automaticamente a partir do payload, para o grafo poder
    rotear em cima de falha sem reler a conversa.
    """
    atualizacoes.setdefault("ultimo_erro", None if payload.get("ok") else payload.get("erro"))
    return Command(
        update={
            **atualizacoes,
            "messages": [ToolMessage(content=_serializar(payload), tool_call_id=tool_call_id)],
        }
    )
