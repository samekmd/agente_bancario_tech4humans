"""Modelos Pydantic do domínio: Cliente, SolicitacaoAumento, FaixaLimite e afins.

Validação de formato mora aqui. Regra de negócio, não — essa vive em `services/`.
"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from banco_agil.domain.enums import MotivoFalhaAuth, StatusPedido, TipoEmprego


class Cliente(BaseModel):
    """Registro de um cliente da base. Espelha uma linha de `clientes.csv`."""

    cpf: str = Field(pattern=r"^\d{11}$")
    nome: str
    data_nascimento: date
    limite_atual: float = Field(ge=0)
    score_atual: int = Field(ge=0, le=1000)


class FaixaLimite(BaseModel):
    """Faixa de score e o limite máximo que ela autoriza. Linha de `score_limite.csv`."""

    score_min: int = Field(ge=0, le=1000)
    score_max: int = Field(ge=0, le=1000)
    limite_maximo: float = Field(ge=0)


class SolicitacaoAumento(BaseModel):
    """Pedido de aumento de limite. Espelha uma linha de `solicitacoes_aumento_limite.csv`."""

    cpf_cliente: str = Field(pattern=r"^\d{11}$")
    data_hora_solicitacao: datetime
    limite_atual: float = Field(ge=0)
    novo_limite_solicitado: float = Field(ge=0)
    status_pedido: StatusPedido = StatusPedido.PENDENTE


class DadosEntrevista(BaseModel):
    """Os cinco campos coletados na entrevista de crédito, entrada da fórmula de score."""

    renda_mensal: float = Field(ge=0)
    despesas_mensais: float = Field(ge=0)
    tipo_emprego: TipoEmprego
    num_dependentes: int = Field(ge=0)
    tem_dividas: bool


class ResultadoAutenticacao(BaseModel):
    """Desfecho de uma tentativa de autenticação, com o contador já atualizado.

    Só carrega números e enums: a mensagem ao cliente é construída pelo agente.
    """

    autenticado: bool
    cliente: Cliente | None = None
    tentativas: int = Field(ge=0)
    tentativas_restantes: int = Field(ge=0)
    bloqueado: bool = False
    motivo: MotivoFalhaAuth | None = None


class ResultadoAvaliacao(BaseModel):
    """Desfecho da avaliação de um pedido de aumento de limite."""

    aprovado: bool
    status_pedido: StatusPedido
    score_considerado: int = Field(ge=0, le=1000)
    limite_maximo: float = Field(ge=0)
    limite_solicitado: float = Field(ge=0)


class Cotacao(BaseModel):
    """Cotação de um par de moedas, como devolvida pela fonte externa."""

    par: str
    moeda_origem: str
    moeda_destino: str
    compra: float = Field(gt=0)
    venda: float = Field(gt=0)
    atualizado_em: datetime
    fonte: str
