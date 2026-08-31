"""Repositório das solicitações de aumento de limite (gerado em runtime).

Sem coluna de id no contrato de dados, a chave de uma linha é o par
`(cpf_cliente, data_hora_solicitacao)`.
"""

from datetime import datetime
from pathlib import Path

from banco_agil.domain.enums import StatusPedido
from banco_agil.domain.models import SolicitacaoAumento
from banco_agil.repositories.base import anexar_linha, escrever_csv, ler_csv
from banco_agil.utils.exceptions import SolicitacaoNaoEncontradaError
from banco_agil.utils.logging import dump_seguro, get_logger, mascarar_cpf

logger = get_logger("repositories.solicitacoes")

COLUNAS = (
    "cpf_cliente",
    "data_hora_solicitacao",
    "limite_atual",
    "novo_limite_solicitado",
    "status_pedido",
)


class SolicitacoesRepository:
    """Acesso a `solicitacoes_aumento_limite.csv`."""

    def __init__(self, caminho: Path | None = None) -> None:
        if caminho is None:
            from banco_agil.config import get_settings

            caminho = get_settings().solicitacoes_csv
        self.caminho = caminho

    @staticmethod
    def _para_modelo(linha: dict[str, str]) -> SolicitacaoAumento:
        return SolicitacaoAumento(
            cpf_cliente=linha["cpf_cliente"],
            data_hora_solicitacao=linha["data_hora_solicitacao"],
            limite_atual=float(linha["limite_atual"]),
            novo_limite_solicitado=float(linha["novo_limite_solicitado"]),
            status_pedido=StatusPedido(linha["status_pedido"]),
        )

    def registrar(self, solicitacao: SolicitacaoAumento) -> SolicitacaoAumento:
        """Grava o pedido no CSV, criando o arquivo com cabeçalho na primeira execução."""
        novo_arquivo = not self.caminho.exists()
        linha = solicitacao.model_dump()
        logger.info(
            "gravando solicitação: cpf=%s, %s, status=%s%s",
            mascarar_cpf(solicitacao.cpf_cliente),
            solicitacao.data_hora_solicitacao.isoformat(),
            solicitacao.status_pedido.value,
            " (criando arquivo com cabeçalho)" if novo_arquivo else "",
        )
        logger.debug("linha a gravar: %s", dump_seguro(solicitacao))
        anexar_linha(self.caminho, COLUNAS, linha)
        return solicitacao

    def atualizar_status(
        self,
        cpf_cliente: str,
        data_hora_solicitacao: datetime,
        status: StatusPedido,
    ) -> SolicitacaoAumento:
        """Atualiza o status de um pedido já registrado e devolve a linha atualizada.

        Levanta `SolicitacaoNaoEncontradaError` se o par CPF + data/hora não existir.
        """
        carimbo = data_hora_solicitacao.isoformat()
        logger.info(
            "atualizando status para %s: cpf=%s, %s",
            status.value,
            mascarar_cpf(cpf_cliente),
            carimbo,
        )
        linhas = ler_csv(self.caminho)
        atualizada: SolicitacaoAumento | None = None
        for linha in linhas:
            if linha["cpf_cliente"] == cpf_cliente and linha["data_hora_solicitacao"] == carimbo:
                logger.debug(
                    "linha alvo encontrada, status %s -> %s", linha["status_pedido"], status.value
                )
                linha["status_pedido"] = status.value
                atualizada = self._para_modelo(linha)
                break
        if atualizada is None:
            logger.error(
                "solicitação não encontrada: cpf=%s, %s | carimbos no arquivo: %s",
                mascarar_cpf(cpf_cliente),
                carimbo,
                [linha["data_hora_solicitacao"] for linha in linhas],
            )
            raise SolicitacaoNaoEncontradaError("Não encontrei essa solicitação de aumento.")
        escrever_csv(self.caminho, COLUNAS, linhas)
        logger.info("status persistido em %s (%d linhas)", self.caminho.name, len(linhas))
        return atualizada

    def listar_por_cpf(self, cpf_cliente: str) -> list[SolicitacaoAumento]:
        """Retorna as solicitações do CPF informado, e apenas dele (regra 9)."""
        if not self.caminho.exists():
            return []
        return [
            self._para_modelo(linha)
            for linha in ler_csv(self.caminho)
            if linha["cpf_cliente"] == cpf_cliente
        ]
