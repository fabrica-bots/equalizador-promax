# Product Brief

## 1. Identificação da Demanda
- **Título:** Equalizador ProMax
- **Projeto:** Equalizador ProMax
- **Issue:** Não informada
- **Responsável pela etapa:** BotPO

## 2. Resumo Executivo
O Equalizador ProMax tem como objetivo automatizar a equalização de ambiente hoje feita com forte dependência de scripts locais e operação manual. O MVP deve receber uma lista de estórias da release, buscar no Jira as subtasks de cada estória, localizar no Git apenas os commits já integrados em `develop`, eliminar duplicidades, ordenar os commits do mais antigo para o mais novo, criar uma branch baseada em `origin/quality` e executar o cherry-pick sequencial de forma assistida, pausando em cada conflito para intervenção do TechLead.

## 3. Problema Atual
O processo atual de equalização é operacionalmente frágil e distribuído em múltiplas etapas manuais:
- a lista de estórias/tasks é obtida a partir da release;
- um script no Jira busca subtasks por estória;
- um script local percorre merges em `develop` e tenta localizar commits relacionados;
- depois é criada manualmente uma branch baseada em `quality` e os commits são aplicados um a um.

Os scripts atuais mostram que:
- o `script_jira.txt` consulta a API REST do Jira por issue e imprime a estória e suas subtasks;
- o `script.py` percorre merges do `develop`, usa `--first-parent`, associa história por texto contido na mensagem do merge e ordena os commits por data antes de salvar a saída;
- o arquivo `commits_encontrados.txt` evidencia repetição de PRs e variações de nome de branch, o que aumenta risco de duplicidade e associação imprecisa.

## 4. Objetivo da Entrega
Entregar uma automação assistida que permita ao TechLead:
- informar uma lista de estórias da release e o diretório local do repositório clonado;
- obter automaticamente as subtasks de cada estória no Jira;
- localizar os commits elegíveis já integrados em `develop`;
- montar uma lista distinta e cronológica de commits;
- criar uma branch de equalização baseada em `origin/quality`;
- executar os cherry-picks em sequência, pausando em cada conflito e retomando após ação do usuário;
- registrar evidências do que foi encontrado, aplicado, ignorado, conflitado ou não localizado.

## 5. Público/Consumidor da Solução
- **Público principal:** TechLeads
- **Beneficiários secundários:** time técnico responsável por promoção entre ambientes

## 6. Escopo Inicial

### Entra no escopo
- [ ] **PB-REQ-01** Receber como entrada o diretório local do repositório clonado e a lista de estórias da release.
- [ ] **PB-REQ-02** Consultar o Jira para obter as subtasks de cada estória informada.
- [ ] **PB-REQ-03** Consolidar uma lista única de itens elegíveis para rastreamento, composta pelas estórias de entrada e suas subtasks.
- [ ] **PB-REQ-04** Localizar apenas commits já integrados em `develop` relacionados aos itens elegíveis.
- [ ] **PB-REQ-05** Eliminar duplicidade de commits antes da execução da equalização.
- [ ] **PB-REQ-06** Ordenar os commits distintos em ordem cronológica crescente, do mais antigo para o mais novo.
- [ ] **PB-REQ-07** Criar uma branch de equalização com base em `origin/quality`.
- [ ] **PB-REQ-08** Executar cherry-pick sequencial de cada commit encontrado na ordem definida.
- [ ] **PB-REQ-09** Pausar a execução ao encontrar conflito de cherry-pick, aguardando intervenção manual do TechLead e retomando depois para o próximo commit.
- [ ] **PB-REQ-10** Quando não houver correspondência inequívoca de commit para uma estória ou subtask, registrar a ausência e continuar o processamento.
- [ ] **PB-REQ-11** Registrar log rastreável da execução, incluindo itens consultados, commits encontrados, commits ignorados por duplicidade, conflitos e itens sem correspondência.
- [ ] **PB-REQ-12** Gerar um resumo final utilizável pelo TechLead ao término da execução.
- [ ] **PB-REQ-13** Operar inicialmente sobre um único repositório local informado pelo usuário.

### Fora de escopo
- [ ] Não entra integração multi-repositório no MVP.
- [ ] Não entra resolução automática de conflitos.
- [ ] Não entra alteração do processo de criação de release no Jira.
- [ ] Não entra deploy ou promoção automática para produção.
- [ ] Não entra redefinição das convenções de branch e merge do time.
- [ ] Não entra suporte a commits ainda não integrados em `develop`.
- [ ] Não entra refatoração completa da governança de versionamento do time.

