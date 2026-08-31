# CLAUDE.md

Contexto operacional do projeto. Leia antes de qualquer tarefa.

## Projeto

Sistema de atendimento bancário conversacional do **Banco Ágil** (banco digital fictício),
construído como multiagente com LangGraph. Um único assistente do ponto de vista do
cliente, com quatro especializações internas: Triagem, Crédito, Entrevista de Crédito e
Câmbio. É a entrega de um desafio técnico — o README e a clareza arquitetural valem
tanto quanto o código funcionando.

## Stack

- Python 3.11+
- LangGraph (orquestração) + LangChain (tools, mensagens)
- Groq como provedor de LLM (`langchain-groq`)
- Streamlit (UI de teste)
- Pydantic v2 + pydantic-settings (modelos e config)
- pytest, ruff

## Regras arquiteturais invioláveis

Estas regras existem porque o projeto é avaliado por arquitetura. Se uma tarefa parecer
exigir violar alguma delas, pare e sinalize em vez de contornar.

1. **Camadas em sentido único.**
   `ui → graph → agents → tools → services → repositories → CSV`
   Nenhuma camada importa de uma camada acima. `services` não conhece LangChain.
   `repositories` é o único lugar que toca disco.

2. **Regra de negócio nunca fica com o LLM.** Cálculo de score, comparação com faixas de
   limite, validação de CPF, decisão de aprovar/rejeitar e contagem de tentativas são
   funções Python puras em `services/` ou `utils/`. O LLM apenas orquestra, extrai
   entidades da fala e verbaliza resultados.

3. **Roteamento é determinístico.** As arestas condicionais leem campos do `State` em
   Python. O LLM nunca decide para qual nó ir por texto livre — ele só chama uma handoff
   tool, que escreve `agente_atual` no estado.

4. **Escopo de agente se garante por binding de ferramenta.** Cada agente recebe apenas
   as tools do seu domínio. Câmbio não tem acesso a `consultar_limite`. Prompt é reforço,
   nunca a garantia.

5. **Tools são adaptadores finos.** Uma tool valida entrada, chama um service, e retorna
   um payload estruturado (sucesso ou erro tratado). Sem lógica de negócio, sem I/O direto.

6. **Nenhuma tool levanta exceção para o grafo.** Erros esperados (CSV ausente, API fora,
   entrada inválida) viram retorno estruturado com `ok: False` e uma mensagem que o
   agente possa verbalizar. Exceções de domínio ficam em `utils/exceptions.py`.

7. **Handoff não encerra o turno.** A handoff tool escreve `agente_atual` e encerra o
   subgrafo do agente de origem (`return_direct=True`, para ele não voltar ao LLM e
   anunciar a saída); a aresta condicional do grafo pai lê o campo e entrega o controle ao
   destino, que responde na mesma invocação. O agente que recebe o controle responde na
   mesma mensagem, sem se reapresentar e sem anunciar a transição. Do ponto de vista do
   cliente existe um único atendente.

   Não usar `Command(goto=..., graph=Command.PARENT)`: saindo de um subgrafo, a
   `AIMessage` que fez o tool call não chega ao grafo pai, o histórico persistido fica com
   uma `ToolMessage` órfã e o provedor de LLM rejeita a próxima mensagem.

8. **Escrita em CSV é atômica.** Sempre via `repositories/base.py`: escreve em arquivo
   temporário e faz `os.replace`, sob `filelock`. Nunca abrir CSV com `open(..., "w")`
   direto fora dos repositories.

9. **Nenhum dado de outros clientes entra no contexto do LLM.** Tools de autenticação e
   consulta retornam apenas o registro do CPF autenticado.

## Estrutura de pastas

