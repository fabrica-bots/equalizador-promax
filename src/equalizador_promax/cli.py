from __future__ import annotations

import argparse
from pathlib import Path

from equalizador_promax.config import load_config
from equalizador_promax.errors import EqualizadorError
from equalizador_promax.gui import launch_gui
from equalizador_promax.orchestrator import EqualizadorService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="equalizador-promax")
    parser.add_argument("--config", type=Path, help="Caminho opcional para config.toml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gui", help="Abre a interface desktop.")

    doctor_parser = subparsers.add_parser("doctor", help="Valida ambiente e dependencias.")
    doctor_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")

    run_parser = subparsers.add_parser("run", help="Inicia uma equalizacao.")
    run_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    run_input_group = run_parser.add_mutually_exclusive_group(required=True)
    run_input_group.add_argument(
        "--stories",
        help="Lista de stories separadas por virgula. Ex.: SQCRM-6805,SQCRM-6806",
    )
    run_input_group.add_argument(
        "--release-id",
        help="Identificador numerico da versao/release no Jira. Ex.: 59571",
    )
    run_parser.add_argument(
        "--force-new",
        "--force-now",
        dest="force_new",
        action="store_true",
        help="Ignora execucao aberta com mesmo fingerprint.",
    )

    resume_parser = subparsers.add_parser("resume", help="Retoma uma execucao pausada.")
    resume_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    resume_parser.add_argument("--run-id", help="Identificador da execucao pausada.")

    status_parser = subparsers.add_parser("status", help="Exibe o status da ultima execucao.")
    status_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    status_parser.add_argument("--run-id", help="Identificador da execucao.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "gui":
        launch_gui()
        return 0

    service = EqualizadorService(load_config(args.config))

    try:
        if args.command == "doctor":
            checks = service.doctor(args.repo)
            for check in checks:
                marker = "[OK]" if check.ok else "[ERRO]"
                print(f"{marker} {check.name}: {check.details}")
            return 0 if all(check.ok for check in checks) else 1

        if args.command == "run":
            release_name = None
            if args.release_id:
                story_keys, release_name = service.resolve_release(args.release_id)
            else:
                story_keys = service.resolve_story_keys(
                    story_keys=[part.strip() for part in args.stories.split(",")] if args.stories else None,
                )

            manifest = service.run(
                args.repo,
                story_keys,
                force_new=args.force_new,
                release_id=args.release_id,
                release_name=release_name,
            )
            print(f"Run {manifest.run_id} finalized with status {manifest.status}.")
            return 0

        if args.command == "resume":
            manifest = service.resume(args.repo, args.run_id)
            print(f"Run {manifest.run_id} resumed and finished with status {manifest.status}.")
            return 0

        if args.command == "status":
            print(service.status(args.repo, args.run_id))
            return 0

        parser.error(f"Unknown command {args.command}")
    except EqualizadorError as exc:
        print(f"ERROR: {exc}")
        return exc.exit_code
    except Exception as exc:  # pragma: no cover - defensive fallback
        print(f"ERROR: {exc}")
        return 1

    return 0
