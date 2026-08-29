"""Testes da cotação de câmbio, com transporte falso — nenhum teste toca a rede."""

from datetime import UTC, datetime

import httpx
import pytest

from banco_agil.domain.models import Cotacao
from banco_agil.services.cotacao import (
    converter,
    converter_inverso,
    normalizar_par,
    obter_cotacao,
)
from banco_agil.utils.exceptions import CotacaoIndisponivelError, EntradaInvalidaError

pytestmark = pytest.mark.unit

BASE_URL = "https://economia.exemplo/json/last"

PAYLOAD = {
    "USDBRL": {
        "code": "USD",
        "codein": "BRL",
        "name": "Dólar Americano/Real Brasileiro",
        "high": "5.2289",
        "low": "5.159",
        "varBid": "0.0441",
        "pctChange": "0.854307",
        "bid": "5.2062",
        "ask": "5.2073",
        "timestamp": "1787943062",
        "create_date": "2026-08-28 15:51:02",
    }
}


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutraliza o backoff para os testes não dormirem."""
    monkeypatch.setattr("banco_agil.services.cotacao.time.sleep", lambda _: None)


@pytest.fixture
def cotacao() -> Cotacao:
    return Cotacao(
        par="USD-BRL",
        moeda_origem="USD",
        moeda_destino="BRL",
        compra=5.0,
        venda=5.2,
        atualizado_em=datetime(2026, 8, 28, 15, 51, tzinfo=UTC),
        fonte="AwesomeAPI",
    )


class TestNormalizarPar:
    @pytest.mark.parametrize("entrada", ["USD-BRL", "usd-brl", " Usd-Brl "])
    def test_normaliza_para_maiusculas(self, entrada: str) -> None:
        assert normalizar_par(entrada) == "USD-BRL"

    @pytest.mark.parametrize("entrada", ["USDBRL", "dólar", "", "US-BRL"])
    def test_rejeita_formato_invalido(self, entrada: str) -> None:
        with pytest.raises(EntradaInvalidaError):
            normalizar_par(entrada)


class TestObterCotacao:
    def test_traduz_o_payload_da_fonte(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/USD-BRL")
            return httpx.Response(200, json=PAYLOAD)

        resultado = obter_cotacao(
            "USD-BRL", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=0
        )

        assert resultado.moeda_origem == "USD"
        assert resultado.moeda_destino == "BRL"
        assert resultado.compra == 5.2062
        assert resultado.venda == 5.2073
        assert resultado.atualizado_em == datetime.fromtimestamp(1787943062, tz=UTC)
        assert resultado.fonte == "AwesomeAPI"

    def test_retenta_e_devolve_a_cotacao_apos_falha_transitoria(self) -> None:
        chamadas: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            chamadas.append(1)
            if len(chamadas) < 3:
                return httpx.Response(503)
            return httpx.Response(200, json=PAYLOAD)

        resultado = obter_cotacao(
            "USD-BRL", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=2
        )

        assert len(chamadas) == 3
        assert resultado.compra == 5.2062

    def test_erro_de_rede_esgota_as_tentativas_e_levanta(self) -> None:
        chamadas: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            chamadas.append(1)
            raise httpx.ConnectError("sem rede")

        with pytest.raises(CotacaoIndisponivelError):
            obter_cotacao(
                "USD-BRL", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=2
            )

        assert len(chamadas) == 3

    def test_par_inexistente_nao_e_retentado(self) -> None:
        chamadas: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            chamadas.append(1)
            return httpx.Response(404)

        with pytest.raises(CotacaoIndisponivelError):
            obter_cotacao(
                "XXX-BRL", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=2
            )

        assert len(chamadas) == 1

    def test_payload_inesperado_vira_cotacao_indisponivel(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"outra_coisa": {}})

        with pytest.raises(CotacaoIndisponivelError):
            obter_cotacao(
                "USD-BRL", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=0
            )

    def test_par_invalido_nem_chega_a_consultar(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise AssertionError("não deveria consultar a fonte")

        with pytest.raises(EntradaInvalidaError):
            obter_cotacao(
                "dólar", client=_client(handler), base_url=BASE_URL, timeout_s=1.0, max_retries=0
            )


class TestConversao:
    def test_converte_da_origem_para_o_destino(self, cotacao: Cotacao) -> None:
        assert converter(100.0, cotacao) == 500.0

    def test_converte_do_destino_para_a_origem(self, cotacao: Cotacao) -> None:
        assert converter_inverso(520.0, cotacao) == 100.0

    def test_arredonda_para_duas_casas(self, cotacao: Cotacao) -> None:
        assert converter(33.333, cotacao) == 166.67