### Assunções
- O usuário fornecerá a lista de estórias da release no início do processo.
- As subtasks necessárias podem ser recuperadas a partir das estórias via Jira.
- O repositório já estará clonado localmente no diretório informado pelo usuário.
- `origin/quality` existe e pode ser usada como base da branch de equalização.
- O vínculo entre item Jira e commit continuará dependendo de evidências presentes no histórico Git já adotado pelo time.

## 7. Critérios de Aceite
- [ ] **PB-AC-01** Dado um diretório de repositório válido e uma lista de estórias válida, a solução deve iniciar o processo de equalização sem exigir montagem manual de arquivos intermediários.
- [ ] **PB-AC-02** Para cada estória informada, a solução deve consultar o Jira e obter a própria estória e suas subtasks associadas.
- [ ] **PB-AC-03** A solução deve consolidar os identificadores elegíveis sem duplicar itens repetidos na entrada ou no retorno do Jira.
- [ ] **PB-AC-04** A solução deve considerar somente commits já integrados em `develop` como candidatos à equalização.
- [ ] **PB-AC-05** A lista final de commits a aplicar deve conter hashes únicos, sem repetição de cherry-pick do mesmo commit.
- [ ] **PB-AC-06** Os commits selecionados para aplicação devem ser ordenados cronologicamente do mais antigo para o mais novo antes da execução.
- [ ] **PB-AC-07** Antes do primeiro cherry-pick, a solução deve criar a branch de equalização a partir de `origin/quality`.
- [ ] **PB-AC-08** A solução deve executar os cherry-picks um a um na ordem calculada.
- [ ] **PB-AC-09** Ao ocorrer conflito em um cherry-pick, a solução deve interromper a sequência, identificar o commit em conflito e permitir retomada posterior a partir do ponto interrompido.
- [ ] **PB-AC-10** Quando uma estória ou subtask não tiver correspondência inequívoca de commit, a solução deve registrar esse fato no log e seguir para o próximo item sem abortar o processo inteiro.
- [ ] **PB-AC-11** Ao final da execução, a solução deve apresentar resumo com, no mínimo, total de estórias consultadas, total de subtasks obtidas, total de commits encontrados, total de commits distintos aplicados, total de conflitos e total de itens sem correspondência.
- [ ] **PB-AC-12** O log final deve permitir rastrear para cada item Jira se houve commit encontrado, commit ignorado por duplicidade, conflito ou ausência de correspondência.
- [ ] **PB-AC-13** O MVP deve funcionar inicialmente para um único repositório por execução.

## 8. Restrições Conhecidas
- O `script_jira.txt` atual já usa a API REST do Jira por issue e imprime a chave da estória e as subtasks retornadas.
- O `script.py` atual busca merges apenas em `develop`, usando `--merges` e `--first-parent`, associa a história por presença textual na mensagem do merge e ordena a saída por data.
- O `commits_encontrados.txt` atual já evidencia repetição de PRs e branches com convenções variadas, reforçando a necessidade de `distinct` antes do cherry-pick.
- O MVP deve operar apenas em um repositório local por vez.
- O comportamento desejado para conflito é pausa assistida, não resolução automática.

## 9. Riscos de Produto
- **PB-RISK-01 — Associação imprecisa entre item Jira e commit**
  - Impacto: inclusão indevida ou omissão de commits na equalização.
  - Mitigação sugerida: exigir log explícito de correspondência e tratar ausência de vínculo inequívoco como item sem correspondência.

- **PB-RISK-02 — Duplicidade de commits em múltiplas estórias/subtasks**
  - Impacto: cherry-pick repetido e aumento do risco operacional.
  - Mitigação sugerida: deduplicação obrigatória por hash antes da aplicação.

- **PB-RISK-03 — Conflitos sucessivos tornarem a execução lenta ou confusa**
  - Impacto: perda de rastreabilidade e interrupção operacional prolongada.
  - Mitigação sugerida: pausa controlada por conflito, com retomada explícita e log do ponto interrompido.

- **PB-RISK-04 — Dependência da qualidade do histórico Git atual**
  - Impacto: baixa confiança na descoberta automática quando mensagens de merge e branches fogem do padrão.
  - Mitigação sugerida: manter rastreabilidade por item, registrar exceções e não esconder ausência de correspondência.

