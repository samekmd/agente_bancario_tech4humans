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


class RespostaNaoSolicitadaError(BancoAgilError):
    """A entrevista tentou registrar um campo que ainda não foi perguntado ao cliente.

    Não é o valor que está inválido — é o momento. O cliente precisa responder à
    pergunta antes de a resposta poder ser gravada.
    """


class ValorNaoInformadoError(BancoAgilError):
    """O valor a registrar não foi dito pelo cliente.

    Não é entrada inválida — é entrada *inventada*. O LLM deduziu um número do limite
    atual, do teto ou do nada, em vez de perguntar. Um sistema bancário não pode
    registrar pedido de crédito com valor que o cliente nunca pronunciou.
    """


class DadosIndisponiveisError(BancoAgilError):
    """Uma base necessária não pôde ser lida (arquivo ausente ou corrompido)."""


class ClienteNaoEncontradoError(BancoAgilError):
    """Nenhum cliente na base corresponde ao CPF informado."""


class SolicitacaoNaoEncontradaError(BancoAgilError):
    """A solicitação de aumento referenciada não existe na base."""


class CotacaoIndisponivelError(BancoAgilError):
    """A cotação de câmbio não pôde ser obtida. Nunca inventar valor."""
