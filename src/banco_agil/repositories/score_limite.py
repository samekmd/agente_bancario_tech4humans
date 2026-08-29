"""Repositório das faixas de score e limite máximo (somente leitura)."""

from pathlib import Path

from banco_agil.domain.models import FaixaLimite
from banco_agil.repositories.base import ler_csv

COLUNAS = ("score_min", "score_max", "limite_maximo")


class ScoreLimiteRepository:
    """Acesso a `score_limite.csv`. Base imutável em runtime."""

    def __init__(self, caminho: Path | None = None) -> None:
        if caminho is None:
            from banco_agil.config import get_settings

            caminho = get_settings().score_limite_csv
        self.caminho = caminho

    def listar_faixas(self) -> list[FaixaLimite]:
        """Retorna todas as faixas de score, na ordem em que aparecem no arquivo."""
        return [
            FaixaLimite(
                score_min=int(linha["score_min"]),
                score_max=int(linha["score_max"]),
                limite_maximo=float(linha["limite_maximo"]),
            )
            for linha in ler_csv(self.caminho)
        ]
