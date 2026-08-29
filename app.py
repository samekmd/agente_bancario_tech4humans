"""Entrypoint Streamlit do atendimento do Banco Ágil.

Execute com `make run`.
"""

import streamlit as st

from ui.chat import renderizar

st.set_page_config(page_title="Banco Ágil — Atendimento", page_icon="💬")

renderizar()
