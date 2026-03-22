# Architecture Brief 

## 1. Identificação da Demanda
- **Título:** Equalizador ProMax
- **Projeto:** Equalizador ProMax
- **Issue:** Não informada
- **Responsável pela etapa:** BotArq

## 2. Resumo Técnico
O Equalizador ProMax deve ser implementado como uma ferramenta **local para Windows**, sem interface web e sem login no MVP, focada em automatizar a equalização assistida de um único repositório por execução. A solução proposta é uma **CLI empacotada para Windows** que orquestra consulta ao Jira, descoberta de commits já integrados em `develop`, deduplicação por hash, ordenação cronológica, criação de branch baseada em `origin/quality`, execução sequencial de `cherry-pick` e pausa segura em conflitos com retomada posterior.

A arquitetura prioriza previsibilidade operacional, rastreabilidade local, segurança de credenciais do Jira e isolamento claro entre regras de negócio, integração com Jira, automação Git e persistência do estado de execução.

## 3. Objetivo Técnico da Entrega
A arquitetura precisa viabilizar, com baixo risco operacional:
- entrada simples de diretório do repositório e lista de estórias;
- consulta ao Jira para obtenção de subtasks;
- correlação rastreável entre itens Jira e commits já presentes em `develop`;
- criação e uso seguro de branch local de equalização;
- execução assistida de `cherry-pick` com pausa e retomada;
- persistência de logs e estado da execução para auditoria e recuperação;
- evolução futura para outros modos de operação sem reescrever o núcleo da ferramenta.

## 4. Contexto Considerado
Insumos considerados nesta análise:
- Product Brief aprovado do Equalizador ProMax.
- Template oficial `architecture-brief.md`.
- Guia do SSO da fábrica consultado antes da definição da solução.
- Restrição adicional informada pelo Maestro no contexto desta conversa:
  - não será web;
  - não exigirá login;
  - deve rodar em Windows com acesso a diretório local e criação/edição de arquivos.
- Scripts de referência anexados:
  - `script_jira.txt` para consulta simples ao Jira;
  - `script.py` para descoberta de merges/commits em `develop`.

## 5. Proposta de Solução
A solução deve ser organizada como uma aplicação CLI local com núcleo de execução desacoplado dos adaptadores externos.

### 5.1 Visão Geral
**Decisão tomada — AB-DEC-01:** implementar o MVP como **aplicação CLI local para Windows em Python 3.12**, distribuída como executável único via empacotamento, reutilizando a viabilidade já demonstrada pelos scripts atuais e evitando complexidade desnecessária de frontend web.

**Decisão tomada — AB-DEC-02:** separar a solução em camadas:
1. **CLI Adapter** para entrada de comandos;
2. **Execution Orchestrator** para o fluxo ponta a ponta;
3. **Jira Client** para obtenção de estórias/subtasks;
4. **Git Adapter** para leitura do histórico, criação de branch e `cherry-pick`;
5. **Correlation Engine** para associar itens Jira a commits de forma inequívoca;
6. **Run State Store** para persistir estado, retomada e auditoria.

**Decisão tomada — AB-DEC-03:** operar com um comando principal `run` e comandos auxiliares `resume`, `status` e `doctor`.

**Recomendação — AB-DEC-04:** usar `Typer` ou `argparse` para CLI, biblioteca `jira` (Jira Client) para integração com Jira, `subprocess` para Git e `keyring`/Windows Credential Manager para segredos. Essa escolha mantém o MVP simples, testável e alinhado ao ambiente Windows.

### 5.2 Componentes Envolvidos
- [x] Backend
- [ ] Frontend
- [ ] Banco de dados
- [x] Infraestrutura
- [ ] Autenticação
- [ ] Autorização
- [x] Observabilidade
- [x] Integrações externas

**AB-COMP-01 — CLI Adapter**
- Responsável por parsing de parâmetros, mensagens ao usuário e códigos de saída.
- Comandos previstos: `run`, `resume`, `status`, `doctor`.

**AB-COMP-02 — Execution Orchestrator**
- Coordena o fluxo completo da equalização.
- Garante ordem das etapas, persistência de checkpoints e encerramento consistente.

**AB-COMP-03 — Jira Client**
- Implementado sobre a biblioteca `jira` (Python Jira Client) como adaptador oficial do MVP.
- Consulta a API do Jira para obter estória e subtasks.
- Expõe contrato interno estável para o núcleo e isola detalhes de credencial/configuração.

