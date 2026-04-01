from __future__ import annotations

import argparse
from pathlib import Path

from equalizador_promax.config import load_config
from equalizador_promax.errors import EqualizadorError
from equalizador_promax.gui import launch_gui
from equalizador_promax.orchestrator import EqualizadorService


def _split_csv_argument(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="equalizador-promax")
    parser.add_argument("--config", type=Path, help="Caminho opcional para config.toml")

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("gui", help="Abre a interface desktop.")

    doctor_parser = subparsers.add_parser("doctor", help="Valida ambiente e dependencias.")
    doctor_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    doctor_parser.add_argument(
        "--source-ref",
        default="origin/develop",
        help="Ref/branche origem para buscar merges e commits. Default: origin/develop",
    )
    doctor_parser.add_argument(
        "--target-ref",
        default="origin/quality",
        help="Ref/branche destino usada como base da equalizacao. Default: origin/quality",
    )

    run_parser = subparsers.add_parser("run", help="Inicia uma equalizacao.")
    run_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    run_parser.add_argument(
        "--source-ref",
        default="origin/develop",
        help="Ref/branche origem para buscar merges e commits. Default: origin/develop",
    )
    run_parser.add_argument(
        "--target-ref",
        default="origin/quality",
        help="Ref/branche destino usada como base da equalizacao. Default: origin/quality",
    )
    run_parser.add_argument(
        "--stories",
        help="Lista de stories separadas por virgula. Ex.: SQCRM-6805,SQCRM-6806",
    )
    run_parser.add_argument(
        "--release-id",
        help="Lista de IDs numericos de versao/release separada por virgula. Ex.: 59571,59572",
    )
    run_parser.add_argument(
        "--force-new",
        "--force-now",
        dest="force_new",
        action="store_true",
        help="Ignora execucao aberta com mesmo fingerprint.",
    )

    jira_parser = subparsers.add_parser("fetch-jira", help="Busca stories e subtasks no Jira e salva o snapshot local.")
    jira_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    jira_parser.add_argument(
        "--source-ref",
        default="origin/develop",
        help="Ref/branche origem para buscar merges e commits. Default: origin/develop",
    )
    jira_parser.add_argument(
        "--target-ref",
        default="origin/quality",
        help="Ref/branche destino usada como base da equalizacao. Default: origin/quality",
    )
    jira_parser.add_argument(
        "--stories",
        help="Lista de stories separadas por virgula. Ex.: SQCRM-6805,SQCRM-6806",
    )
    jira_parser.add_argument(
        "--release-id",
        help="Lista de IDs numericos de versao/release separada por virgula. Ex.: 59571,59572",
    )
    jira_parser.add_argument(
        "--force-new",
        "--force-now",
        dest="force_new",
        action="store_true",
        help="Ignora execucao aberta com mesmo fingerprint.",
    )

    commits_parser = subparsers.add_parser("fetch-commits", help="Busca commits usando o ultimo snapshot Jira.")
    commits_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    commits_parser.add_argument("--run-id", help="Identificador da execucao.")

    apply_parser = subparsers.add_parser("apply-cherry-picks", help="Aplica cherry-picks usando a lista de commits salva.")
    apply_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    apply_parser.add_argument("--run-id", help="Identificador da execucao.")

    discard_parser = subparsers.add_parser("discard-branch", help="Descarta a branch atual da equalizacao e volta para a origem.")
    discard_parser.add_argument("--repo", type=Path, required=True, help="Caminho do repositorio Git local.")
    discard_parser.add_argument("--run-id", help="Identificador da execucao.")

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
            checks = service.doctor(args.repo, source_ref=args.source_ref, target_ref=args.target_ref)
            for check in checks:
                marker = "[OK]" if check.ok else "[ERRO]"
                print(f"{marker} {check.name}: {check.details}")
            return 0 if all(check.ok for check in checks) else 1

        if args.command == "run":
            manifest = service.run(
                args.repo,
                *service.resolve_inputs(
                    release_ids=_split_csv_argument(args.release_id),
                    story_keys=_split_csv_argument(args.stories),
                ),
                force_new=args.force_new,
                source_ref=args.source_ref,
                target_ref=args.target_ref,
            )
            print(f"Run {manifest.run_id} finalized with status {manifest.status}.")
            return 0

        if args.command == "fetch-jira":
            manifest = service.capture_jira_snapshot(
                args.repo,
                *service.resolve_inputs(
                    release_ids=_split_csv_argument(args.release_id),
                    story_keys=_split_csv_argument(args.stories),
                ),
                force_new=args.force_new,
                source_ref=args.source_ref,
                target_ref=args.target_ref,
            )
            print(f"Run {manifest.run_id} updated with status {manifest.status}.")
            return 0

        if args.command == "fetch-commits":
            manifest = service.fetch_commits(args.repo, args.run_id)
            print(f"Run {manifest.run_id} updated with status {manifest.status}.")
            return 0

        if args.command == "apply-cherry-picks":
            manifest = service.apply_cherry_picks(args.repo, args.run_id)
            print(f"Run {manifest.run_id} finalized with status {manifest.status}.")
            return 0

        if args.command == "discard-branch":
            manifest = service.discard_current_branch(args.repo, args.run_id)
            print(f"Run {manifest.run_id} updated with status {manifest.status}.")
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
