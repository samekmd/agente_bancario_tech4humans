"""Configuração de logging estruturado da aplicação.

Único ponto que configura handlers. Nenhum `print` no projeto.
"""

import logging
import sys
from logging import Logger

_FORMATO = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_RAIZ = "banco_agil"
_configurado = False


def configurar_logging(nivel: str | None = None) -> None:
    """Configura o logger raiz da aplicação (stderr + `logs/banco_agil.log`).

    Idempotente: chamadas repetidas não duplicam handlers.
    """
    global _configurado
    if _configurado:
        return

    from banco_agil.config import get_settings

    settings = get_settings()
    logger = logging.getLogger(_RAIZ)
    logger.setLevel(nivel or settings.log_level)
    logger.propagate = False

    formatador = logging.Formatter(_FORMATO)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatador)
    logger.addHandler(console)

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    arquivo = logging.FileHandler(settings.logs_dir / "banco_agil.log", encoding="utf-8")
    arquivo.setFormatter(formatador)
    logger.addHandler(arquivo)

    _configurado = True


def get_logger(nome: str) -> Logger:
    """Retorna um logger filho do logger raiz da aplicação."""
    return logging.getLogger(f"{_RAIZ}.{nome}")


def dump_seguro(modelo: object) -> dict[str, object]:
    """Serializa um modelo Pydantic para log, mascarando qualquer campo de CPF.

    Existe para que `model_dump()` num log não acabe registrando o documento do cliente.
    """
    dados = modelo.model_dump(mode="json")  # type: ignore[attr-defined]
    return {
        chave: mascarar_cpf(valor) if "cpf" in chave and isinstance(valor, str) else valor
        for chave, valor in dados.items()
    }


def mascarar_cpf(cpf: str | None) -> str:
    """Reduz o CPF ao suficiente para rastrear uma execução, sem registrar o documento.

    `39053344705` vira `390.***.**7-05`.
    """
    if not cpf:
        return "-"
    digitos = "".join(c for c in cpf if c.isdigit())
    if len(digitos) != 11:
        return "***"
    return f"{digitos[:3]}.***.**{digitos[8]}-{digitos[9:]}"
