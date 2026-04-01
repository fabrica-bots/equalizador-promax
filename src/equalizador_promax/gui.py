from __future__ import annotations

import csv
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from equalizador_promax import __version__
from equalizador_promax.config import AppConfig, JiraSettings, default_config_path, load_config, save_config
from equalizador_promax.jira_client import save_jira_secret

GUI_SECRET_ACCOUNT = "gui-default"
COMMIT_GRID_COLUMNS = ("cherry_pick_status", "commit_hash", "commit_datetime_utc", "author")


def global_state_dir() -> Path:
    return default_config_path().parent


def global_secret_path() -> Path:
    return global_state_dir() / "gui-secret.txt"


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


def latest_run_directory(repo_path: str | Path | None) -> Path | None:
    if not repo_path:
        return None

    runs_root = Path(repo_path) / ".git" / "equalizador-promax" / "runs"
    if not runs_root.exists():
        return None

    try:
        manifest_paths = sorted(runs_root.glob("**/manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    except OSError:
        return None
    return manifest_paths[0].parent if manifest_paths else None


def latest_commits_csv_path(repo_path: str | Path | None) -> Path | None:
    run_dir = latest_run_directory(repo_path)
    if run_dir is None:
        return None
    commits_csv_path = run_dir / "commits.csv"
    return commits_csv_path if commits_csv_path.exists() else None


def load_commit_grid_rows(commits_csv_path: Path | None) -> list[tuple[str, str, str, str]]:
    if commits_csv_path is None or not commits_csv_path.exists():
        return []

    try:
        with commits_csv_path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            return [
                (
                    str(row.get("cherry_pick_status", "")),
                    str(row.get("commit_hash", "")),
                    str(row.get("commit_datetime_utc", "")),
                    str(row.get("author", "")),
                )
                for row in reader
            ]
    except (OSError, csv.Error, ValueError):
        return []


class EqualizadorPromaxApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Equalizador ProMax")
        self.root.geometry("1100x760")
        self.root.minsize(980, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.process: subprocess.Popen[str] | None = None
        self._build_variables()
        self._load_initial_state()
        self._build_layout()
        self._poll_output_queue()

    def _build_variables(self) -> None:
        self.repo_var = tk.StringVar()
        self.release_id_var = tk.StringVar()
        self.stories_var = tk.StringVar()
        self.force_now_var = tk.BooleanVar(value=False)
        self.source_ref_var = tk.StringVar(value="origin/develop")
        self.target_ref_var = tk.StringVar(value="origin/quality")

        self.base_url_var = tk.StringVar()
        self.auth_mode_var = tk.StringVar(value="token")
        self.username_var = tk.StringVar()
        self.timeout_var = tk.StringVar(value="15")
        self.secret_var = tk.StringVar()

        self.status_var = tk.StringVar(value="Pronto.")
        self.config_path_var = tk.StringVar(value=str(default_config_path()))
        self.commit_grid_status_var = tk.StringVar(value="Selecione um repositorio para visualizar os commits do ultimo run.")
        self._commit_grid_signature: tuple[str, int, int] | None = None
        self.config_window: tk.Toplevel | None = None
        self.username_entry: ttk.Entry | None = None
        self.secret_entry: ttk.Entry | None = None
        self.secret_toggle_button: ttk.Button | None = None
        self.commit_grid: ttk.Treeview | None = None

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        ttk.Label(header, text="Equalizador ProMax", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        header_actions = ttk.Frame(header)
        header_actions.grid(row=0, column=1, sticky="e")
        ttk.Label(header_actions, text=f"Versao {__version__}", font=("Segoe UI", 10, "bold")).grid(
            row=0, column=0, sticky="e"
        )
        ttk.Button(header_actions, text="⚙", width=3, command=self._open_config_modal).grid(
            row=0, column=1, sticky="e", padx=(8, 0)
        )
        ttk.Label(
            header,
            text="Selecione o repositorio, informe Release IDs e/ou stories e siga a jornada em 3 passos: Jira, commits e cherry-picks.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        top = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        top.grid(row=1, column=0, sticky="nsew")
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)
        top.rowconfigure(0, weight=1)

        self._build_execution_panel(top).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_commit_panel(top).grid(row=0, column=1, sticky="nsew")
        self._refresh_commit_grid(force=True)

        bottom = ttk.Frame(self.root, padding=(16, 0, 16, 16))
        bottom.grid(row=2, column=0, sticky="nsew")
        bottom.columnconfigure(0, weight=1)
        bottom.rowconfigure(1, weight=1)

        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.output_text = ScrolledText(bottom, wrap="word", font=("Consolas", 10))
        self.output_text.grid(row=1, column=0, sticky="nsew")
        self.output_text.configure(state="disabled")

    def _build_execution_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Execucao", padding=16)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Repositorio").grid(row=0, column=0, sticky="w")
        repo_entry = ttk.Entry(frame, textvariable=self.repo_var)
        repo_entry.grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(frame, text="Selecionar...", command=self._select_repo).grid(row=0, column=2, sticky="ew")

        ttk.Label(frame, text="Release ID").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.release_entry = ttk.Entry(frame, textvariable=self.release_id_var)
        self.release_entry.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(frame, text="Separe por virgula. Ex.: 59571,59572").grid(
            row=2, column=1, columnspan=2, sticky="w", pady=(4, 0)
        )

        ttk.Label(frame, text="Stories").grid(row=3, column=0, sticky="nw", pady=(12, 0))
        self.stories_entry = ttk.Entry(frame, textvariable=self.stories_var)
        self.stories_entry.grid(row=3, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(frame, text="Separe por virgula. Ex.: SQCRM-7637,SQCRM-7638").grid(
            row=4, column=1, columnspan=2, sticky="w", pady=(4, 0)
        )

        ttk.Label(frame, text="Branche origem").grid(row=5, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.source_ref_var).grid(row=5, column=1, columnspan=2, sticky="ew", pady=(12, 0))

        ttk.Label(frame, text="Branche destino").grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.target_ref_var).grid(row=6, column=1, columnspan=2, sticky="ew", pady=(12, 0))

        ttk.Checkbutton(frame, text="Executar com force-now", variable=self.force_now_var).grid(
            row=7, column=1, columnspan=2, sticky="w", pady=(12, 0)
        )

        journey = ttk.LabelFrame(frame, text="Jornada em 3 etapas", padding=12)
        journey.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        journey.columnconfigure(1, weight=1)
        journey.columnconfigure(2, weight=0)

        ttk.Label(journey, text="1. Jira", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="nw")
        ttk.Label(
            journey,
            text="Busca somente stories e subtasks no Jira, em lotes, e salva o snapshot local para evitar novas chamadas.",
            wraplength=420,
            justify="left",
        ).grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Button(journey, text="Buscar Stories e Tasks", command=self._fetch_jira_snapshot).grid(
            row=0, column=2, sticky="ew"
        )

        ttk.Label(journey, text="2. Commits", font=("Segoe UI", 10, "bold")).grid(row=1, column=0, sticky="nw", pady=(14, 0))
        ttk.Label(
            journey,
            text="Usa apenas o ultimo snapshot Jira salvo neste repositorio para montar a lista de commits candidatos.",
            wraplength=420,
            justify="left",
        ).grid(row=1, column=1, sticky="w", padx=(12, 12), pady=(14, 0))
        ttk.Button(journey, text="Buscar Commits", command=self._fetch_commits).grid(
            row=1, column=2, sticky="ew", pady=(14, 0)
        )

        ttk.Label(journey, text="3. Cherry-picks", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="nw", pady=(14, 0))
        ttk.Label(
            journey,
            text="Cria a branch de equalizacao a partir da branche destino e aplica a lista de commits capturada na etapa anterior.",
            wraplength=420,
            justify="left",
        ).grid(row=2, column=1, sticky="w", padx=(12, 12), pady=(14, 0))
        cherry_pick_actions = ttk.Frame(journey)
        cherry_pick_actions.grid(row=2, column=2, sticky="ew", pady=(14, 0))
        cherry_pick_actions.columnconfigure(0, weight=1)
        ttk.Button(cherry_pick_actions, text="Realizar Cherry-picks", command=self._apply_cherry_picks).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(cherry_pick_actions, text="Retomar Conflito", command=self._resume_run).grid(
            row=1, column=0, sticky="ew", pady=(8, 0)
        )
        ttk.Button(cherry_pick_actions, text="Descartar Branch Atual", command=self._discard_current_branch).grid(
            row=2, column=0, sticky="ew", pady=(8, 0)
        )

        secondary = ttk.Frame(frame)
        secondary.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for column in range(4):
            secondary.columnconfigure(column, weight=1)
        ttk.Button(secondary, text="Doctor", command=self._run_doctor).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(secondary, text="Status", command=self._show_status).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(secondary, text="Abrir Ultimo Run", command=self._open_latest_run_folder).grid(
            row=0, column=2, sticky="ew", padx=4
        )
        ttk.Button(secondary, text="Limpar Saida", command=self._clear_output).grid(row=0, column=3, sticky="ew", padx=(8, 0))

        ttk.Label(
            frame,
            text="Fluxo sugerido: 1) buscar stories e tasks, 2) buscar commits, 3) realizar cherry-picks. Em conflito, use Retomar ou descarte a branch para recomecar da etapa 3.",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=(18, 0))

        return frame

    def _build_commit_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Ultima execucao - Commits", padding=16)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(frame, textvariable=self.commit_grid_status_var, justify="left").grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        grid_frame = ttk.Frame(frame)
        grid_frame.grid(row=1, column=0, sticky="nsew")
        grid_frame.columnconfigure(0, weight=1)
        grid_frame.rowconfigure(0, weight=1)

        self.commit_grid = ttk.Treeview(
            grid_frame,
            columns=COMMIT_GRID_COLUMNS,
            show="headings",
            height=18,
        )
        self.commit_grid.grid(row=0, column=0, sticky="nsew")

        vertical_scrollbar = ttk.Scrollbar(grid_frame, orient="vertical", command=self.commit_grid.yview)
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar = ttk.Scrollbar(grid_frame, orient="horizontal", command=self.commit_grid.xview)
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        self.commit_grid.configure(yscrollcommand=vertical_scrollbar.set, xscrollcommand=horizontal_scrollbar.set)

        self.commit_grid.heading("cherry_pick_status", text="cherry_pick_status")
        self.commit_grid.heading("commit_hash", text="commit_hash")
        self.commit_grid.heading("commit_datetime_utc", text="commit_datetime_utc")
        self.commit_grid.heading("author", text="author")
        self.commit_grid.column("cherry_pick_status", width=130, minwidth=110, stretch=False)
        self.commit_grid.column("commit_hash", width=260, minwidth=220, stretch=False)
        self.commit_grid.column("commit_datetime_utc", width=180, minwidth=160, stretch=False)
        self.commit_grid.column("author", width=140, minwidth=120, stretch=True)
        return frame

    def _open_config_modal(self) -> None:
        if self.config_window is not None and self.config_window.winfo_exists():
            self.config_window.deiconify()
            self.config_window.lift()
            self.config_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        window.title("Configuracao Jira")
        window.geometry("520x360")
        window.minsize(480, 340)
        window.transient(self.root)
        window.grab_set()
        window.protocol("WM_DELETE_WINDOW", self._close_config_modal)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)
        self.config_window = window

        frame = ttk.Frame(window, padding=16)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Arquivo de config").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.config_path_var, wraplength=320, justify="left").grid(
            row=0, column=1, sticky="w", padx=(8, 0)
        )

        ttk.Label(frame, text="URL base").grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.base_url_var).grid(row=1, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))

        ttk.Label(frame, text="Autenticacao").grid(row=2, column=0, sticky="w", pady=(12, 0))
        auth_combo = ttk.Combobox(frame, textvariable=self.auth_mode_var, values=("token", "basic"), state="readonly")
        auth_combo.grid(row=2, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))
        auth_combo.bind("<<ComboboxSelected>>", lambda _event: self._toggle_auth_mode())

        ttk.Label(frame, text="Usuario").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.username_entry = ttk.Entry(frame, textvariable=self.username_var)
        self.username_entry.grid(row=3, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))

        ttk.Label(frame, text="PAT / Senha").grid(row=4, column=0, sticky="w", pady=(12, 0))
        secret_frame = ttk.Frame(frame)
        secret_frame.grid(row=4, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))
        secret_frame.columnconfigure(0, weight=1)
        self.secret_entry = ttk.Entry(secret_frame, textvariable=self.secret_var, show="*")
        self.secret_entry.grid(row=0, column=0, sticky="ew")
        self.secret_toggle_button = ttk.Button(secret_frame, text="Mostrar", command=self._toggle_secret_visibility, width=10)
        self.secret_toggle_button.grid(row=0, column=1, padx=(8, 0))
        ttk.Label(frame, text="Informe aqui o token real que a aplicacao deve usar para acessar o Jira.").grid(
            row=5, column=1, sticky="w", pady=(4, 0)
        )

        ttk.Label(frame, text="Timeout (s)").grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.timeout_var).grid(row=6, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))

        actions = ttk.Frame(frame)
        actions.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        ttk.Button(actions, text="Salvar Configuracao", command=self._save_jira_configuration).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(actions, text="Fechar", command=self._close_config_modal).grid(
            row=0, column=1, sticky="ew", padx=(6, 0)
        )

        self._toggle_auth_mode()

    def _close_config_modal(self) -> None:
        if self.config_window is None:
            return
        try:
            self.config_window.grab_release()
        except Exception:
            pass
        try:
            self.config_window.destroy()
        finally:
            self.config_window = None
            self.username_entry = None
            self.secret_entry = None
            self.secret_toggle_button = None

    def _select_repo(self) -> None:
        selected = filedialog.askdirectory(title="Selecione o repositorio Git")
        if selected:
            self.repo_var.set(selected)
            self._save_ui_state()
            self._refresh_commit_grid(force=True)

    def _toggle_auth_mode(self) -> None:
        if self.username_entry is None:
            return
        is_basic = self.auth_mode_var.get() == "basic"
        self.username_entry.configure(state="normal" if is_basic else "disabled")

    def _toggle_secret_visibility(self) -> None:
        if self.secret_entry is None or self.secret_toggle_button is None:
            return
        is_hidden = self.secret_entry.cget("show") == "*"
        self.secret_entry.configure(show="" if is_hidden else "*")
        self.secret_toggle_button.configure(text="Ocultar" if is_hidden else "Mostrar")

    def _save_jira_configuration(self) -> None:
        self._persist_configuration(show_success=True)

    def _persist_configuration(self, *, show_success: bool = False) -> bool:
        try:
            timeout = int(self.timeout_var.get().strip() or "15")
        except ValueError:
            messagebox.showerror("Configuracao invalida", "O timeout precisa ser numerico.")
            return False

        config_path = default_config_path()
        settings = JiraSettings(
            base_url=self.base_url_var.get().strip(),
            auth_mode=self.auth_mode_var.get().strip(),
            username=self.username_var.get().strip() or None,
            credential_service="equalizador-promax/jira",
            credential_account=GUI_SECRET_ACCOUNT,
            timeout_seconds=timeout,
        )
        config = AppConfig(jira=settings, config_path=config_path)

        try:
            saved_path = save_config(config, config_path)
            secret = self.secret_var.get()
            if secret:
                save_jira_secret(settings, secret)
                self._save_global_secret(secret)
            self.config_path_var.set(str(saved_path))
            self._save_ui_state()
        except Exception as exc:
            messagebox.showerror("Erro ao salvar", str(exc))
            return False

        if show_success:
            messagebox.showinfo("Configuracao salva", f"Configuracao Jira salva em:\n{saved_path}")
        return True

    def _run_doctor(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        source_ref, target_ref = self._require_refs()
        if not source_ref or not target_ref:
            return
        if not self._persist_configuration():
            return
        self._launch_cli(
            ["doctor", "--repo", repo, "--source-ref", source_ref, "--target-ref", target_ref],
            "Executando doctor...",
        )

    def _require_story_inputs(self) -> tuple[str, str] | None:
        release_ids = self.release_id_var.get().strip()
        stories = self.stories_var.get().strip()
        if not release_ids and not stories:
            messagebox.showerror("Campo obrigatorio", "Informe pelo menos um Release ID ou uma story manual.")
            return None
        return release_ids, stories

    def _fetch_jira_snapshot(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        source_ref, target_ref = self._require_refs()
        if not source_ref or not target_ref:
            return

        inputs = self._require_story_inputs()
        if inputs is None:
            return
        release_ids, stories = inputs

        command = ["fetch-jira", "--repo", repo, "--source-ref", source_ref, "--target-ref", target_ref]
        if release_ids:
            command.extend(["--release-id", release_ids])
        if stories:
            command.extend(["--stories", stories])
        if self.force_now_var.get():
            command.append("--force-now")

        self._save_ui_state()
        if not self._persist_configuration():
            return
        self._launch_cli(command, "Buscando stories e subtasks no Jira...")

    def _fetch_commits(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        self._save_ui_state()
        if not self._persist_configuration():
            return
        self._launch_cli(["fetch-commits", "--repo", repo], "Buscando commits a partir do ultimo snapshot Jira...")

    def _apply_cherry_picks(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        self._save_ui_state()
        if not self._persist_configuration():
            return
        self._launch_cli(["apply-cherry-picks", "--repo", repo], "Aplicando cherry-picks salvos...")

    def _resume_run(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        if not self._persist_configuration():
            return
        self._launch_cli(["resume", "--repo", repo], "Retomando execucao pausada...")

    def _discard_current_branch(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        confirmed = messagebox.askyesno(
            "Descartar branch atual",
            "Isso vai abortar o cherry-pick em andamento, apagar a branch de equalizacao e voltar para a branche origem. Deseja continuar?",
        )
        if not confirmed:
            return
        self._save_ui_state()
        if not self._persist_configuration():
            return
        self._launch_cli(["discard-branch", "--repo", repo], "Descartando branch atual e retornando para a origem...")

    def _show_status(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        if not self._persist_configuration():
            return
        self._launch_cli(["status", "--repo", repo], "Consultando status...")

    def _open_latest_run_folder(self) -> None:
        repo = self.repo_var.get().strip()
        if not repo:
            messagebox.showerror("Campo obrigatorio", "Selecione o repositorio.")
            return

        runs_root = Path(repo) / ".git" / "equalizador-promax" / "runs"
        if not runs_root.exists():
            messagebox.showerror("Pasta nao encontrada", f"Nenhum run encontrado em:\n{runs_root}")
            return

        target = latest_run_directory(repo) or runs_root
        os.startfile(str(target))

    def _refresh_commit_grid(self, *, force: bool = False) -> None:
        if self.commit_grid is None:
            return
        repo = self.repo_var.get().strip()
        if not repo:
            self._set_commit_grid_rows([], "Selecione um repositorio para visualizar os commits do ultimo run.")
            self._commit_grid_signature = None
            return

        commits_csv_path = latest_commits_csv_path(repo)
        signature = self._build_commit_grid_signature(commits_csv_path)
        if not force and signature == self._commit_grid_signature:
            return

        self._commit_grid_signature = signature
        if commits_csv_path is None:
            self._set_commit_grid_rows([], "Nenhum commits.csv encontrado no ultimo run deste repositorio.")
            return

        rows = load_commit_grid_rows(commits_csv_path)
        if rows:
            self._set_commit_grid_rows(
                rows,
                f"Fonte: {commits_csv_path.parent.name}\\commits.csv | {len(rows)} commits",
            )
            return

        self._set_commit_grid_rows([], f"Fonte: {commits_csv_path.parent.name}\\commits.csv | sem commits capturados ainda.")

    def _build_commit_grid_signature(self, commits_csv_path: Path | None) -> tuple[str, int, int] | None:
        if commits_csv_path is None or not commits_csv_path.exists():
            return None
        try:
            stat_result = commits_csv_path.stat()
        except OSError:
            return None
        return (str(commits_csv_path), stat_result.st_mtime_ns, stat_result.st_size)

    def _set_commit_grid_rows(self, rows: list[tuple[str, str, str, str]], status_message: str) -> None:
        if self.commit_grid is None:
            self.commit_grid_status_var.set(status_message)
            return
        for item_id in self.commit_grid.get_children():
            self.commit_grid.delete(item_id)
        for row in rows:
            self.commit_grid.insert("", tk.END, values=row)
        self.commit_grid_status_var.set(status_message)

    def _clear_output(self) -> None:
        self.output_text.configure(state="normal")
        self.output_text.delete("1.0", tk.END)
        self.output_text.configure(state="disabled")
        self.status_var.set("Saida limpa.")

    def _launch_cli(self, command_args: list[str], status_message: str) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("Execucao em andamento", "Ja existe um processo em execucao.")
            return

        self.status_var.set(status_message)
        config_args = ["--config", str(default_config_path())]
        self._sync_secret_to_runtime_store()

        env = os.environ.copy()
        if is_frozen_app():
            launch_command = [sys.executable, *config_args, *command_args]
        else:
            package_parent = Path(__file__).resolve().parents[1]
            current_pythonpath = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                str(package_parent) if not current_pythonpath else f"{package_parent}{os.pathsep}{current_pythonpath}"
            )
            launch_command = [sys.executable, "-m", "equalizador_promax", *config_args, *command_args]

        self._append_output(f"$ {' '.join(launch_command)}\n")

        self.process = subprocess.Popen(
            launch_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        threading.Thread(target=self._stream_process_output, daemon=True).start()

    def _stream_process_output(self) -> None:
        assert self.process is not None
        for line in self.process.stdout or []:
            self.output_queue.put(("line", line))
        return_code = self.process.wait()
        self.output_queue.put(("line", f"\n[processo finalizado com codigo {return_code}]\n"))
        status_message = "Execucao concluida." if return_code == 0 else f"Execucao finalizada com codigo {return_code}."
        self.output_queue.put(("status", status_message))

    def _poll_output_queue(self) -> None:
        while True:
            try:
                item_type, value = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if item_type == "line":
                self._append_output(value)
            elif item_type == "status":
                self.status_var.set(value)
        self._refresh_commit_grid()
        self.root.after(150, self._poll_output_queue)

    def _append_output(self, text: str) -> None:
        self.output_text.configure(state="normal")
        self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)
        self.output_text.configure(state="disabled")

    def _require_repo(self) -> str | None:
        repo = self.repo_var.get().strip()
        if not repo:
            messagebox.showerror("Campo obrigatorio", "Selecione o repositorio.")
            return None
        return repo

    def _require_refs(self) -> tuple[str | None, str | None]:
        source_ref = self.source_ref_var.get().strip()
        target_ref = self.target_ref_var.get().strip()
        if not source_ref:
            messagebox.showerror("Campo obrigatorio", "Informe a branche origem.")
            return None, None
        if not target_ref:
            messagebox.showerror("Campo obrigatorio", "Informe a branche destino.")
            return None, None
        return source_ref, target_ref

    def _load_initial_state(self) -> None:
        try:
            config = load_config()
            self.base_url_var.set(config.jira.base_url)
            self.auth_mode_var.set(config.jira.auth_mode)
            self.username_var.set(config.jira.username or "")
            self.timeout_var.set(str(config.jira.timeout_seconds))
            if config.config_path:
                self.config_path_var.set(str(config.config_path))
        except Exception:
            pass

        state = self._load_ui_state()
        self.repo_var.set(state.get("repo_path", ""))
        self.release_id_var.set("")
        self.stories_var.set("")
        self.force_now_var.set(bool(state.get("force_now", False)))
        self.source_ref_var.set(state.get("source_ref", "origin/develop"))
        self.target_ref_var.set(state.get("target_ref", "origin/quality"))
        secret_path = global_secret_path()
        if secret_path.exists():
            try:
                self.secret_var.set(secret_path.read_text(encoding="utf-8").strip())
            except Exception:
                pass

    def _state_file_path(self) -> Path:
        config_path = default_config_path()
        return config_path.parent / "gui-state.json"

    def _load_ui_state(self) -> dict[str, str]:
        path = self._state_file_path()
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_ui_state(self) -> None:
        path = self._state_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "repo_path": self.repo_var.get().strip(),
            "force_now": self.force_now_var.get(),
            "source_ref": self.source_ref_var.get().strip(),
            "target_ref": self.target_ref_var.get().strip(),
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def _save_global_secret(self, secret: str) -> None:
        secret_path = global_secret_path()
        secret_path.parent.mkdir(parents=True, exist_ok=True)
        secret_path.write_text(secret, encoding="utf-8")

    def _sync_secret_to_runtime_store(self) -> None:
        secret = self.secret_var.get().strip()
        if not secret:
            secret_path = global_secret_path()
            if secret_path.exists():
                secret = secret_path.read_text(encoding="utf-8").strip()
                self.secret_var.set(secret)
        if not secret:
            return

        config = load_config(default_config_path())
        save_jira_secret(config.jira, secret)

    def _on_close(self) -> None:
        try:
            self._close_config_modal()
            self._save_ui_state()
            self._persist_configuration()
        finally:
            self.root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    try:
        root.iconname("Equalizador ProMax")
    except Exception:
        pass
    EqualizadorPromaxApp(root)
    root.mainloop()
