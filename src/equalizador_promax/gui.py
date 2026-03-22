from __future__ import annotations

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


def global_state_dir() -> Path:
    return default_config_path().parent


def global_secret_path() -> Path:
    return global_state_dir() / "gui-secret.txt"


def is_frozen_app() -> bool:
    return bool(getattr(sys, "frozen", False))


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
        self.input_mode_var = tk.StringVar(value="release")
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

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        header = ttk.Frame(self.root, padding=16)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        header.columnconfigure(1, weight=0)
        ttk.Label(header, text="Equalizador ProMax", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(header, text=f"Versao {__version__}", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="e")
        ttk.Label(
            header,
            text="Selecione o repositorio, informe a release ou as stories e acompanhe a execucao sem sair da aplicacao.",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        top = ttk.Frame(self.root, padding=(16, 0, 16, 12))
        top.grid(row=1, column=0, sticky="nsew")
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        self._build_execution_panel(top).grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._build_config_panel(top).grid(row=0, column=1, sticky="nsew")

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

        ttk.Label(frame, text="Entrada").grid(row=1, column=0, sticky="nw", pady=(12, 0))
        mode_frame = ttk.Frame(frame)
        mode_frame.grid(row=1, column=1, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Radiobutton(
            mode_frame,
            text="Release ID",
            value="release",
            variable=self.input_mode_var,
            command=self._toggle_input_mode,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            mode_frame,
            text="Stories manuais",
            value="stories",
            variable=self.input_mode_var,
            command=self._toggle_input_mode,
        ).grid(row=0, column=1, sticky="w", padx=(16, 0))

        ttk.Label(frame, text="Release ID").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.release_entry = ttk.Entry(frame, textvariable=self.release_id_var)
        self.release_entry.grid(row=2, column=1, columnspan=2, sticky="ew", pady=(12, 0))

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

        actions = ttk.Frame(frame)
        actions.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(20, 0))
        for column in range(3):
            actions.columnconfigure(column, weight=1)
        ttk.Button(actions, text="Doctor", command=self._run_doctor).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(actions, text="Executar", command=self._run_equalization).grid(row=0, column=1, sticky="ew", padx=4)
        ttk.Button(actions, text="Retomar", command=self._resume_run).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        secondary = ttk.Frame(frame)
        secondary.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))
        for column in range(3):
            secondary.columnconfigure(column, weight=1)
        ttk.Button(secondary, text="Status", command=self._show_status).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(secondary, text="Abrir Ultimo Run", command=self._open_latest_run_folder).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(secondary, text="Limpar Saida", command=self._clear_output).grid(row=0, column=2, sticky="ew", padx=(8, 0))

        ttk.Label(
            frame,
            text="Fluxo sugerido: salvar configuracao Jira, rodar Doctor, executar a release e usar Retomar quando houver conflito.",
        ).grid(row=10, column=0, columnspan=3, sticky="w", pady=(18, 0))

        self._toggle_input_mode()
        return frame

    def _build_config_panel(self, parent: ttk.Frame) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text="Configuracao Jira", padding=16)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Arquivo de config").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, textvariable=self.config_path_var).grid(row=0, column=1, sticky="w", padx=(8, 0))

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
        ttk.Label(
            frame,
            text="Informe aqui o token real que a aplicacao deve usar para acessar o Jira.",
        ).grid(row=5, column=1, sticky="w", pady=(4, 0))

        ttk.Label(frame, text="Timeout (s)").grid(row=6, column=0, sticky="w", pady=(12, 0))
        ttk.Entry(frame, textvariable=self.timeout_var).grid(row=6, column=1, sticky="ew", pady=(12, 0), padx=(8, 0))

        ttk.Button(frame, text="Salvar Configuracao", command=self._save_jira_configuration).grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(18, 0)
        )

        ttk.Label(
            frame,
            text="Sugestoes uteis para o usuario final:\n"
            "- Executar a release direto pelo ID.\n"
            "- Ajustar as branches de origem e destino sem abrir terminal.\n"
            "- Abrir a pasta do ultimo run sem navegar na arvore.\n"
            "- Manter token e URL configurados na propria tela.\n"
            "- Usar Status/Retomar apos conflito sem abrir terminal.",
            justify="left",
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(18, 0))

        self._toggle_auth_mode()
        return frame

    def _select_repo(self) -> None:
        selected = filedialog.askdirectory(title="Selecione o repositorio Git")
        if selected:
            self.repo_var.set(selected)
            self._save_ui_state()

    def _toggle_input_mode(self) -> None:
        is_release = self.input_mode_var.get() == "release"
        self.release_entry.configure(state="normal" if is_release else "disabled")
        self.stories_entry.configure(state="disabled" if is_release else "normal")

    def _toggle_auth_mode(self) -> None:
        is_basic = self.auth_mode_var.get() == "basic"
        self.username_entry.configure(state="normal" if is_basic else "disabled")

    def _toggle_secret_visibility(self) -> None:
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

    def _run_equalization(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        source_ref, target_ref = self._require_refs()
        if not source_ref or not target_ref:
            return

        command = ["run", "--repo", repo, "--source-ref", source_ref, "--target-ref", target_ref]
        if self.input_mode_var.get() == "release":
            release_id = self.release_id_var.get().strip()
            if not release_id:
                messagebox.showerror("Campo obrigatorio", "Informe o Release ID.")
                return
            command.extend(["--release-id", release_id])
        else:
            stories = self.stories_var.get().strip()
            if not stories:
                messagebox.showerror("Campo obrigatorio", "Informe as stories manualmente.")
                return
            command.extend(["--stories", stories])
        if self.force_now_var.get():
            command.append("--force-now")

        self._save_ui_state()
        if not self._persist_configuration():
            return
        self._launch_cli(command, "Iniciando equalizacao...")

    def _resume_run(self) -> None:
        repo = self._require_repo()
        if not repo:
            return
        if not self._persist_configuration():
            return
        self._launch_cli(["resume", "--repo", repo], "Retomando execucao pausada...")

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

        manifest_paths = sorted(runs_root.glob("**/manifest.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        target = manifest_paths[0].parent if manifest_paths else runs_root
        os.startfile(str(target))

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
        self.input_mode_var.set(state.get("input_mode", "release"))
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
            "input_mode": self.input_mode_var.get().strip(),
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
