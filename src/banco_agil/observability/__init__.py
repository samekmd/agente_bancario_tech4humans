"""Observabilidade: tracing do atendimento com MLflow.

Camada transversal, como `utils/`: pode ser importada de qualquer camada e não importa
nenhuma. Observar nunca altera o comportamento do atendimento — se o MLflow estiver
desligado ou fora do ar, tudo aqui vira no-op silencioso.
"""
