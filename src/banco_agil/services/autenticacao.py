"""Regra de autenticação: conferência de credenciais e contagem de tentativas.

O contador é devolvido já atualizado para o estado do grafo. Nenhuma contagem é feita
pelo LLM nem inferida do número de mensagens.
"""

from banco_agil.domain.enums import MotivoFalhaAuth
from banco_agil.domain.models import ResultadoAutenticacao
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.utils.exceptions import EntradaInvalidaError
from banco_agil.utils.validators import validar_cpf, validar_data_nascimento


def _falha(motivo: MotivoFalhaAuth, tentativas: int, max_tentativas: int) -> ResultadoAutenticacao:
    """Monta o resultado de uma tentativa malsucedida, já com o contador incrementado."""
    return ResultadoAutenticacao(
        autenticado=False,
        cliente=None,
        tentativas=tentativas,
        tentativas_restantes=max(0, max_tentativas - tentativas),
        bloqueado=tentativas >= max_tentativas,
        motivo=motivo,
    )


def autenticar(
    cpf: str,
    data_nascimento: str,
    tentativas_atuais: int = 0,
    max_tentativas: int | None = None,
    repo: ClientesRepository | None = None,
) -> ResultadoAutenticacao:
    """Confere CPF e data de nascimento contra a base e atualiza o contador de tentativas.

    Toda tentativa malsucedida conta, inclusive a que traz o dado em formato inválido —
    o limite do CLAUDE.md é de tentativas totais, não de credenciais bem formadas.
    Uma autenticação bem-sucedida não incrementa o contador.
    """
    if max_tentativas is None:
        from banco_agil.config import get_settings

        max_tentativas = get_settings().max_tentativas_auth

    tentativas = tentativas_atuais + 1

    try:
        cpf_normalizado = validar_cpf(cpf)
    except EntradaInvalidaError:
        return _falha(MotivoFalhaAuth.CPF_INVALIDO, tentativas, max_tentativas)

    try:
        nascimento = validar_data_nascimento(data_nascimento)
    except EntradaInvalidaError:
        return _falha(MotivoFalhaAuth.DATA_INVALIDA, tentativas, max_tentativas)

    cliente = (repo or ClientesRepository()).buscar_por_cpf(cpf_normalizado)
    if cliente is None or cliente.data_nascimento != nascimento:
        return _falha(MotivoFalhaAuth.CREDENCIAIS_INCORRETAS, tentativas, max_tentativas)

    return ResultadoAutenticacao(
        autenticado=True,
        cliente=cliente,
        tentativas=tentativas_atuais,
        tentativas_restantes=max(0, max_tentativas - tentativas_atuais),
        bloqueado=False,
        motivo=None,
    )
