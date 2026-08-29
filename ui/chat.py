"""Renderização do chat e do histórico de mensagens."""

import streamlit as st
from pydantic import ValidationError

from ui.session import enviar_mensagem, iniciar_sessao, obter_grafo, reiniciar_sessao

TITULO = "Banco Ágil"
SUBTITULO = "Atendimento virtual"
SAUDACAO = "Olá! Sou o assistente do Banco Ágil. Como posso ajudar você hoje?"
PLACEHOLDER = "Digite sua mensagem..."
AVISO_ENCERRADO = "Este atendimento foi encerrado."

AJUDA_CONFIG = """
**Configuração incompleta.**

Crie um arquivo `.env` na raiz do projeto a partir do `.env.example` e preencha a chave
do Groq:

```
GROQ_API_KEY=sua-chave-aqui
```
"""


def _barra_lateral() -> None:
    with st.sidebar:
        st.subheader(TITULO)
        st.caption(SUBTITULO)
        if st.button("Novo atendimento", use_container_width=True):
            reiniciar_sessao()
            st.rerun()


def _historico() -> None:
    with st.chat_message("assistant"):
        st.markdown(SAUDACAO)
    for papel, texto in st.session_state.historico:
        with st.chat_message(papel):
            st.markdown(texto)


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
        st.markdown(pergunta)

    with st.chat_message("assistant"), st.spinner("Consultando..."):
        resposta = enviar_mensagem(pergunta)
        st.markdown(resposta)
    st.session_state.historico.append(("assistant", resposta))

    if st.session_state.encerrado:
        st.rerun()