**AB-COMP-04 — Git Adapter**
- Executa operações locais via Git CLI.
- Responsável por preflight do repositório, leitura de merges, descoberta de commits, criação de branch e `cherry-pick`.

**AB-COMP-05 — Correlation Engine**
- Constrói o conjunto elegível de chaves Jira.
- Localiza somente correspondências inequívocas entre item Jira e evidências no Git.
- Deduplica por hash e ordena cronologicamente.

**AB-COMP-06 — Run State Store**
- Persiste manifesto da execução, checkpoints, logs estruturados e resumo final.
- Permite pausa/retomada sem perder rastreabilidade.

**AB-COMP-07 — Report Generator**
- Produz resumo final legível pelo TechLead.
- Gera também artefatos estruturados para auditoria posterior.

### 5.3 Fluxo Principal
1. O usuário executa `equalizador-promax run --repo <caminho> --stories <lista>`.
2. O CLI valida parâmetros, permissões locais, existência do repositório, presença do Git e diretório limpo.
3. O `Jira Client` consulta cada estória e obtém as subtasks associadas.
4. O `Correlation Engine` consolida uma lista única de itens elegíveis.
5. O `Git Adapter` lê merges já integrados em `develop` usando `--merges` e `--first-parent`.
6. O `Correlation Engine` localiza apenas commits com correspondência inequívoca com os itens elegíveis.
7. A lista de commits é deduplicada por hash e ordenada do mais antigo para o mais novo.
8. O `Git Adapter` cria a branch de equalização a partir de `origin/quality`.
9. O `Execution Orchestrator` executa os `cherry-picks` um a um.
10. Em conflito, o estado é salvo como pausado e a execução é interrompida com instruções claras.
11. Após intervenção manual, o usuário executa `resume`.
12. Ao final, o sistema gera log em tela, log em arquivo e resumo consolidado.

## 6. Contratos e Integrações
**Integração/Contrato 1 — Jira via biblioteca `jira`**
- Adaptador oficial do MVP: biblioteca `jira` (Python Jira Client).
- Operação mínima necessária observada nos insumos: leitura de issue por chave para obter estória e subtasks.
- Referência de endpoint subjacente já evidenciada no contexto atual: `GET /rest/api/2/issue/{issueKey}`.
- Saídas mínimas consumidas: chave da issue, subtasks, status de acesso e metadados básicos para log.

**Integração/Contrato 2 — Configuração de acesso ao Jira**
A implementação deve aceitar configuração externa e segura para acesso ao Jira. Para o acesso funcionar com sucesso, o Maestro/ambiente precisa fornecer:
- `jira.base_url`: URL base do Jira acessível pela máquina Windows do operador. Pelo script de referência, o ambiente atual aponta para `https://agile.corp.edp.pt`.
- `jira.auth_mode`: modo de autenticação realmente aceito pelo ambiente alvo para uso do Jira Client local. Exemplos compatíveis com a arquitetura: token pessoal/técnico, usuário+token ou outro método suportado pela biblioteca `jira` e pelo Jira da empresa.
- `jira.username` ou identificador equivalente da conta técnica/pessoal quando o modo escolhido exigir esse campo.
- `jira.secret`: segredo correspondente ao modo escolhido, armazenado no Windows Credential Manager e nunca em arquivo do projeto.
- permissão de leitura nas estórias e subtasks informadas.
- conectividade de rede necessária na estação do operador, incluindo VPN/proxy/certificados corporativos quando aplicável.
- observação arquitetural: o segredo não entra por argumento de linha de comando; a CLI deve buscá-lo no storage seguro local.

**Integração/Contrato 3 — Git CLI local**
- Comandos previstos:
  - `git rev-parse --show-toplevel`
  - `git fetch origin`
  - `git log develop --merges --first-parent --pretty=%H;%s`
  - `git show --pretty=%P -s <merge>`
  - `git log <base>..<branch-parent> --no-merges --pretty=%H;%ct;%an;%s`
  - `git switch -c <branch> origin/quality`
  - `git cherry-pick <hash>`
  - `git status --porcelain`
- O Git CLI é a interface oficial de execução sobre o repositório local no MVP.

