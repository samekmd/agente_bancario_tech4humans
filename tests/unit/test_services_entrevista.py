"""Testes do slot filling da entrevista e da conclusão com recálculo de score."""

import pytest

from banco_agil.domain.enums import TipoEmprego
from banco_agil.repositories.clientes import ClientesRepository
from banco_agil.services.entrevista import (
    CAMPOS,
    OPCOES,
    concluir_entrevista,
    conferir_pergunta_feita,
    conferir_valor_do_cliente,
    montar_dados,
    normalizar_valor,
    proximo_campo,
    registrar_slot,
    slots_completos,
)
from banco_agil.utils.exceptions import (
    EntradaInvalidaError,
    RespostaNaoSolicitadaError,
    ValorNaoInformadoError,
)

pytestmark = pytest.mark.unit

COMPLETOS = {
    "renda_mensal": 8000.0,
    "despesas_mensais": 3000.0,
    "tipo_emprego": TipoEmprego.FORMAL,
    "num_dependentes": 0,
    "tem_dividas": False,
}


class TestProximoCampo:
    def test_segue_a_ordem_fixa_dos_campos(self) -> None:
        slots: dict = {}
        vistos = []
        for valor in ("5000", "2000", "formal", "1", "nao"):
            campo = proximo_campo(slots)
            vistos.append(campo)
            slots = registrar_slot(slots, campo, valor)

        assert vistos == list(CAMPOS)
        assert proximo_campo(slots) is None
        assert slots_completos(slots) is True

    def test_nao_pula_campo_preenchido_fora_de_ordem(self) -> None:
        slots = registrar_slot({}, "tem_dividas", "sim")

        assert proximo_campo(slots) == "renda_mensal"

    def test_entrevista_vazia_comeca_no_primeiro_campo(self) -> None:
        assert proximo_campo({}) == "renda_mensal"
        assert slots_completos({}) is False


