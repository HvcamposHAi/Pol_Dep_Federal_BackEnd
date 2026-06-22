"""Orquestrador do enriquecimento — loop principal reutilizado por API e CLI.

- Rodadas de priorização (R1: leads com e-mail; R2: sem e-mail) para Apollo.
- ViaCEP aplicado em todas as rodadas (gratuito).
- Resume automático: cada lead recebe um status terminal (enriched/skipped/failed),
  saindo do conjunto ``pending`` — reiniciar o run continua de onde parou.
- Checkpoint de contadores em ``enrichment_runs`` a cada lote (commit).
- Honra cancelamento (status do run vira ``canceled``).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.merge import fill_only_empty
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.repositories import enrichment_repo, lead_repo
from app.services.apollo_service import ApolloEnrichmentService
from app.services.google_maps_service import GoogleMapsService
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
        self._google = GoogleMapsService(
            settings, AsyncRateLimiter.from_rpm(settings.google_maps_rate_limit)
        )
        # Disjuntor: ao primeiro 401/403 do Apollo (chave/plano sem acesso), para de
        # chamar o Apollo no resto da execução (evita 403 em toda a base + rate limit).
        self._apollo_blocked = False
        # Mesmo disjuntor p/ o Google Maps (REQUEST_DENIED -> chave/billing/API off).
        self._google_blocked = False

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
        """Executa o run. QUALQUER exceção não tratada marca o run como ``failed``
        (status terminal) antes de propagar — assim a UI nunca fica presa em
        ``running`` por causa de uma task que morreu silenciosamente."""
        try:
            await self._run(run_id, dry_run=dry_run, filters=filters)
        except asyncio.CancelledError:
            # Encerramento cooperativo (shutdown/reload): não vira "failed".
            raise
        except Exception as exc:  # noqa: BLE001 - garante status terminal e re-propaga
            await self._mark_failed(run_id, exc)
            raise

    async def _mark_failed(self, run_id: uuid.UUID, exc: BaseException) -> None:
        """Marca o run como ``failed`` (se ainda não terminal) e registra o motivo."""
        try:
            async with self._sm() as session:
                run = await enrichment_repo.get_run(session, run_id)
                if run is None or run.status in ("completed", "canceled", "failed"):
                    return
                run.status = "failed"
                run.finished_at = datetime.now(UTC)
                await enrichment_repo.log_event(
                    session,
                    run_id=run_id,
                    lead_id=None,
                    provider="orchestrator",
                    level="error",
                    event_type="run_failed",
                    message=f"Execução interrompida: {exc}"[:480],
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - best-effort; não mascara o erro original
            pass

    async def _run(
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
            # Apollo exige chave válida. Sem chave, pula o Apollo por completo — evita
            # 403 em todos os leads e a espera inútil do rate limit (46/min).
            if "apollo" in scope and not self._settings.apollo_api_key:
                scope = [p for p in scope if p != "apollo"]
                await enrichment_repo.log_event(
                    session,
                    run_id=run_id,
                    lead_id=None,
                    provider="orchestrator",
                    level="warn",
                    event_type="skipped",
                    message=(
                        "Apollo ignorado: APOLLO_API_KEY não configurada "
                        "(defina em Configurações › Integrações)."
                    ),
                )
            # Google Maps também exige chave. Sem chave, pula por completo.
            if "google_maps" in scope and not self._settings.google_maps_api_key:
                scope = [p for p in scope if p != "google_maps"]
                await enrichment_repo.log_event(
                    session,
                    run_id=run_id,
                    lead_id=None,
                    provider="orchestrator",
                    level="warn",
                    event_type="skipped",
                    message=(
                        "Google Maps ignorado: GOOGLE_MAPS_API_KEY não configurada "
                        "(defina em Configurações › Integrações)."
                    ),
                )
            await session.commit()

        if dry_run:
            await self._dry_run(run_id, scope, cidade, estado, limit)
            return

        remaining = limit
        batch = self._settings.enrich_run_batch_size
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
                        run.current_round = round_number
                        # Heartbeat por lead: prova de vida lida pelo watchdog da API
                        # (um run cujo processo morreu para de bater e é marcado failed).
                        run.checkpoint = {"heartbeat": datetime.now(UTC).isoformat()}
                        if remaining is not None:
                            remaining -= 1
                        # Commit por lead: transação curta (não segura a conexão do
                        # pool durante as chamadas HTTP do lote) e progresso/parcial
                        # sempre persistido — robusto a quedas no meio do lote.
                        await session.commit()
                        # Honra cancelamento DENTRO do lote (custo: 1 SELECT por lead).
                        await session.refresh(run, ["status"])
                        if run.status == "canceled":
                            return

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
        google_matched = False
        reasons: list[str] = []  # motivos quando negativo
        apollo_ran = False
        try:
            if "viacep" in scope:
                viacep_result = await self._viacep.enrich(lead)
                await self._apply(session, run_id, lead, viacep_result, filled_total)
                if viacep_result.error:
                    reasons.append(f"ViaCEP: {viacep_result.error}")
                elif not viacep_result.candidate:
                    reasons.append("ViaCEP: sem dados")
            if "google_maps" in scope and not self._google_blocked:
                google_result = await self._google.enrich(lead)
                # Sem acesso (REQUEST_DENIED -> 403): desabilita p/ o resto da execução.
                if google_result.http_status in (401, 403):
                    self._google_blocked = True
                    await enrichment_repo.log_event(
                        session,
                        run_id=run_id,
                        lead_id=None,
                        provider="orchestrator",
                        level="warn",
                        event_type="skipped",
                        message=(
                            f"Google Maps desabilitado nesta execução: {google_result.error}. "
                            "Revise a chave/billing em Configurações › Integrações."
                        ),
                    )
                if google_result.matched:
                    google_matched = True
                await self._apply(session, run_id, lead, google_result, filled_total)
                if google_result.error:
                    reasons.append(f"Google Maps: {google_result.error}")
                elif not google_result.matched:
                    reasons.append("Google Maps: sem correspondência")
            elif "google_maps" in scope and self._google_blocked:
                reasons.append("Google Maps: desabilitado (sem acesso)")
            if "apollo" in scope and not self._apollo_blocked:
                apollo_ran = True
                result = await self._apollo.enrich(lead)
                # Sem acesso (401/403): desabilita o Apollo para o resto da execução.
                if result.http_status in (401, 403):
                    self._apollo_blocked = True
                    await enrichment_repo.log_event(
                        session,
                        run_id=run_id,
                        lead_id=None,
                        provider="orchestrator",
                        level="warn",
                        event_type="skipped",
                        message=(
                            f"Apollo desabilitado nesta execução: {result.error}. "
                            "Revise a chave/plano em Configurações › Integrações."
                        ),
                    )
                if result.matched:
                    apollo_matched = True
                    run.matched_count += 1
                elif result.error is None:
                    apollo_matched = False
                await self._apply(session, run_id, lead, result, filled_total)
                if result.error:
                    reasons.append(f"Apollo: {result.error}")
                elif not result.matched:
                    reasons.append("Apollo: sem correspondência")
            elif "apollo" in scope and self._apollo_blocked:
                reasons.append("Apollo: desabilitado (sem acesso)")

            # Resultado: positivo = match (Apollo/Google) OU algum campo novo preenchido.
            positivo = bool(apollo_matched or google_matched or filled_total)
            if positivo:
                status = "enriched"
                parts: list[str] = []
                if filled_total:
                    parts.append("campos: " + ", ".join(dict.fromkeys(filled_total)))
                if not filled_total and apollo_matched:
                    parts.append("match Apollo (sem campo novo)")
                if not filled_total and google_matched:
                    parts.append("match Google Maps (sem campo novo)")
                note = "; ".join(parts) or "match"
            else:
                status = "skipped"
                note = "; ".join(reasons) or "sem correspondência"

            await lead_repo.patch_fields(
                session,
                lead,
                patch={},
                provenance={},
                provider="apollo" if apollo_ran else None,
                apollo_matched=apollo_matched,
                status=status,
                note=note,
            )
        except Exception as exc:  # noqa: BLE001 - registra falha e segue (status terminal)
            run.error_count += 1
            lead.enrichment_status = "failed"
            lead.enrichment_note = f"erro: {exc}"[:480]
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