**Integração/Contrato 4 — Filesystem local**
- Persistência de estado e logs em diretório interno da execução.
- Recomendação: armazenar em `.git/equalizador-promax/runs/<run-id>/` para não poluir o working tree.

**Integração/Contrato 5 — Provedor local de segredos**
- Recomendação: Windows Credential Manager como armazenamento preferencial de credenciais do Jira.
- Fallback de desenvolvimento: variável de ambiente, nunca arquivo versionado.

## 7. Dados e Persistência
**Decisão tomada — AB-DEC-05:** não haverá banco de dados no MVP. Toda a persistência será local e por execução.

**Decisão tomada — AB-DEC-06:** a execução persistirá os seguintes arquivos em `.git/equalizador-promax/runs/<run-id>/`:
- `manifest.json` — identidade da execução, branch alvo, repositório, parâmetros de entrada, status atual, índice corrente e checkpoints.
- `items.json` — estórias/subtasks consolidadas e resultado da correlação.
- `events.jsonl` — log estruturado de eventos da execução.
- `execution.log` — log textual contínuo espelhando em arquivo o que é exibido em tela.
- `summary.md` — resumo final legível.
- `resume-hints.txt` — instruções rápidas de retomada quando houver pausa.

**Decisão tomada — AB-DEC-07:** o `run-id` deve ser único e determinístico o suficiente para auditoria humana, no formato `YYYYMMDD-HHMMSS-<repo-slug>`.

**Decisão tomada — AB-DEC-08:** a branch de equalização deve seguir padrão `equalizacao/<run-id>`.

**Decisão tomada — AB-DEC-09:** a ferramenta deve bloquear reexecução ambígua quando detectar execução anterior não encerrada para o mesmo repositório e mesma lista de estórias, exigindo escolha explícita entre `resume` ou nova execução forçada.

## 8. Segurança
Este projeto **não exige autenticação do usuário final no MVP**. O guia da fábrica determina uso obrigatório da `sso-platform` somente quando o projeto exigir autenticação; como este MVP é local, sem web e sem login, a integração com SSO **não se aplica nesta fase**.

**Decisão tomada — AB-DEC-10:** não implementar qualquer fluxo de login local, sessão de usuário ou controle de identidade no MVP.

**Decisão tomada — AB-DEC-11:** as credenciais para acesso ao Jira devem ser tratadas como segredo operacional local e nunca persistidas em arquivos da execução, em código-fonte, em argumentos de linha de comando visíveis no histórico do shell ou em logs.

**Decisão tomada — AB-DEC-12:** usar Windows Credential Manager como storage principal de segredo; apenas em ambiente de desenvolvimento controlado admitir variável de ambiente como fallback explícito.

**Decisão tomada — AB-DEC-13:** sanitizar logs para evitar exposição de token, cabeçalhos HTTP, paths sensíveis desnecessários ou conteúdo bruto de erro do Jira que revele segredo.

**Recomendação — AB-DEC-14:** exigir `working tree` limpo antes da criação da branch e antes de iniciar um `resume`, para reduzir risco de cherry-pick sobre estado contaminado.

## 9. Observabilidade e Operação
**Decisão tomada — AB-DEC-15:** a observabilidade mínima do MVP será local, composta por saída de console, `execution.log` textual em arquivo, `events.jsonl` estruturado e `summary.md` final.

**Decisão tomada — AB-DEC-16:** cada evento relevante deve registrar timestamp, fase, item Jira, hash do commit quando aplicável, ação, resultado e mensagem curta; os principais marcos devem ser espelhados tanto em tela quanto em arquivo.

**Decisão tomada — AB-DEC-17:** o comando `doctor` deve validar, antes de uma execução real:
- Git instalado e acessível;
- diretório informado é repositório Git válido;
- `origin/quality` acessível;
- `develop` acessível;
- working tree limpo;
- permissão de escrita no diretório de estado;
- perfil/configuração do Jira disponível;
- credencial do Jira disponível no storage seguro local;
- conectividade básica com a API do Jira.

**Recomendação — AB-DEC-18:** códigos de saída padronizados:
- `0` sucesso;
- `1` erro de validação local;
- `2` erro de integração Jira;
- `3` pausa por conflito;
- `4` estado inconsistente detectado.

