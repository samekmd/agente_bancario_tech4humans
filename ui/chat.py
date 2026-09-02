"""Renderização do chat e do histórico de mensagens."""

import streamlit as st
from pydantic import ValidationError

from ui.session import (
    bloqueado_por_autenticacao,
    enviar_mensagem,
    iniciar_sessao,
    observabilidade_ativa,
    obter_grafo,
    reiniciar_sessao,
)

TITULO = "Banco Ágil"
SUBTITULO = "Atendimento virtual"
SAUDACAO = "Olá! Sou o assistente do Banco Ágil. Como posso ajudar você hoje?"
PLACEHOLDER = "Digite sua mensagem..."
AVISO_ENCERRADO = "Este atendimento foi encerrado."
AVISO_BLOQUEADO = (
    "Não foi possível confirmar a identidade do cliente após as tentativas permitidas. "
    "Por segurança, este atendimento está encerrado. Procure uma agência ou a central "
    "telefônica para seguir."
)
TRACING_ATIVO = "Observabilidade: gravando no MLflow."
TRACING_DESLIGADO = "Observabilidade: desligada. Rode `make mlflow` para gravar os traces."

AJUDA_CONFIG = """
**Configuração incompleta.**

Crie um arquivo `.env` na raiz do projeto a partir do `.env.example` e preencha a chave
do Groq:

```
GROQ_API_KEY=sua-chave-aqui
```
"""


def texto_seguro(texto: str) -> str:
    """Escapa `$` para o Streamlit não ler o par de cifrões como fórmula LaTeX.

    `st.markdown` trata `$...$` como matemática: uma mensagem com dois valores em reais
    perde os dois cifrões e italiza o miolo. Foi assim que "R$ 5.000,00 ... R$ 1.000,00"
    chegou ao cliente como "R 5.000,00 ... R 1.000,00".
    """
    return texto.replace("$", r"\$")


def _barra_lateral() -> None:
    with st.sidebar:
        st.subheader(TITULO)
        st.caption(SUBTITULO)
        # Bloqueado por autenticação, reiniciar é justamente o que não pode ser oferecido:
        # thread nova devolveria as três tentativas.
        if not bloqueado_por_autenticacao() and st.button(
            "Novo atendimento", use_container_width=True
        ):
            reiniciar_sessao()
            st.rerun()
        st.divider()
        st.caption(TRACING_ATIVO if observabilidade_ativa() else TRACING_DESLIGADO)


def _historico() -> None:
    with st.chat_message("assistant"):
        st.markdown(SAUDACAO)
    for papel, texto in st.session_state.historico:
        with st.chat_message(papel):
            st.markdown(texto_seguro(texto))


def renderizar() -> None:
    """Desenha a página inteira do chat."""
    iniciar_sessao()

    try:
        obter_grafo()
    except ValidationError:
        st.error(AJUDA_CONFIG)
        st.stop()

    st.title(TITULO)
    st.caption(SUBTITULO)
    _barra_lateral()
    _historico()

    if bloqueado_por_autenticacao():
        st.error(AVISO_BLOQUEADO)
        return

    if st.session_state.encerrado:
        st.info(AVISO_ENCERRADO)
        if st.button("Iniciar novo atendimento"):
            reiniciar_sessao()
            st.rerun()
        return

    pergunta = st.chat_input(PLACEHOLDER)
    if not pergunta:
        return

    st.session_state.historico.append(("user", pergunta))
    with st.chat_message("user"):
        st.markdown(texto_seguro(pergunta))

    with st.chat_message("assistant"), st.spinner("Consultando..."):
        resposta = enviar_mensagem(pergunta)
        st.markdown(texto_seguro(resposta))
    st.session_state.historico.append(("assistant", resposta))

    if st.session_state.encerrado:
        st.rerun()
