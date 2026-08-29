"""Exceções de domínio. Nunca atravessam a fronteira de uma tool.

Services e repositories levantam; as tools capturam e convertem em `{"ok": False, ...}`
com uma mensagem que o agente possa verbalizar.
"""


class BancoAgilError(Exception):
    """Base de todas as exceções de domínio do atendimento."""

    def __init__(self, mensagem: str) -> None:
        super().__init__(mensagem)
        self.mensagem = mensagem


class EntradaInvalidaError(BancoAgilError):
    """Dado informado pelo cliente não passou na validação de formato."""


class DadosIndisponiveisError(BancoAgilError):
    """Uma base necessária não pôde ser lida (arquivo ausente ou corrompido)."""


class ClienteNaoEncontradoError(BancoAgilError):
    """Nenhum cliente na base corresponde ao CPF informado."""


class SolicitacaoNaoEncontradaError(BancoAgilError):
    """A solicitação de aumento referenciada não existe na base."""


class CotacaoIndisponivelError(BancoAgilError):
    """A cotação de câmbio não pôde ser obtida. Nunca inventar valor."""
