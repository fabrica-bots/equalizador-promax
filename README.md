# Equalizador ProMax

CLI local em Python para automatizar a equalizacao assistida de um repositorio Git com suporte a:

- consulta de stories e subtasks no Jira;
- descoberta de commits ja integrados em `develop`;
- deduplicacao e ordenacao cronologica dos commits;
- criacao de branch baseada em `origin/quality`;
- cherry-pick sequencial com pausa em conflito;
- persistencia de estado, logs e resumo em `.git/equalizador-promax/runs/<run-id>/`.

## Requisitos

- Python 3.11+
- Git acessivel no `PATH`
- credencial valida do Jira disponivel localmente

## Configuracao do Jira

A CLI procura configuracao primeiro nas variaveis de ambiente e depois no arquivo:

- Windows: `%APPDATA%\\EqualizadorProMax\\config.toml`
- fallback: `~/.equalizador-promax/config.toml`

Se o arquivo nao existir, ele e criado automaticamente com valores default, incluindo:

- `base_url = "https://agile.corp.edp.pt"`
- `auth_mode = "token"`
- `credential_account = ""`

Exemplo de `config.toml`:

```toml
[jira]
base_url = "https://agile.corp.edp.pt"
auth_mode = "basic"
username = "usuario@empresa"
credential_service = "equalizador-promax/jira"
credential_account = "usuario@empresa"
timeout_seconds = 15
```

O segredo e lido primeiro do Windows Credential Manager via `keyring`. Em desenvolvimento controlado, a variavel `EQUALIZADOR_PROMAX_JIRA_SECRET` pode ser usada como fallback.

## Uso

Validar ambiente:

```powershell
python -m equalizador_promax doctor --repo C:\caminho\repo
```

Abrir a interface desktop:

```powershell
python -m equalizador_promax gui
```

Na interface desktop, o segredo real do Jira deve ser informado no campo `PAT / Senha`.
Quando salvo pela interface, esse token fica guardado localmente em `%APPDATA%\\EqualizadorProMax`, para reaparecer automaticamente nas proximas aberturas sem depender de variavel de ambiente e sem entrar no versionamento do Git.

Executar uma equalizacao:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --stories SQCRM-6805,SQCRM-6806
```

Ou usar o identificador numerico da release/version no Jira:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --release-id 59571
```

Para ignorar uma execucao anterior aberta com o mesmo fingerprint:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --release-id 59571 --force-now
```

Quando a execucao usa `--release-id`, a branch de equalizacao passa a seguir o padrao:

```text
equalizacao/NOME_VERSAO_DD-MM-YYYY-HH-MM-SS
```

Retomar uma execucao pausada por conflito:

```powershell
python -m equalizador_promax resume --repo C:\caminho\repo
```

Inspecionar o status da ultima execucao:

```powershell
python -m equalizador_promax status --repo C:\caminho\repo
```

## Observacao operacional

Quando houver conflito, a ferramenta pausa e grava instrucoes em `resume-hints.txt`. Resolva os arquivos, deixe o cherry-pick pronto para continuacao e entao execute `resume`. Neste primeiro corte, o fluxo pressupoe que a retomada seja feita pela CLI, sem rodar `git cherry-pick --continue` manualmente antes do `resume`.

## Artefatos por execucao

Cada execucao grava arquivos em `.git/equalizador-promax/runs/<run-id>/`, incluindo:

- `stories.txt`
- `subtasks_por_story.txt`
- `commits.csv`
- `manifest.json`
- `items.json`
- `events.jsonl`
- `execution.log`
- `summary.md`
- `resume-hints.txt`