class TestNormalizarValor:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [("R$ 8.000,00", 8000.0), ("8000", 8000.0), ("7500.50", 7500.5)],
    )
    def test_valores_monetarios(self, valor: str, esperado: float) -> None:
        assert normalizar_valor("renda_mensal", valor) == esperado

    @pytest.mark.parametrize("campo", ["renda_mensal", "despesas_mensais"])
    @pytest.mark.parametrize("valor", ["8 mil", "uns 3 mil", "8k"])
    def test_renda_ambigua_e_recusada_em_vez_de_truncada(self, campo: str, valor: str) -> None:
        """`8 mil` não pode virar R$ 8,00 e entrar na fórmula de score."""
        with pytest.raises(EntradaInvalidaError):
            normalizar_valor(campo, valor)

    def test_milhar_com_ponto_entra_pelo_valor_cheio(self) -> None:
        assert normalizar_valor("renda_mensal", "R$ 8.000") == 8000.0

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("formal", TipoEmprego.FORMAL),
            ("Formal", TipoEmprego.FORMAL),
            ("FORMAL", TipoEmprego.FORMAL),
            ("autônomo", TipoEmprego.AUTONOMO),
            ("Autônomo", TipoEmprego.AUTONOMO),
            ("AUTÔNOMO", TipoEmprego.AUTONOMO),
            ("autonomo", TipoEmprego.AUTONOMO),
            ("autonoma", TipoEmprego.AUTONOMO),
            ("desempregado", TipoEmprego.DESEMPREGADO),
            ("Desempregado", TipoEmprego.DESEMPREGADO),
            ("Desempregada", TipoEmprego.DESEMPREGADO),
            ("  desempregado  ", TipoEmprego.DESEMPREGADO),
        ],
    )
    def test_tipo_de_emprego_ignora_acento_caixa_e_espaco(
        self, valor: str, esperado: TipoEmprego
    ) -> None:
        assert normalizar_valor("tipo_emprego", valor) is esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("Autônomo.", TipoEmprego.AUTONOMO),
            ("formal!", TipoEmprego.FORMAL),
            ('"desempregado"', TipoEmprego.DESEMPREGADO),
            ("Formal,", TipoEmprego.FORMAL),
        ],
    )
    def test_tipo_de_emprego_ignora_pontuacao_de_borda(
        self, valor: str, esperado: TipoEmprego
    ) -> None:
        assert normalizar_valor("tipo_emprego", valor) is esperado

    @pytest.mark.parametrize(("valor", "esperado"), [("sim", True), ("não", False), ("nao", False)])
    def test_dividas_em_linguagem_natural(self, valor: str, esperado: bool) -> None:
        assert normalizar_valor("tem_dividas", valor) is esperado

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("0", 0),
            ("3", 3),
            ("  2  ", 2),
            ("02", 2),
            ("2 filhos", 2),
            ("2 dependentes", 2),
            ("1 filha", 1),
            ("3,0", 3),
            ("3.0", 3),
            (3, 3),
            (3.0, 3),
        ],
    )
    def test_dependentes(self, valor: str | int | float, esperado: int) -> None:
        assert normalizar_valor("num_dependentes", valor) == esperado

    @pytest.mark.parametrize(
        "valor",
        ["1_000", "nenhum", "zero", "dois", "tenho 3", "2.5", "-1", "", 3.5, True, False, None, -1],
    )
    def test_dependentes_recusa_o_que_nao_e_contagem(self, valor: object) -> None:
        with pytest.raises(EntradaInvalidaError):
            normalizar_valor("num_dependentes", valor)

    @pytest.mark.parametrize(("valor", "valor_corrompido"), [("1_000", 1000), (True, 1)])
    def test_regressao_int_nao_aceita_o_que_nao_devia(
        self, valor: object, valor_corrompido: int
    ) -> None:
        """`int()` solto aceitava underscore de literal Python, e `bool` é subclasse de `int`.

        `"1_000"` virava 1000 dependentes, e bastaria trocar a ordem das checagens para
        `True` virar 1. Os dois precisam ser recusa, nunca número.
        """
        try:
            resultado = normalizar_valor("num_dependentes", valor)
        except EntradaInvalidaError:
            return
        assert resultado != valor_corrompido

    @pytest.mark.parametrize(
        ("campo", "valor"),
        [
            ("tipo_emprego", "empresário"),
            ("tipo_emprego", "carteira assinada"),
            ("tipo_emprego", "clt"),
            ("num_dependentes", "vários"),
            ("num_dependentes", "-1"),
            ("tem_dividas", "talvez"),
            ("renda_mensal", "muito"),
            ("estado_civil", "casado"),
        ],
    )
    def test_rejeita_valor_ou_campo_invalido(self, campo: str, valor: str) -> None:
        """Fora das opções continua recusado: quem restringe é a pergunta, não o normalizador."""
        with pytest.raises(EntradaInvalidaError):
            normalizar_valor(campo, valor)


class TestOpcoesOferecidas:
    """As opções apresentadas ao cliente não podem divergir do que o normalizador aceita."""

    def test_toda_opcao_de_vinculo_e_aceita(self) -> None:
        for opcao in OPCOES["tipo_emprego"]:
            assert isinstance(normalizar_valor("tipo_emprego", opcao), TipoEmprego)

    def test_toda_opcao_de_dividas_e_aceita(self) -> None:
        for opcao in OPCOES["tem_dividas"]:
            assert isinstance(normalizar_valor("tem_dividas", opcao), bool)

    def test_as_opcoes_cobrem_todos_os_vinculos_possiveis(self) -> None:
        aceitos = {normalizar_valor("tipo_emprego", o) for o in OPCOES["tipo_emprego"]}

        assert aceitos == set(TipoEmprego)

    def test_so_campos_de_resposta_fechada_tem_opcoes(self) -> None:
        assert set(OPCOES) <= set(CAMPOS)


class TestRegistrarSlot:
    def test_nao_muta_o_dicionario_recebido(self) -> None:
        originais: dict = {}
        registrar_slot(originais, "renda_mensal", "5000")

        assert originais == {}

    def test_sobrescreve_campo_ja_respondido(self) -> None:
        slots = registrar_slot({}, "renda_mensal", "5000")
        slots = registrar_slot(slots, "renda_mensal", "6000")

        assert slots["renda_mensal"] == 6000.0