## 10. Riscos Técnicos
**AB-RISK-01 — Correlação imperfeita entre item Jira e commit**
- Impacto: inclusão indevida ou omissão de commit elegível.
- Mitigação sugerida: correlação apenas por evidência inequívoca, com regex por chave Jira, múltiplas fontes de evidência controladas e log explícito de ausência de correspondência.

**AB-RISK-02 — Credencial/configuração Jira ausente ou incompatível na máquina do operador**
- Impacto: a ferramenta inicia, mas não consegue obter estórias/subtasks no ambiente real.
- Mitigação sugerida: usar Jira Client com configuração externa validada pelo `doctor`, ler segredo apenas do storage seguro local e falhar cedo com mensagem objetiva sobre o parâmetro ausente.

**AB-RISK-03 — Pausa e retomada em estado Git inconsistente**
- Impacto: corrupção da branch local ou retomada do ponto errado.
- Mitigação sugerida: manifesto com checkpoint obrigatório, validação de estado Git no `resume`, recusa em prosseguir quando houver divergência não resolvida.

**AB-RISK-04 — Reexecução acidental da mesma equalização**
- Impacto: branch duplicada, commits reaplicados ou auditoria confusa.
- Mitigação sugerida: fingerprint da execução, detecção de execução aberta e exigência de ação explícita do usuário.

**AB-RISK-05 — Dependência de convenções fracas do histórico Git**
- Impacto: baixa cobertura automática da descoberta.
- Mitigação sugerida: assumir desde já que o MVP pode produzir itens “sem correspondência” e tratar isso como saída válida, não como falha escondida.

**AB-RISK-06 — Empacotamento Python no Windows com dependência de Git externo**
- Impacto: falhas de execução em estações com PATH inconsistente.
- Mitigação sugerida: `doctor` obrigatório, documentação curta de pré-requisitos e empacotamento com validação de ambiente no bootstrap.

## 11. Trade-offs
**AB-TF-01 — Python CLI vs aplicação .NET desktop**
- Prós do Python CLI:
  - reaproveita diretamente os scripts já existentes;
  - menor tempo de MVP;
  - boa ergonomia para automação local e empacotamento rápido.
- Contras:
  - distribuição pode exigir mais cuidado com empacotamento;
  - observabilidade e debugging em estações podem depender mais de disciplina do pacote.

**AB-TF-02 — Persistência em `.git/equalizador-promax` vs pasta externa global**
- Prós de `.git/equalizador-promax`:
  - evita poluir o working tree;
  - mantém o estado acoplado ao repositório certo;
  - facilita `resume` e auditoria local.
- Contras:
  - artefatos ficam escondidos e podem ser esquecidos pelo usuário;
  - troca de máquina não leva estado automaticamente.

**AB-TF-03 — Correlação estrita vs heurística agressiva**
- Prós da correlação estrita:
  - reduz falso positivo;
  - respeita o requisito de correspondência inequívoca.
- Contras:
  - pode aumentar volume de itens sem correspondência.

**AB-TF-04 — Pausa assistida vs tentativa de auto-resolução**
- Prós da pausa assistida:
  - aderente ao Product Brief;
  - menor risco de erro silencioso.
- Contras:
  - maior intervenção humana;
  - throughput operacional menor em lotes conflitados.

## 12. Decisões que Dependem do Maestro
No momento, **não há decisão arquitetural crítica remanescente bloqueando o início do desenvolvimento**.

Os pontos abaixo passam a ser tratados como **insumos operacionais de implantação/configuração**, e não mais como pendências de arquitetura:
- disponibilizar a configuração de acesso ao Jira descrita em `Integração/Contrato 2`;
- disponibilizar uma credencial válida no Windows Credential Manager da estação que executará a ferramenta.

## 13. Recomendação do BotArq
Informe a recomendação final:

- [x] Apto para seguir para desenvolvimento
- [ ] Apto para seguir após decisão do Maestro
- [ ] Precisa de revisão de arquitetura

## 14. Observações Finais
- O Product Brief está pronto para arquitetura e a solução proposta mantém o fluxo oficial do MVP.
- O uso do guia de SSO foi considerado e explicitamente marcado como **não aplicável ao MVP**, pois o sistema não será web e não terá login nesta fase.
- O uso da biblioteca `jira` como adaptador oficial e a distribuição como executável único para Windows foram consolidados nesta revisão.
- O único cuidado remanescente não é arquitetural: é prover corretamente a configuração/credencial do Jira no ambiente do operador.

