import subprocess
import os
from datetime import datetime

# Arquivos
historias_file = "historias.txt"
saida_file = "commits_encontrados.txt"

# Lê as histórias
with open(historias_file, "r", encoding="utf-8") as f:
    historias = [linha.strip() for linha in f if linha.strip()]

resultados = []

for historia in historias:
    # Procura merges no develop relacionados à história
    cmd_merges = [
        "git", "log", "develop", "--merges", "--first-parent",
        "--pretty=%H;%s"
    ]
    merges = subprocess.check_output(cmd_merges, encoding="utf-8", errors="ignore").splitlines()

    for merge in merges:
        commit_merge, mensagem = merge.split(";", 1)

        if historia.lower() in mensagem.lower():
            # Pega os dois pais do merge (primeiro é develop, segundo é branch mergeada)
            pais = subprocess.check_output(
                ["git", "show", "--pretty=%P", "-s", commit_merge],
                encoding="utf-8"
            ).strip().split()

            if len(pais) < 2:
                continue

            branch_parent = pais[1]

            # Lista commits dessa branch (até o merge), excluindo merge commits
            cmd_commits = [
                "git", "log", f"{pais[0]}..{branch_parent}",
                "--no-merges",
                "--pretty=%H;%ct;%an"
            ]
            commits = subprocess.check_output(cmd_commits, encoding="utf-8", errors="ignore").splitlines()

            for linha in commits:
                hash_commit, timestamp, autor = linha.split(";", 2)
                data_fmt = datetime.fromtimestamp(int(timestamp)).strftime("%d/%m/%Y %H:%M:%S")
                resultados.append((hash_commit, data_fmt, autor, mensagem))

# Ordena por data
resultados.sort(key=lambda x: datetime.strptime(x[1], "%d/%m/%Y %H:%M:%S"))

# Salva no arquivo
with open(saida_file, "w", encoding="utf-8") as f:
    for r in resultados:
        f.write(f"{r[0]};{r[1]};{r[2]};{r[3]}\n")

print(f"Commits salvos em {saida_file}")