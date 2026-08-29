# Arquitetura

Documento de arquitetura do atendimento do Banco Ágil.

> Esqueleto. O conteúdo é escrito conforme as camadas forem implementadas.

## Camadas

`ui → graph → agents → tools → services → repositories → CSV`

Fluxo em sentido único: nenhuma camada importa de uma camada acima, `services` não
conhece LangChain e `repositories` é o único ponto que toca disco.

## Grafo

Diagrama em `docs/grafo.png` (gerado a partir de `build_graph()` quando o grafo existir).
