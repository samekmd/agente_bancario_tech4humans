"""Enums do domínio: agentes, status de pedido, tipos de emprego."""

from enum import StrEnum


class Agente(StrEnum):
    """Especializações internas do atendimento. Escrito no estado pelas handoff tools."""

    TRIAGEM = "triagem"
    CREDITO = "credito"
    ENTREVISTA_CREDITO = "entrevista_credito"
    CAMBIO = "cambio"


class StatusPedido(StrEnum):
    """Status de uma solicitação de aumento de limite."""

    PENDENTE = "pendente"
    APROVADO = "aprovado"
    REJEITADO = "rejeitado"


class MotivoFalhaAuth(StrEnum):
    """Por que uma tentativa de autenticação falhou. O agente verbaliza; a decisão é daqui."""

    CPF_INVALIDO = "cpf_invalido"
    DATA_INVALIDA = "data_invalida"
    CREDENCIAIS_INCORRETAS = "credenciais_incorretas"


class TipoEmprego(StrEnum):
    """Vínculo de trabalho declarado na entrevista de crédito."""

    FORMAL = "formal"
    AUTONOMO = "autonomo"
    DESEMPREGADO = "desempregado"
