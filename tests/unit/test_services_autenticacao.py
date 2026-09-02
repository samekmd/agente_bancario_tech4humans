"""Testes da autenticação: conferência de credenciais e contagem de tentativas."""

import pytest

from banco_agil.domain.enums import MotivoFalhaAuth
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.services.autenticacao import autenticar

pytestmark = pytest.mark.unit

CPF = "52998224725"
NASCIMENTO = "12/03/1985"


def test_credenciais_corretas_autenticam(repo_clientes: ClientesRepository) -> None:
    resultado = autenticar(CPF, NASCIMENTO, repo=repo_clientes)

    assert resultado.autenticado is True
    assert resultado.cliente is not None
    assert resultado.cliente.nome == "Helena Ribeiro Antunes"
    assert resultado.motivo is None


def test_aceita_cpf_pontuado_e_data_iso(repo_clientes: ClientesRepository) -> None:
    assert autenticar("529.982.247-25", "1985-03-12", repo=repo_clientes).autenticado is True


def test_sucesso_nao_incrementa_o_contador(repo_clientes: ClientesRepository) -> None:
    resultado = autenticar(CPF, NASCIMENTO, tentativas_atuais=1, repo=repo_clientes)

    assert resultado.autenticado is True
    assert resultado.tentativas == 1


def test_data_de_nascimento_errada_nao_autentica(repo_clientes: ClientesRepository) -> None:
    resultado = autenticar(CPF, "01/01/1990", repo=repo_clientes)

    assert resultado.autenticado is False
    assert resultado.cliente is None
    assert resultado.motivo is MotivoFalhaAuth.CREDENCIAIS_INCORRETAS


def test_cpf_fora_da_base_nao_autentica(repo_clientes: ClientesRepository) -> None:
    # CPF com dígito verificador válido, mas ausente da base.
    resultado = autenticar("12345678909", NASCIMENTO, repo=repo_clientes)

    assert resultado.autenticado is False
    assert resultado.motivo is MotivoFalhaAuth.CREDENCIAIS_INCORRETAS


def test_cpf_malformado_e_reportado_como_tal(repo_clientes: ClientesRepository) -> None:
    resultado = autenticar("111", NASCIMENTO, repo=repo_clientes)

    assert resultado.motivo is MotivoFalhaAuth.CPF_INVALIDO


def test_data_malformada_e_reportada_como_tal(repo_clientes: ClientesRepository) -> None:
    resultado = autenticar(CPF, "ontem", repo=repo_clientes)

    assert resultado.motivo is MotivoFalhaAuth.DATA_INVALIDA


def test_nunca_devolve_cliente_em_falha(repo_clientes: ClientesRepository) -> None:
    """Regra 9: nenhum dado de cliente entra no contexto sem autenticação."""
    for cpf, nascimento in [("111", NASCIMENTO), (CPF, "01/01/1990"), ("12345678909", NASCIMENTO)]:
        assert autenticar(cpf, nascimento, repo=repo_clientes).cliente is None


class TestContagemDeTentativas:
    def test_conta_a_partir_do_valor_recebido(self, repo_clientes: ClientesRepository) -> None:
        resultado = autenticar("111", NASCIMENTO, tentativas_atuais=0, repo=repo_clientes)

        assert resultado.tentativas == 1
        assert resultado.tentativas_restantes == 2
        assert resultado.bloqueado is False

    def test_bloqueia_na_terceira_falha(self, repo_clientes: ClientesRepository) -> None:
        resultado = autenticar(CPF, "01/01/1990", tentativas_atuais=2, repo=repo_clientes)

        assert resultado.tentativas == 3
        assert resultado.tentativas_restantes == 0
        assert resultado.bloqueado is True

    def test_formato_invalido_tambem_consome_tentativa(
        self, repo_clientes: ClientesRepository
    ) -> None:
        resultado = autenticar("111", NASCIMENTO, tentativas_atuais=2, repo=repo_clientes)

        assert resultado.bloqueado is True

    def test_limite_e_configuravel(self, repo_clientes: ClientesRepository) -> None:
        resultado = autenticar(
            "111", NASCIMENTO, tentativas_atuais=0, max_tentativas=1, repo=repo_clientes
        )

        assert resultado.bloqueado is True


class TestUmaTentativaPorTurno:
    """O limite é de tentativas do cliente, não de chamadas da ferramenta.

    Nos logs de 02/09 o agente chamou `autenticar_cliente` duas vezes na mesma invocação,
    com 515 ms entre elas: uma única mensagem do cliente consumiu duas das três chances
    dele. `ja_contabilizada` é o que impede a segunda chamada de cobrar de novo.
    """

    def test_segunda_chamada_no_mesmo_turno_nao_incrementa(
        self, repo_clientes: ClientesRepository
    ) -> None:
        primeira = autenticar(CPF, "01/01/1990", tentativas_atuais=0, repo=repo_clientes)
        segunda = autenticar(
            CPF,
            "02/02/1991",
            tentativas_atuais=primeira.tentativas,
            ja_contabilizada=True,
            repo=repo_clientes,
        )

        assert primeira.tentativas == 1
        assert segunda.tentativas == 1
        assert segunda.tentativas_restantes == 2
        assert segunda.bloqueado is False

    def test_o_bloqueio_ainda_acontece_na_terceira_mensagem(
        self, repo_clientes: ClientesRepository
    ) -> None:
        """Três mensagens do cliente bloqueiam, mesmo com chamadas repetidas em cada uma."""
        tentativas = 0
        for _ in range(3):
            # Primeira chamada do turno: cobra.
            resultado = autenticar(
                CPF, "01/01/1990", tentativas_atuais=tentativas, repo=repo_clientes
            )
            # O agente insiste no mesmo turno: não cobra.
            resultado = autenticar(
                CPF,
                "01/01/1990",
                tentativas_atuais=resultado.tentativas,
                ja_contabilizada=True,
                repo=repo_clientes,
            )
            tentativas = resultado.tentativas

        assert tentativas == 3
        assert resultado.bloqueado is True

    def test_turno_ja_cobrado_no_limite_continua_bloqueado(
        self, repo_clientes: ClientesRepository
    ) -> None:
        """Não contar de novo não pode desfazer um bloqueio já atingido."""
        resultado = autenticar(
            CPF, "01/01/1990", tentativas_atuais=3, ja_contabilizada=True, repo=repo_clientes
        )

        assert resultado.tentativas == 3
        assert resultado.tentativas_restantes == 0
        assert resultado.bloqueado is True

    def test_sucesso_no_turno_ja_cobrado_autentica(self, repo_clientes: ClientesRepository) -> None:
        """Errar e acertar na mesma mensagem ainda autentica."""
        resultado = autenticar(
            CPF, NASCIMENTO, tentativas_atuais=1, ja_contabilizada=True, repo=repo_clientes
        )

        assert resultado.autenticado is True
        assert resultado.tentativas == 1
