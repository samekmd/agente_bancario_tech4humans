"""Testes da camada de I/O de CSV: leitura, escrita atômica e append."""

from datetime import datetime
from pathlib import Path

import pytest

from banco_agil.domain.enums import StatusPedido
from banco_agil.repositories.base import anexar_linha, escrever_csv, ler_csv
from banco_agil.utils.exceptions import DadosIndisponiveisError

pytestmark = pytest.mark.unit

COLUNAS = ("a", "b", "c")


def test_round_trip_preserva_colunas_e_ordem(tmp_path: Path) -> None:
    destino = tmp_path / "saida.csv"
    escrever_csv(destino, COLUNAS, [{"a": "1", "b": "2", "c": "3"}])

    assert destino.read_text(encoding="utf-8").splitlines()[0] == "a,b,c"
    assert ler_csv(destino) == [{"a": "1", "b": "2", "c": "3"}]


def test_ler_arquivo_ausente_levanta_dados_indisponiveis(tmp_path: Path) -> None:
    with pytest.raises(DadosIndisponiveisError):
        ler_csv(tmp_path / "nao_existe.csv")


def test_escrita_nao_deixa_arquivo_temporario(tmp_path: Path) -> None:
    destino = tmp_path / "saida.csv"
    escrever_csv(destino, COLUNAS, [{"a": "1", "b": "2", "c": "3"}])

    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_anexar_cria_arquivo_com_cabecalho(tmp_path: Path) -> None:
    destino = tmp_path / "novo.csv"
    anexar_linha(destino, COLUNAS, {"a": "1", "b": "2", "c": "3"})

    assert destino.exists()
    assert destino.read_text(encoding="utf-8").splitlines()[0] == "a,b,c"
    assert len(ler_csv(destino)) == 1


def test_anexar_preserva_linhas_existentes(tmp_path: Path) -> None:
    destino = tmp_path / "novo.csv"
    anexar_linha(destino, COLUNAS, {"a": "1", "b": "2", "c": "3"})
    anexar_linha(destino, COLUNAS, {"a": "4", "b": "5", "c": "6"})

    assert [linha["a"] for linha in ler_csv(destino)] == ["1", "4"]


def test_serializacao_de_float_enum_datetime_e_none(tmp_path: Path) -> None:
    destino = tmp_path / "tipos.csv"
    colunas = ("valor", "status", "quando", "vazio")
    escrever_csv(
        destino,
        colunas,
        [
            {
                "valor": 5000.0,
                "status": StatusPedido.PENDENTE,
                "quando": datetime(2026, 8, 28, 13, 45),
                "vazio": None,
            }
        ],
    )

    linha = ler_csv(destino)[0]
    assert linha["valor"] == "5000.00"
    assert linha["status"] == "pendente"
    assert linha["quando"] == "2026-08-28T13:45:00"
    assert linha["vazio"] == ""


def test_escrita_falha_sem_corromper_arquivo_original(tmp_path: Path) -> None:
    destino = tmp_path / "saida.csv"
    escrever_csv(destino, COLUNAS, [{"a": "1", "b": "2", "c": "3"}])

    def linhas_com_erro() -> object:
        yield {"a": "9", "b": "9", "c": "9"}
        raise RuntimeError("falha no meio da escrita")

    with pytest.raises(RuntimeError):
        escrever_csv(destino, COLUNAS, linhas_com_erro())

    assert ler_csv(destino) == [{"a": "1", "b": "2", "c": "3"}]
    assert [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