```
app.py                          entrypoint Streamlit
data/                           clientes.csv, score_limite.csv, solicitacoes_aumento_limite.csv
docs/                           arquitetura.md, grafo.png
src/banco_agil/
  config.py                     pydantic-settings (chaves, modelos, paths)
  llm.py                        factory ChatGroq
  state.py                      AtendimentoState
  graph.py                      build_graph()
  routing.py                    arestas condicionais determinísticas
  agents/                       base.py + triagem, credito, entrevista, cambio
  prompts/                      .md versionados (persona_base + um por agente)
  tools/                        autenticacao, credito, entrevista, cambio, handoff, sistema
  services/                     autenticacao, score, limite, cotacao  (puro, sem I/O)
  repositories/                 base, clientes, score_limite, solicitacoes
  domain/                       models.py, enums.py
  utils/                        validators, logging, exceptions
ui/                             chat.py, session.py
tests/                          unit/, integration/, fixtures/
```

Ao criar um arquivo novo, ele precisa caber em uma dessas pastas. Se não couber, a
modelagem provavelmente está errada.

## Estado do grafo

`AtendimentoState` é o contrato central. Campos:

| Campo | Tipo | Escrito por |
|---|---|---|
| `messages` | `Annotated[list, add_messages]` | todos |
| `agente_atual` | `Agente` (enum) | handoff tools |
| `autenticado` | `bool` | tool de autenticação |
| `tentativas_auth` | `int` | tool de autenticação |
| `cpf` | `str \| None` | tool de autenticação |
| `cliente` | `Cliente \| None` | tool de autenticação |
| `solicitacao_atual` | `SolicitacaoAumento \| None` | tools de crédito |
| `limite_pendente_reavaliacao` | `float \| None` | tools de crédito e entrevista |
| `entrevista_slots` | `dict[str, Any]` | tools de entrevista |
| `entrevistas_realizadas` | `int` | nó de entrevista |
| `entrevista_campo_perguntado` | `str \| None` | nó de entrevista |
| `encerrado` | `bool` | `encerrar_atendimento` |
| `ultimo_erro` | `str \| None` | qualquer tool |

`messages` é a única chave do estado em inglês: é o default dos prebuilts do LangGraph
(`ToolNode`, `create_react_agent`, `MessagesState`) e renomeá-la custaria `messages_key`
em cada ponto de uso. Todo o resto do estado segue o domínio em português.

O grafo roda **uma invocação por mensagem do usuário**, com checkpointer e `thread_id`
vindo de `st.session_state`. Não usar `interrupt()` para coletar input.
`estado_inicial()` em `state.py` é a única fonte dos valores de partida.

## Regras de negócio críticas

- **Autenticação**: CPF + data de nascimento contra `clientes.csv`. Até 3 tentativas
  totais. Na terceira falha, mensagem cordial e encerramento. O contador vive no estado,
  não na contagem de mensagens.
- **Nenhum agente além da Triagem atua sem `autenticado is True`.** Verificado na aresta,
  não no prompt.
- **Aumento de limite**: registrar o pedido em `solicitacoes_aumento_limite.csv` com
  status `pendente`, depois avaliar contra `score_limite.csv` e atualizar a linha para
  `aprovado` ou `rejeitado`. O registro do pedido acontece antes da decisão.
- **Rejeitado** → oferecer a entrevista. Se o cliente recusar, encerrar ou redirecionar.
- **Ciclo crédito ⇄ entrevista** tem teto: `entrevistas_realizadas` máximo 1 por sessão.
  `recursion_limit` do grafo configurado explicitamente.
- **Entrevista** é slot filling determinístico: o Python decide qual dos cinco campos
  falta e injeta no prompt; o LLM só extrai o valor. Nunca pular perguntas — garantido
  por `entrevista_campo_perguntado`: um middleware `after_model` marca o campo quando o
  agente responde texto ao cliente, e a tool recusa registrar qualquer outro. Sem isso o
  LLM preenche slots com valores tirados do histórico da conversa.
- **Encerramento** por pedido do cliente é sempre possível, em qualquer agente, via
  `encerrar_atendimento`.

## Fórmula de score

```
score = (renda_mensal / (despesas + 1)) * 30
      + peso_emprego[tipo_emprego]
      + peso_dependentes[num_dependentes]
      + peso_dividas[tem_dividas]
```

