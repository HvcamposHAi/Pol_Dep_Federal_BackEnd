"""Orquestrador do enriquecimento — loop principal reutilizado por API e CLI.

- Rodadas de priorização (R1: leads com e-mail; R2: sem e-mail) para Apollo.
- ViaCEP aplicado em todas as rodadas (gratuito).
- Resume automático: cada lead recebe um status terminal (enriched/skipped/failed),
  saindo do conjunto ``pending`` — reiniciar o run continua de onde parou.
- Checkpoint de contadores em ``enrichment_runs`` a cada lote (commit).
- Honra cancelamento (status do run vira ``canceled``).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.merge import fill_only_empty
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.repositories import enrichment_repo, lead_repo
from app.services.apollo_service import ApolloEnrichmentService
from app.services.result import ProviderResult
from app.services.viacep_service import ViaCepService


class EnrichmentOrchestrator:
    def __init__(self, settings: Settings, sessionmaker: async_sessionmaker[AsyncSession]):
        self._settings = settings
        self._sm = sessionmaker
        rpm = settings.apollo_rate_limit
        self._apollo = ApolloEnrichmentService(settings, AsyncRateLimiter.from_rpm(rpm))
        self._viacep = ViaCepService(
            settings, AsyncRateLimiter.from_rpm(settings.viacep_rate_limit)
        )

    @staticmethod
    def _rounds(provider_scope: list[str]) -> list[tuple[int, bool | None]]:
        """(numero_da_rodada, with_email). Sem Apollo -> rodada única (None)."""
        if "apollo" in provider_scope:
            return [(1, True), (2, False)]
        return [(1, None)]

    async def run(
        self,
        run_id: uuid.UUID,
        *,
        dry_run: bool = False,
        filters: dict | None = None,
    ) -> None:
        filters = filters or {}
        cidade = filters.get("cidade")
        estado = filters.get("estado")
        limit = filters.get("limit")

        async with self._sm() as session:
            run = await enrichment_repo.get_run(session, run_id)
            if run is None:
                raise ValueError(f"run {run_id} inexistente")
            if run.status in ("completed", "canceled"):
                return
            run.status = "running"
            if run.started_at is None:
                run.started_at = datetime.now(UTC)
            if run.total_targets == 0:
                run.total_targets = await lead_repo.count_targets(
                    session, cidade=cidade, estado=estado
                )
            scope = list(run.provider_scope)
            await session.commit()

        if dry_run:
            await self._dry_run(run_id, scope, cidade, estado, limit)
            return

        remaining = limit
        batch = self._settings.enrich_batch_size
        for round_number, with_email in self._rounds(scope):
            while True:
                if remaining is not None and remaining <= 0:
                    break
                fetch = batch if remaining is None else min(batch, remaining)
                async with self._sm() as session:
                    run = await enrichment_repo.get_run(session, run_id)
                    if run is None or run.status == "canceled":
                        return
                    leads = await lead_repo.select_targets(
                        session,
                        with_email=with_email,
                        after_id=None,
                        limit=fetch,
                        cidade=cidade,
                        estado=estado,
                    )
                    if not leads:
                        break
                    for lead in leads:
                        await self._process_lead(session, run_id, lead, scope, run)
                        run.processed_count += 1
                        run.last_processed_lead_id = lead.id
                        if remaining is not None:
                            remaining -= 1
                    run.current_round = round_number
                    await session.commit()

        async with self._sm() as session:
            run = await enrichment_repo.get_run(session, run_id)
            if run and run.status != "canceled":
                run.status = "completed"
                run.finished_at = datetime.now(UTC)
                await session.commit()

    async def _process_lead(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        lead: Lead,
        scope: list[str],
        run,
    ) -> None:
        filled_total: list[str] = []
        apollo_matched: bool | None = None
        try:
            if "viacep" in scope:
                viacep_result = await self._viacep.enrich(lead)
                await self._apply(session, run_id, lead, viacep_result, filled_total)
            if "apollo" in scope:
                result = await self._apollo.enrich(lead)
                if result.matched:
                    apollo_matched = True
                    run.matched_count += 1
                elif result.error is None:
                    apollo_matched = False
                await self._apply(session, run_id, lead, result, filled_total)

            status = "enriched" if (filled_total or apollo_matched) else "skipped"
            await lead_repo.patch_fields(
                session,
                lead,
                patch={},
                provenance={},
                provider="apollo" if "apollo" in scope else None,
                apollo_matched=apollo_matched,
                status=status,
            )
        except Exception as exc:  # noqa: BLE001 - registra falha e segue (status terminal)
            run.error_count += 1
            lead.enrichment_status = "failed"
            await enrichment_repo.log_event(
                session,
                run_id=run_id,
                lead_id=lead.id,
                provider="orchestrator",
                level="error",
                event_type="http_error",
                message=str(exc),
            )

    async def _apply(
        self,
        session: AsyncSession,
        run_id: uuid.UUID,
        lead: Lead,
        result: ProviderResult,
        filled_total: list[str],
    ) -> None:
        """Aplica um ProviderResult ao lead (fill-only-empty) e registra evento."""
        if result.error:
            await enrichment_repo.log_event(
                session,
                run_id=run_id,
                lead_id=lead.id,
                provider=result.provider,
                level="warn",
                event_type="http_error",
                message=result.error,
                http_status=result.http_status,
            )
            return

        if not result.candidate:
            await enrichment_repo.log_event(
                session,
                run_id=run_id,
                lead_id=lead.id,
                provider=result.provider,
                level="info",
                event_type="no_match" if not result.matched else "matched",
                http_status=result.http_status,
            )
            return

        current = {col: getattr(lead, col) for col in result.candidate}
        merge = fill_only_empty(current, result.candidate, result.provider)
        await lead_repo.patch_fields(
            session,
            lead,
            patch=merge.patch,
            provenance=merge.provenance,
            provider=result.provider,
            apollo_matched=True if result.provider == "apollo" and result.matched else None,
        )
        filled_total.extend(merge.fields_filled)
        await enrichment_repo.log_event(
            session,
            run_id=run_id,
            lead_id=lead.id,
            provider=result.provider,
            level="info",
            event_type="merged" if merge.fields_filled else "matched",
            fields_filled=merge.fields_filled or None,
            http_status=result.http_status,
        )

    async def _dry_run(
        self,
        run_id: uuid.UUID,
        scope: list[str],
        cidade: str | None,
        estado: str | None,
        limit: int | None,
    ) -> None:
        """Simula a seleção sem chamar APIs externas nem gravar campos."""
        async with self._sm() as session:
            leads = await lead_repo.select_targets(
                session,
                with_email=None,
                after_id=None,
                limit=limit or 50,
                cidade=cidade,
                estado=estado,
            )
            for lead in leads:
                await enrichment_repo.log_event(
                    session,
                    run_id=run_id,
                    lead_id=lead.id,
                    provider="orchestrator",
                    level="info",
                    event_type="skipped",
                    message=f"dry_run: candidato a enriquecimento (providers={scope})",
                )
            run = await enrichment_repo.get_run(session, run_id)
            if run:
                run.status = "completed"
                run.processed_count = len(leads)
                run.finished_at = datetime.now(UTC)
            await session.commit()
