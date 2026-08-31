"""Infraestrutura comum às tools: payload estruturado e atualização de estado.

Nenhuma tool levanta exceção para o grafo. Erro esperado vira `{"ok": False, "erro": ...}`
com uma mensagem que o agente possa verbalizar, e o motivo também vai para `ultimo_erro`
no estado.
"""

import json
from typing import Any

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from banco_agil.observability.tags import marcar_erro
from banco_agil.utils.exceptions import BancoAgilError
from banco_agil.utils.logging import get_logger

ERRO_INESPERADO = "Tive um problema técnico aqui. Pode tentar de novo em instantes?"

logger = get_logger("tools")


def sucesso(**dados: Any) -> dict[str, Any]:  # noqa: ANN401 - payload varia por tool
    """Monta o payload de uma tool bem-sucedida."""
    return {"ok": True, **dados}


def falha(erro: str, **dados: Any) -> dict[str, Any]:  # noqa: ANN401 - payload varia por tool
    """Monta o payload de uma tool que falhou de forma esperada."""
    return {"ok": False, "erro": erro, **dados}


def falha_de(excecao: Exception, tool: str = "?") -> dict[str, Any]:
    """Converte uma exceção em payload de erro, registrando o que aconteceu.

    Exceções de domínio carregam mensagem verbalizável; qualquer outra vira uma mensagem
    genérica, para não vazar detalhe de implementação na conversa. O log é o único lugar
    onde o erro real aparece — sem ele, uma falha inesperada some sem deixar rastro.
    """
    if isinstance(excecao, BancoAgilError):
        logger.warning("[%s] erro de domínio: %s", tool, excecao.mensagem)
        marcar_erro(excecao.mensagem, tool)
        return falha(excecao.mensagem)
    logger.exception("[%s] erro inesperado", tool)
    marcar_erro(f"{type(excecao).__name__}: {excecao}", tool)
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
    logger.debug(
        "payload devolvido ao agente: %s | estado atualizado: %s",
        _serializar(payload),
        sorted(atualizacoes),
    )
    return Command(
        update={
            **atualizacoes,
            "messages": [ToolMessage(content=_serializar(payload), tool_call_id=tool_call_id)],
        }
    )
