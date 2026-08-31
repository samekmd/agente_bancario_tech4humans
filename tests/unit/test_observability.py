"""Testes da observabilidade — todos offline, com o tracing desligado.

A regra que estes testes protegem é uma só: **observar nunca pode alterar o atendimento.**
Servidor fora do ar, MLflow ausente ou falha ao gravar tag não podem virar erro para o
cliente, nem atrasar resposta, nem escrever arquivo em disco.
"""

from typing import Any

import pytest

from banco_agil.observability import setup, tags, tracing
from banco_agil.observability.tracing import TASK, span

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def tracing_desligado(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Desliga o tracing e devolve o MLflow ao estado limpo depois de cada teste.

    Sem a limpeza, um teste que configura o MLflow de verdade deixa autolog ligado e a
    tracking URI apontando para lugar nenhum — e os testes seguintes, que só exercitam
    tools, passam a emitir trace e a tentar exportá-lo.
    """
    import mlflow

    uri_original = mlflow.get_tracking_uri()
    monkeypatch.setattr(setup, "_ativo", False)
    monkeypatch.setattr(setup, "_configurado", True)
    yield
    mlflow.langchain.autolog(disable=True)
    mlflow.set_tracking_uri(uri_original)


class TestSpanDesligado:
    def test_entrega_objeto_utilizavel_sem_tracing(self) -> None:
        """Sem span inerte, cada ponto instrumentado precisaria de `if span is not None`."""
        with span("qualquer", TASK, entrada=1) as observado:
            observado.set_inputs({"a": 1})
            observado.set_outputs({"b": 2})
            observado.set_attributes({"c": 3})

        assert observado is tracing.INERTE

    def test_nao_toca_o_mlflow_quando_desligado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Um `start_span` solto cria banco local em disco só por existir."""

        def proibido(*a: Any, **k: Any) -> None:
            raise AssertionError("o MLflow não deveria ser chamado com o tracing desligado")

        import mlflow

        monkeypatch.setattr(mlflow, "start_span", proibido)
        with span("qualquer", TASK):
            pass

    def test_excecao_dentro_do_bloco_continua_subindo(self) -> None:
        """Tracing registra o erro, mas nunca engole erro de negócio."""
        with pytest.raises(ValueError, match="erro de negócio"), span("qualquer", TASK):
            raise ValueError("erro de negócio")

    def test_valor_de_retorno_do_bloco_e_preservado(self) -> None:
        def calcular() -> int:
            with span("calculo", TASK):
                return 42

        assert calcular() == 42


class TestSpanComFalhaDoMlflow:
    def test_falha_ao_abrir_span_nao_interrompe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(setup, "_ativo", True)

        import mlflow

        def explode(*a: Any, **k: Any) -> None:
            raise RuntimeError("servidor fora do ar")

        monkeypatch.setattr(mlflow, "start_span", explode)

        with span("qualquer", TASK) as observado:
            observado.set_outputs({"ok": True})

        assert observado is tracing.INERTE


class TestTags:
    def test_sao_no_op_silencioso_com_tracing_desligado(self) -> None:
        tags.marcar(qualquer="coisa")
        tags.marcar_cliente("39053344705")
        tags.marcar_agente("credito")
        tags.marcar_desfecho_pedido("rejeitado", 6000.0)
        tags.marcar_entrevista(470, 580)
        tags.marcar_erro("algo falhou", "tools.credito")

    def test_cliente_e_marcado_com_cpf_mascarado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Trace é dado armazenado e navegável: o documento inteiro não entra."""
        monkeypatch.setattr(setup, "_ativo", True)
        registradas: dict[str, str] = {}

        import mlflow

        monkeypatch.setattr(
            mlflow, "update_current_trace", lambda tags=None, **k: registradas.update(tags or {})
        )
        tags.marcar_cliente("390.533.447-05")

        assert registradas == {"cliente": "390.***.**7-05"}
        assert "39053344705" not in str(registradas)

    def test_valores_nulos_nao_viram_tag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(setup, "_ativo", True)
        registradas: dict[str, str] = {}

        import mlflow

        monkeypatch.setattr(
            mlflow, "update_current_trace", lambda tags=None, **k: registradas.update(tags or {})
        )
        tags.marcar_desfecho_pedido("aprovado", None)

        assert registradas == {"desfecho_pedido": "aprovado"}

    def test_falha_ao_gravar_tag_nao_interrompe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(setup, "_ativo", True)

        import mlflow

        def explode(**k: Any) -> None:
            raise RuntimeError("servidor fora do ar")

        monkeypatch.setattr(mlflow, "update_current_trace", explode)
        tags.marcar(qualquer="coisa")


class TestConfigurarMlflow:
    def test_desligado_por_configuracao_devolve_falso(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(setup, "_configurado", False)
        monkeypatch.setattr(setup, "_ativo", False)
        monkeypatch.setenv("MLFLOW_HABILITADO", "false")

        from banco_agil.config import get_settings

        get_settings.cache_clear()
        try:
            assert setup.configurar_mlflow() is False
            assert setup.tracing_ativo() is False
        finally:
            get_settings.cache_clear()

    def test_servidor_inalcancavel_nao_levanta(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """O atendimento tem que seguir igual com o servidor do MLflow fora do ar."""
        monkeypatch.setattr(setup, "_configurado", False)
        monkeypatch.setattr(setup, "_ativo", False)

        import mlflow

        def explode(*a: Any, **k: Any) -> None:
            raise RuntimeError("Connection refused")

        monkeypatch.setattr(mlflow, "set_experiment", explode)

        assert setup.configurar_mlflow(tracking_uri="http://localhost:1") is False
        assert setup.tracing_ativo() is False

    def test_e_idempotente(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chamadas: list[int] = []
        monkeypatch.setattr(setup, "_configurado", False)
        monkeypatch.setattr(setup, "_ativo", False)

        import mlflow

        monkeypatch.setattr(mlflow, "set_tracking_uri", lambda *a, **k: chamadas.append(1))
        monkeypatch.setattr(mlflow, "set_experiment", lambda *a, **k: None)
        monkeypatch.setattr(mlflow.langchain, "autolog", lambda *a, **k: None)

        setup.configurar_mlflow()
        setup.configurar_mlflow()
        setup.configurar_mlflow()

        assert len(chamadas) == 1
