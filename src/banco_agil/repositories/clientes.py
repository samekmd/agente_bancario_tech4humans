"""Repositório da base de clientes (leitura e atualização de score).

Nunca expõe a base inteira: só devolve o registro do CPF consultado (regra 9).
"""

from pathlib import Path

from banco_agil.domain.models import Cliente
from banco_agil.repositories.base import escrever_csv, ler_csv
from banco_agil.utils.exceptions import ClienteNaoEncontradoError
from banco_agil.utils.logging import get_logger, mascarar_cpf
from banco_agil.utils.validators import normalizar_cpf

logger = get_logger("repositories.clientes")

COLUNAS = ("cpf", "nome", "data_nascimento", "limite_atual", "score_atual")


class ClientesRepository:
    """Acesso a `clientes.csv`."""

    def __init__(self, caminho: Path | None = None) -> None:
        if caminho is None:
            from banco_agil.config import get_settings

            caminho = get_settings().clientes_csv
        self.caminho = caminho

    def _linhas(self) -> list[dict[str, str]]:
        return ler_csv(self.caminho)

    @staticmethod
    def _para_modelo(linha: dict[str, str]) -> Cliente:
        return Cliente(
            cpf=linha["cpf"],
            nome=linha["nome"],
            data_nascimento=linha["data_nascimento"],
            limite_atual=float(linha["limite_atual"]),
            score_atual=int(linha["score_atual"]),
        )

    def buscar_por_cpf(self, cpf: str) -> Cliente | None:
        """Retorna o cliente do CPF informado, ou `None` se ele não estiver na base.

        Aceita o CPF com ou sem pontuação.
        """
        alvo = normalizar_cpf(cpf)
        for linha in self._linhas():
            if linha["cpf"] == alvo:
                return self._para_modelo(linha)
        return None

    def atualizar_score(self, cpf: str, novo_score: int) -> Cliente:
        """Grava o novo score do cliente e devolve o registro atualizado.

        Levanta `ClienteNaoEncontradoError` se o CPF não existir na base.
        """
        alvo = normalizar_cpf(cpf)
        logger.info(
            "atualizando score de cpf=%s para %d em %s",
            mascarar_cpf(alvo),
            novo_score,
            self.caminho.name,
        )
        linhas = self._linhas()
        atualizado: Cliente | None = None
        for linha in linhas:
            if linha["cpf"] == alvo:
                anterior = linha["score_atual"]
                atualizado = self._para_modelo({**linha, "score_atual": str(novo_score)})
                linha["score_atual"] = str(atualizado.score_atual)
                logger.debug("linha encontrada: score %s -> %s", anterior, linha["score_atual"])
                break
        if atualizado is None:
            logger.warning("cpf=%s não está na base %s", mascarar_cpf(alvo), self.caminho.name)
            raise ClienteNaoEncontradoError("Não encontrei esse CPF na nossa base.")
        escrever_csv(self.caminho, COLUNAS, linhas)
        logger.info("score persistido: %d linhas reescritas em %s", len(linhas), self.caminho.name)
        return atualizado
