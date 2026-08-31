"""Leitura de CSV e escrita atômica (arquivo temporário + os.replace) sob filelock.

Único ponto do sistema que abre arquivo. Nenhuma camada acima chama `open` em CSV.
"""

import csv
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from filelock import FileLock

from banco_agil.observability.tracing import TOOL, span
from banco_agil.utils.exceptions import DadosIndisponiveisError

TIMEOUT_LOCK_S = 10.0


def _lock(caminho: Path) -> FileLock:
    """Lock de arquivo vizinho ao CSV, serializando leitura e escrita concorrentes."""
    return FileLock(f"{caminho}.lock", timeout=TIMEOUT_LOCK_S)


def _formatar(valor: Any) -> str:  # noqa: ANN401 - serializa qualquer campo de modelo
    """Serializa um valor para o CSV segundo os contratos de dados do projeto."""
    if valor is None:
        return ""
    if isinstance(valor, Enum):
        return str(valor.value)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, float):
        return f"{valor:.2f}"
    return str(valor)


def _ler(caminho: Path) -> list[dict[str, str]]:
    """Lê o CSV sem adquirir o lock. Uso interno, sempre dentro de um `_lock`."""
    with caminho.open(newline="", encoding="utf-8") as arquivo:
        leitor = csv.DictReader(arquivo)
        if leitor.fieldnames is None:
            raise DadosIndisponiveisError(f"Base de dados sem cabeçalho: {caminho.name}.")
        return [dict(linha) for linha in leitor]


def _escrever(caminho: Path, colunas: Sequence[str], linhas: Iterable[Mapping[str, Any]]) -> None:
    """Escreve o CSV atomicamente sem adquirir o lock. Uso interno, dentro de um `_lock`.

    O temporário nasce no mesmo diretório do destino, condição para o `os.replace` ser
    atômico. Uma falha no meio da escrita deixa o arquivo original intacto.
    """
    caminho.parent.mkdir(parents=True, exist_ok=True)
    temporario = tempfile.NamedTemporaryFile(
        mode="w",
        newline="",
        encoding="utf-8",
        dir=caminho.parent,
        prefix=f".{caminho.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with temporario as arquivo:
            escritor = csv.DictWriter(arquivo, fieldnames=list(colunas))
            escritor.writeheader()
            for linha in linhas:
                escritor.writerow({coluna: _formatar(linha.get(coluna)) for coluna in colunas})
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario.name, caminho)
    except BaseException:
        Path(temporario.name).unlink(missing_ok=True)
        raise


def ler_csv(caminho: Path) -> list[dict[str, str]]:
    """Lê um CSV inteiro como lista de dicionários de strings.

    Levanta `DadosIndisponiveisError` se o arquivo não existir ou não tiver cabeçalho.
    """
    if not caminho.exists():
        raise DadosIndisponiveisError(f"Base de dados indisponível: {caminho.name}.")
    with span("ler_csv", TOOL, arquivo=caminho.name) as observado, _lock(caminho):
        linhas = _ler(caminho)
        observado.set_outputs({"linhas": len(linhas)})
        return linhas


def escrever_csv(
    caminho: Path,
    colunas: Sequence[str],
    linhas: Iterable[Mapping[str, Any]],
) -> None:
    """Reescreve o CSV inteiro de forma atômica, sob lock."""
    materializadas = list(linhas)
    with (
        span("escrever_csv", TOOL, arquivo=caminho.name, linhas=len(materializadas)),
        _lock(caminho),
    ):
        _escrever(caminho, colunas, materializadas)


def anexar_linha(caminho: Path, colunas: Sequence[str], linha: Mapping[str, Any]) -> None:
    """Acrescenta uma linha ao CSV, criando o arquivo com cabeçalho se não existir.

    Leitura e escrita acontecem sob o mesmo lock, para que dois pedidos simultâneos não
    sobrescrevam um ao outro.
    """
    with _lock(caminho):
        existentes = _ler(caminho) if caminho.exists() else []
        _escrever(caminho, colunas, [*existentes, linha])
