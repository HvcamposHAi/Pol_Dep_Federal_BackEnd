"""CLI do enriquecimento — mesmo orquestrador da API, processo dedicado.

Exemplos:
    python -m app.cli enrich --new                 # cria um run e executa
    python -m app.cli enrich --run-id <uuid>       # executa/retoma um run existente
    python -m app.cli enrich --new --dry-run --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import uuid

from app.config import get_settings
from app.core.http_client import close_client, init_client
from app.db.session import dispose_engine, get_sessionmaker
from app.repositories import enrichment_repo
from app.services.enrichment_orchestrator import EnrichmentOrchestrator


async def _run_enrich(args: argparse.Namespace) -> None:
    settings = get_settings()
    if args.rate_limit:
        settings.apollo_rate_limit = args.rate_limit
    sm = get_sessionmaker()
    init_client()

    providers = ["viacep"] if args.viacep_only else ["viacep", "apollo"]
    filters = {"limit": args.limit}

    try:
        if args.new:
            async with sm() as session:
                run = await enrichment_repo.create_run(
                    session, provider_scope=providers, params={"filters": filters}
                )
                await session.commit()
                run_id = run.id
            print(f"run criado: {run_id}")
        else:
            run_id = uuid.UUID(args.run_id)

        orchestrator = EnrichmentOrchestrator(settings, sm)
        await orchestrator.run(run_id, dry_run=args.dry_run, filters=filters)

        async with sm() as session:
            run = await enrichment_repo.get_run(session, run_id)
            if run:
                print(
                    f"status={run.status} processados={run.processed_count}/"
                    f"{run.total_targets} matches={run.matched_count} erros={run.error_count}"
                )
    finally:
        await close_client()
        await dispose_engine()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquecimento de leads (Apollo + ViaCEP)")
    sub = parser.add_subparsers(dest="command", required=True)

    enrich = sub.add_parser("enrich", help="executa um run de enriquecimento")
    group = enrich.add_mutually_exclusive_group(required=True)
    group.add_argument("--new", action="store_true", help="cria um novo run e executa")
    group.add_argument("--run-id", help="UUID de um run existente (executa/retoma)")
    enrich.add_argument("--dry-run", action="store_true", help="simula sem chamar APIs/gravar")
    enrich.add_argument("--limit", type=int, default=None, help="máximo de leads a processar")
    enrich.add_argument("--rate-limit", type=int, default=None, help="req/min Apollo (override)")
    enrich.add_argument(
        "--viacep-only", action="store_true", help="só ViaCEP (sem custo Apollo)"
    )

    args = parser.parse_args()
    if args.command == "enrich":
        asyncio.run(_run_enrich(args))


if __name__ == "__main__":
    main()