`peso_emprego`: formal 300, autônomo 200, desempregado 0
`peso_dependentes`: 0 → 100, 1 → 80, 2 → 60, 3 ou mais → 30
`peso_dividas`: sim → -100, não → 100

Resultado sempre truncado ao intervalo **0–1000** e arredondado para inteiro. A fórmula
mora só em `services/score.py` e tem testes de fronteira.

## Contratos de dados

As bases são fictícias e definidas por este projeto. Os schemas abaixo são
normativos — não inferir, não renomear coluna.

`data/clientes.csv` — leitura e escrita (o score é atualizado pela entrevista).
| coluna | tipo | formato |
|---|---|---|
| `cpf` | string | 11 dígitos, sem pontuação |
| `nome` | string | |
| `data_nascimento` | string | `YYYY-MM-DD` |
| `limite_atual` | float | |
| `score_atual` | int | 0–1000 |

`data/score_limite.csv` — somente leitura. Faixas contíguas, sem sobreposição,
cobrindo 0–1000. Colunas: `score_min` (int), `score_max` (int, inclusivo),
`limite_maximo` (float).

`data/solicitacoes_aumento_limite.csv` — gerado em runtime. Colunas nesta ordem:
`cpf_cliente` (string), `data_hora_solicitacao` (ISO 8601), `limite_atual` (float),
`novo_limite_solicitado` (float), `status_pedido` (string).

`data/seed/` guarda a cópia pristina das duas primeiras bases e é versionada.
`data/clientes.csv` é mutável em runtime e restaurado por `make reset-data`.

## Câmbio

Fonte primária: AwesomeAPI (`https://economia.awesomeapi.com.br/json/last/USD-BRL`),
gratuita e sem chave. Retorno JSON estruturado. Timeout curto, retry com backoff, e
fallback para busca web se configurado. Se a cotação não puder ser obtida, informar o
cliente com clareza e registrar o erro — nunca inventar valor.

## Convenções de código

- Domínio em português (`Cliente`, `consultar_limite`, `score_atual`); termos de
  infraestrutura em inglês quando for o idioma da biblioteca.
- Type hints obrigatórios em funções públicas. Pydantic para qualquer dado estruturado
  que cruze camadas.
- Docstrings de tool são prompt: descrevem quando usar e o que retornam, em português,
  de forma objetiva. São lidas pelo LLM.
- Prompts ficam em `src/banco_agil/prompts/*.md`, nunca inline no Python.
- Config e segredos só via `config.py`. Nenhuma chave hardcoded, nenhum `os.getenv`
  espalhado.
- Logging estruturado via `utils/logging.py`. Sem `print`.
- Temperatura 0 para extração e classificação; baixa (0.3) para diálogo.

## Testes

- `tests/unit/` cobre `services/`, `repositories/` e `utils/` sem nenhuma chamada de LLM
  ou de rede. Essa camada deve ser testável integralmente offline.
- `tests/integration/` testa o grafo com `FakeListChatModel` para validar roteamento,
  contagem de tentativas e o ciclo crédito/entrevista.
- Fixtures de CSV em `tests/fixtures/`, nunca apontando para `data/`.
- Toda regra de negócio nova entra com teste na mesma tarefa.

## Comandos

```bash
make install      # dependências
make run          # streamlit run app.py
make test         # pytest
make lint         # ruff check + ruff format
```

Se o Makefile ainda não existir, crie-o ao adicionar o primeiro comando.

## Definition of done

Uma tarefa está pronta quando: respeita as camadas, tem type hints, tem teste unitário se
tocou regra de negócio, passa no ruff, e não introduziu chave, caminho absoluto ou schema
de CSV assumido sem verificação.

## O que não fazer

- Não colocar lógica de negócio em tool, prompt ou nó do grafo.
- Não deixar o LLM decidir roteamento, contar tentativas ou calcular score.
- Não terminar o turno em um handoff.
- Não abrir CSV fora dos repositories.
- Não criar abstração para um único caso de uso.
- Não instalar framework de agente adicional (CrewAI, AutoGen). A stack está fechada.
- Não commitar `.env`, `data/solicitacoes_aumento_limite.csv` ou `logs/`.