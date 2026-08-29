"""Configuração da aplicação: segredos, modelos, parâmetros de negócio e paths.

Único ponto do sistema que lê variáveis de ambiente. Nenhum `os.getenv` fora daqui.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Configuração carregada de variáveis de ambiente e do arquivo `.env`."""

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Provedor de LLM
    groq_api_key: SecretStr
    modelo_dialogo: str = "openai/gpt-oss-120b"
    modelo_extracao: str = "openai/gpt-oss-120b"
    temperatura_dialogo: float = 0.3
    temperatura_extracao: float = 0.0

    # Parâmetros de negócio
    max_tentativas_auth: int = 3
    max_entrevistas_por_sessao: int = 1
    recursion_limit: int = 25

    # Câmbio
    cotacao_base_url: str = "https://economia.awesomeapi.com.br/json/last"
    cotacao_timeout_s: float = 5.0
    cotacao_max_retries: int = 2
    cambio_fallback_web: bool = False

    # Observabilidade
    log_level: str = "INFO"

    # Dados. Campo, e não property, para que testes e outros ambientes possam apontar as
    # bases para outro diretório sem tocar em código.
    data_dir: Path = BASE_DIR / "data"

    @property
    def base_dir(self) -> Path:
        """Raiz do repositório."""
        return BASE_DIR

    @property
    def seed_dir(self) -> Path:
        """Diretório da cópia pristina das bases, restaurada por `make reset-data`."""
        return BASE_DIR / "data" / "seed"

    @property
    def logs_dir(self) -> Path:
        """Diretório de logs da aplicação."""
        return BASE_DIR / "logs"

    @property
    def prompts_dir(self) -> Path:
        """Diretório dos prompts versionados em Markdown."""
        return Path(__file__).resolve().parent / "prompts"

    @property
    def clientes_csv(self) -> Path:
        """Base de clientes (leitura e escrita)."""
        return self.data_dir / "clientes.csv"

    @property
    def score_limite_csv(self) -> Path:
        """Faixas de score e limite máximo (somente leitura)."""
        return self.data_dir / "score_limite.csv"

    @property
    def solicitacoes_csv(self) -> Path:
        """Solicitações de aumento de limite (gerado em runtime)."""
        return self.data_dir / "solicitacoes_aumento_limite.csv"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retorna a configuração da aplicação, carregada uma única vez por processo."""
    return Settings()