class TestMontarDados:
    def test_converte_slots_completos(self) -> None:
        dados = montar_dados(COMPLETOS)

        assert dados.renda_mensal == 8000.0
        assert dados.tipo_emprego is TipoEmprego.FORMAL

    def test_recusa_entrevista_incompleta(self) -> None:
        with pytest.raises(EntradaInvalidaError):
            montar_dados({"renda_mensal": 8000.0})


class TestConcluirEntrevista:
    def test_recalcula_e_persiste_o_score(self, repo_clientes: ClientesRepository) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")
        assert cliente.score_atual == 470

        atualizado = concluir_entrevista(cliente, COMPLETOS, repo=repo_clientes)

        assert atualizado.score_atual == 580
        assert repo_clientes.buscar_por_cpf("39053344705").score_atual == 580

    def test_entrevista_incompleta_nao_toca_a_base(self, repo_clientes: ClientesRepository) -> None:
        cliente = repo_clientes.buscar_por_cpf("39053344705")

        with pytest.raises(EntradaInvalidaError):
            concluir_entrevista(cliente, {"renda_mensal": 8000.0}, repo=repo_clientes)

        assert repo_clientes.buscar_por_cpf("39053344705").score_atual == 470


class TestConferirPerguntaFeita:
    """Nenhum campo pode ser registrado sem ter sido perguntado ao cliente."""

    def test_campo_perguntado_passa(self) -> None:
        assert conferir_pergunta_feita("renda_mensal", "renda_mensal") is None

    def test_nada_perguntado_ainda_e_recusado(self) -> None:
        with pytest.raises(RespostaNaoSolicitadaError, match="Ainda não perguntei"):
            conferir_pergunta_feita("renda_mensal", None)

    def test_campo_diferente_do_perguntado_e_recusado(self) -> None:
        with pytest.raises(RespostaNaoSolicitadaError, match="renda_mensal"):
            conferir_pergunta_feita("tem_dividas", "renda_mensal")

    @pytest.mark.parametrize("campo", CAMPOS)
    def test_vale_para_todos_os_cinco_campos(self, campo: str) -> None:
        assert conferir_pergunta_feita(campo, campo) is None
        with pytest.raises(RespostaNaoSolicitadaError):
            conferir_pergunta_feita(campo, None)


class TestValorPrecisaEstarNaFala:
    """`conferir_pergunta_feita` garante *qual* campo; esta, *o que* se registra."""

    @pytest.mark.parametrize(
        ("campo", "valor", "fala"),
        [
            ("renda_mensal", 8000.0, "ganho 8000 por mês"),
            ("despesas_mensais", 3000.0, "R$ 3.000,00"),
            ("tipo_emprego", TipoEmprego.FORMAL, "formal"),
            ("num_dependentes", 2, "tenho 2 filhos"),
            ("tem_dividas", False, "não"),
            ("tem_dividas", False, "não tenho dívidas"),
            ("tem_dividas", True, "sim"),
        ],
    )
    def test_aceita_o_que_o_cliente_respondeu(self, campo: str, valor: object, fala: str) -> None:
        assert conferir_valor_do_cliente(campo, valor, fala) is None

    @pytest.mark.parametrize(
        ("campo", "valor", "fala"),
        [
            ("renda_mensal", 5000.0, "não lembro"),
            ("renda_mensal", 5000.0, "prefiro não informar"),
            ("despesas_mensais", 2000.0, "não faço ideia"),
            ("tipo_emprego", TipoEmprego.FORMAL, "sei lá"),
            ("num_dependentes", 2, "não sei dizer"),
            ("tem_dividas", False, "não sei"),
            ("tem_dividas", False, "prefiro não dizer"),
        ],
    )
    def test_recusa_o_que_o_cliente_nao_disse(self, campo: str, valor: object, fala: str) -> None:
        """Recusar-se a responder não é uma resposta: o agente pergunta de novo."""
        with pytest.raises(ValorNaoInformadoError):
            conferir_valor_do_cliente(campo, valor, fala)

    def test_nao_sei_nao_vira_ausencia_de_dividas(self) -> None:
        """A armadilha: a palavra "não" isolada em "não sei" valeria 200 pontos de score."""
        with pytest.raises(ValorNaoInformadoError):
            conferir_valor_do_cliente("tem_dividas", False, "não sei")