## 15. Integração com o SSO da fábrica
O guia da fábrica foi consultado antes da proposta. Pela regra oficial, a `sso-platform` é obrigatória para projetos que **precisarem de autenticação**. Este projeto, no entanto, foi definido para o MVP como ferramenta local, sem web e sem login.

**Decisão tomada — AB-DEC-19:** registrar formalmente que **não há integração com a `sso-platform` no MVP**.

**Condição de fronteira:** se o Equalizador ProMax evoluir para uso web, multiusuário, execução remota ou qualquer cenário com autenticação de usuário final, a arquitetura deverá ser revisitada e a integração com a `sso-platform` passará a ser obrigatória.

## 16. Requisitos transversais obrigatórios
### Segurança
- Não implementar login local.
- Não persistir credenciais do Jira em arquivo.
- Sanitizar logs.
- Exigir working tree limpo antes de `run` e `resume`.

### Observabilidade
- Console legível para o operador.
- `execution.log` textual espelhando o fluxo operacional completo em arquivo.
- `events.jsonl` para rastreabilidade detalhada.
- `summary.md` para fechamento operacional.

### Operação
- Comandos previstos: `run`, `resume`, `status`, `doctor`.
- Documentar pré-requisitos mínimos: Windows, Git instalado, acesso ao repositório, acesso ao Jira.

### Health checks
- Implementar `doctor` com validações locais e externas antes da execução real.
- Validar também estado de cherry-pick em aberto antes de um `resume`.

### Secrets
- Windows Credential Manager como storage principal das credenciais do Jira.
- Fallback controlado por variável de ambiente apenas para desenvolvimento.
- Nunca logar token/segredo.

### Deploy
- Distribuição definida como executável único versionado para Windows.
- Incluir versão da ferramenta no cabeçalho do `summary.md` e do `manifest.json`.

### Integração futura
- Preservar núcleo desacoplado da CLI para permitir, no futuro, integração com interface gráfica, scheduler, modo remoto ou múltiplos repositórios.

## 17. Cobertura do Product Brief
| Product Brief | Cobertura arquitetural |
|---|---|
| **PB-REQ-01** | `AB-COMP-01` define entrada via CLI; `AB-DEC-03` define `run`; contrato local de parâmetros `--repo` e `--stories`. |
| **PB-REQ-02** | `AB-COMP-03` usa a biblioteca `jira` para consultar a issue e suas subtasks; configuração operacional descrita em `Integração/Contrato 2`. |
| **PB-REQ-03** | `AB-COMP-05` consolida estórias e subtasks com deduplicação de chaves Jira. |
| **PB-REQ-04** | `AB-COMP-04` lê apenas histórico já integrado em `develop`; `AB-TF-03` privilegia correlação estrita. |
| **PB-REQ-05** | `AB-COMP-05` deduplica commits por hash antes da execução. |
| **PB-REQ-06** | `AB-COMP-05` ordena por timestamp crescente antes do primeiro `cherry-pick`. |
| **PB-REQ-07** | `AB-DEC-08` define branch `equalizacao/<run-id>` criada a partir de `origin/quality`; `AB-COMP-04` executa o comando Git. |
| **PB-REQ-08** | `AB-COMP-02` orquestra `cherry-pick` sequencial; `AB-COMP-04` executa no Git local. |
| **PB-REQ-09** | `AB-COMP-06` persiste checkpoint; `AB-DEC-17` e `AB-RISK-03` cobrem validação para retomada segura. |
| **PB-REQ-10** | `AB-TF-03` define correlação inequívoca; `AB-COMP-07` registra ausência sem abortar fluxo. |
| **PB-REQ-11** | `AB-DEC-15` e `AB-DEC-16` definem logs estruturados e rastreabilidade por evento/item. |
| **PB-REQ-12** | `AB-COMP-07` gera `summary.md` com totais e fechamento operacional. |
| **PB-REQ-13** | `AB-DEC-01` e `AB-DEC-05` mantêm MVP local, monorrepositório e sem infraestrutura compartilhada. |
| **PB-DEP-01** | Resolvido por `AB-COMP-03`, `Integração/Contrato 2`, `AB-DEC-12` e `AB-RISK-02`: Jira Client com configuração externa e segredo em storage seguro local. |
| **PB-DEP-02** | Resolvido por `AB-DEC-03`: entrada via CLI. |
| **PB-DEP-03** | Resolvido por `AB-COMP-05` + `AB-TF-03`: correlação estrita por evidência inequívoca. |
| **PB-DEP-04** | Resolvido por `AB-DEC-08`: branch `equalizacao/<run-id>` baseada em `origin/quality`. |
| **PB-DEP-05** | Resolvido por `AB-COMP-06`, `AB-DEC-06` e `AB-RISK-03`: manifesto/checkpoint + `resume`. |
| **PB-DEP-06** | Resolvido por `AB-DEC-06`: manifesto, itens, eventos e resumo em diretório da execução. |
| **PB-DEP-07** | Resolvido por `AB-DEC-09`: bloqueio de reexecução ambígua e fingerprint da execução. |

