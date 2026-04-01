# Equalizador ProMax

CLI local em Python para automatizar a equalizacao assistida de um repositorio Git com suporte a:

- consulta de stories e subtasks no Jira;
- descoberta de commits ja integrados em `develop`;
- deduplicacao e ordenacao cronologica dos commits;
- criacao de branch baseada em uma ref destino configuravel;
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

Ou informar explicitamente as refs de origem e destino:

```powershell
python -m equalizador_promax doctor --repo C:\caminho\repo --source-ref origin/develop --target-ref origin/quality
```

Abrir a interface desktop:

```powershell
python -m equalizador_promax gui
```

Na interface desktop, o segredo real do Jira deve ser informado no campo `PAT / Senha`.
Quando salvo pela interface, esse token fica guardado localmente em `%APPDATA%\\EqualizadorProMax`, para reaparecer automaticamente nas proximas aberturas sem depender de variavel de ambiente e sem entrar no versionamento do Git.
Na area de execucao, o usuario tambem pode ajustar a `branche origem` e a `branche destino`. Os defaults sao `origin/develop` e `origin/quality`.

Executar uma equalizacao com stories manuais:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --stories SQCRM-6805,SQCRM-6806
```

Com refs explicitas:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --stories SQCRM-6805,SQCRM-6806 --source-ref origin/develop --target-ref origin/quality
```

Ou usar um ou mais identificadores numericos de release/version no Jira:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --release-id 59571,59572
```

Tambem e possivel combinar releases e stories manuais na mesma execucao:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --release-id 59571,59572 --stories SQCRM-6805,SQCRM-6806
```

Para ignorar uma execucao anterior aberta com o mesmo fingerprint:

```powershell
python -m equalizador_promax run --repo C:\caminho\repo --release-id 59571,59572 --force-now
```

Quando a execucao usa exatamente um `--release-id`, a branch de equalizacao passa a seguir o padrao:

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

## Build Windows

Gerar o executavel da interface:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
```

Esse comando incrementa automaticamente a versao do produto antes de gerar o executavel.

Saida esperada:

```text
dist\EqualizadorProMax.exe
```

Se voce gerou uma versao que nao sera distribuida e quer desfazer o bump:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\rollback-version.ps1
```

Esse rollback volta a versao dos arquivos do projeto e remove os artefatos locais de build/instalador.

Se quiser um instalador `.exe`, use o script do Inno Setup em:

```text
installer\EqualizadorProMax.iss
```

Depois de gerar `dist\EqualizadorProMax.exe`, voce pode:

1. Compilar manualmente o `.iss` no Inno Setup, ou
2. Rodar o script abaixo se o `ISCC` estiver no `PATH`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```

Saida esperada:

```text
dist-installer\EqualizadorProMax-Setup.exe
```

### Gerar o instalador em outra maquina

Prerequisitos da maquina que vai gerar o pacote:

- Python 3.11+
- pip
- Inno Setup com `ISCC` disponivel no `PATH`

Passo a passo :

```powershell
git clone <repo>
cd equalizador-promax
powershell -ExecutionPolicy Bypass -File .\scripts\build-windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\build-installer.ps1
```

Arquivos gerados:

```text
dist\EqualizadorProMax.exe
dist-installer\EqualizadorProMax-Setup.exe
```

A versao atual tambem fica visivel na interface desktop.

Se quiser usar um icone customizado no executavel e no instalador, coloque um arquivo:

```text
installer\app.ico
```