- **PB-RISK-05 — Falha de acesso ao Jira ou permissão insuficiente**
  - Impacto: impossibilidade de montar a lista de subtasks da release.
  - Mitigação sugerida: validar acesso ao Jira no início do fluxo e falhar com mensagem objetiva quando a dependência externa estiver indisponível.

- **PB-RISK-06 — Expectativa de cobertura total no MVP**
  - Impacto: frustração do usuário caso algumas estórias/subtasks fiquem sem commit associado.
  - Mitigação sugerida: deixar explícito que ausência inequívoca deve ser logada e não escondida.

## 10. Dependências

### Dependências para o BotArq
- **PB-DEP-01** Definir a forma oficial de autenticação/autorização para consulta à API do Jira.
- **PB-DEP-02** Definir o mecanismo de entrada da lista de estórias no MVP.
- **PB-DEP-03** Definir a estratégia de correlação entre itens Jira e commits já integrados em `develop`.
- **PB-DEP-04** Definir o mecanismo de criação e nomeação da branch de equalização baseada em `origin/quality`.
- **PB-DEP-05** Definir o mecanismo de pausa e retomada segura após conflito de cherry-pick.
- **PB-DEP-06** Definir o formato e local de persistência dos logs e do resumo final da execução.
- **PB-DEP-07** Definir o tratamento de reexecução da mesma equalização para evitar estado inconsistente na branch local.

## 11. Dúvidas para o Maestro
- **PB-Q-01** O MVP deve oferecer também um modo de simulação/pré-validação sem aplicar cherry-picks, além do modo de execução assistida?
- **PB-Q-02** No log final, quando um mesmo commit estiver relacionado a múltiplos itens Jira, o produto deve exibir todas as origens relacionadas ou apenas uma consolidação por hash?

## 12. Recomendação do BotPO
Informe a recomendação final:

- [x] Apto para seguir para Arquitetura
- [ ] Precisa de decisão do Maestro antes de seguir
- [ ] Precisa de refino adicional

## 13. Observações Finais
- A direção do MVP ficou definida: entrada por lista de estórias, busca de subtasks no Jira, descoberta de commits já integrados em `develop`, deduplicação, ordenação cronológica, criação de branch baseada em `origin/quality` e cherry-pick assistido com pausa em conflito.
- O `script_jira.txt` já demonstra viabilidade da etapa de obtenção de subtasks via API do Jira.
- O `script.py` já demonstra o comportamento base de descoberta de commits em `develop`, mas ainda sem tratamento explícito de deduplicação, pausa assistida e fechamento operacional da equalização.

## 14. Definição de pronto para arquitetura
A demanda está pronta para arquitetura quando:
- o comportamento de ponta a ponta do MVP estiver mantido como fluxo oficial;
- as dependências `PB-DEP-01` a `PB-DEP-07` forem tratadas pelo BotArq;
- as dúvidas `PB-Q-01` e `PB-Q-02` forem classificadas como opcionais para o MVP ou absorvidas como decisão de design de produto;
- o arquiteto puder desenhar a solução sem alterar os objetivos, o escopo e os critérios de aceite aqui definidos.

## 15. Matriz Objetivo -> Requisito -> Critério de aceite
| Objetivo | Requisito | Critério de aceite |
|---|---|---|
| Receber entrada operacional do processo | PB-REQ-01 | PB-AC-01 |
| Obter subtasks no Jira | PB-REQ-02 | PB-AC-02 |
| Consolidar universo elegível de rastreamento | PB-REQ-03 | PB-AC-03 |
| Considerar apenas commits válidos para equalização | PB-REQ-04 | PB-AC-04 |
| Evitar repetição de cherry-pick | PB-REQ-05 | PB-AC-05 |
| Garantir ordem correta de aplicação | PB-REQ-06 | PB-AC-06 |
| Preparar branch de equalização | PB-REQ-07 | PB-AC-07 |
| Aplicar commits automaticamente | PB-REQ-08 | PB-AC-08 |
| Tratar conflito de forma assistida | PB-REQ-09 | PB-AC-09 |
| Não bloquear o fluxo por item sem correspondência | PB-REQ-10 | PB-AC-10 |
| Registrar rastreabilidade da execução | PB-REQ-11 | PB-AC-11, PB-AC-12 |
| Encerrar com visão consolidada do processo | PB-REQ-12 | PB-AC-11 |
| Restringir o MVP a um repositório por vez | PB-REQ-13 | PB-AC-13 |