## 18. Checklist para desenvolvimento
- [ ] Implementar `AB-COMP-01` com comandos `run`, `resume`, `status`, `doctor`.
- [ ] Implementar `AB-COMP-03` sobre a biblioteca `jira`, atrás de interface interna que isole configuração e credencial.
- [ ] Implementar `AB-COMP-04` usando Git CLI e tratamento explícito de retorno/erro.
- [ ] Implementar `AB-COMP-05` com regex de chaves Jira e deduplicação por hash.
- [ ] Implementar `AB-COMP-06` com `manifest.json` e checkpoints de execução.
- [ ] Implementar `AB-COMP-07` com `summary.md`, `events.jsonl` e `execution.log`.
- [ ] Implementar validações do `doctor`.
- [ ] Impedir execução com working tree sujo.
- [ ] Sanitizar todos os logs para não expor segredo.
- [ ] Espelhar em tela e em arquivo os marcos do fluxo, desde obtenção das tasks até conflitos encontrados no `cherry-pick`.
- [ ] Empacotar como executável único para Windows e validar execução em máquina limpa.
- [ ] Cobrir testes para: deduplicação, ordenação, ausência de correspondência, pausa em conflito, retomada, reexecução bloqueada.
- [ ] Validar o bootstrap de configuração do Jira (`base_url`, `auth_mode`, identificador de usuário e segredo em storage seguro local).

## 19. Condições para considerar a entrega aderente à arquitetura
A implementação deve ser considerada aderente somente se:
- mantiver o escopo **local, Windows, sem web e sem login** no MVP;
- operar sobre **um único repositório por execução**;
- consultar Jira sem hardcode de segredo e sem persistir credenciais em arquivo;
- considerar apenas commits já integrados em `develop`;
- deduplicar commits por hash antes do `cherry-pick`;
- ordenar commits cronologicamente antes da aplicação;
- criar branch baseada em `origin/quality`;
- pausar em conflito e permitir retomada segura baseada em estado persistido;
- produzir log em tela, `execution.log`, `events.jsonl` e resumo final rastreável;
- bloquear reexecução ambígua da mesma equalização;
- ser distribuída como executável único para Windows;
- não introduzir interface web, banco de dados ou fluxo de autenticação sem revisão arquitetural.

## 20. Classificação explícita das decisões
### Decisão tomada
- `AB-DEC-01` Python CLI local para Windows.
- `AB-DEC-05` Persistência sem banco de dados.
- `AB-DEC-08` Branch `equalizacao/<run-id>`.
- `AB-DEC-10` Sem login no MVP.
- `AB-DEC-12` Windows Credential Manager como storage principal de segredo.
- `AB-DEC-15` Observabilidade local mínima.
- `AB-DEC-19` SSO não aplicável ao MVP atual.
- Uso da biblioteca `jira` como adaptador oficial do Jira.
- Distribuição como executável único para Windows.

### Recomendação
- `AB-DEC-04` Stack de bibliotecas Python para MVP.
- `AB-DEC-18` Padronização de códigos de saída.

### Precisa de decisão do Maestro
- Nenhuma pendência crítica remanescente nesta revisão.

### Fica para fase futura
- `AB-TF-01` alternativa .NET desktop se houver demanda corporativa por stack única.
- `AB-TF-02` mover persistência para storage externo se houver necessidade de centralização.
- `AB-TF-04` modo de simulação/dry-run como evolução pós-MVP.
- Evolução para web/multiusuário apenas com revisão arquitetural e integração obrigatória com SSO.
