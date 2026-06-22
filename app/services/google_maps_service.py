"""Cliente Google Maps Platform (Places + Geocoding) — provider ``google_maps``.

Estratégia COMBINADA, pensada para esta base de pessoas físicas (telefone 100%
preenchido em E.164):

1) Reverse-lookup por TELEFONE (Places — *Find Place From Phone Number*):
   o ``phone_e164`` já está no formato exato que a API exige. Quando o número
   está cadastrado como contato de um ESTABELECIMENTO no Maps, devolve
   place_id + endereço + coordenadas + nome do local. O hit rate numa base de
   celulares pessoais é baixo — só casa autônomos/comércios cujo telefone é o
   contato do negócio —, mas o que casa traz geo e endereço estruturado.

2) Fallback por ENDEREÇO (Geocoding): se o telefone não casa, geocodifica o
   endereço que o lead JÁ tem (logradouro/CEP/cidade/UF) para preencher
   ``latitude``/``longitude`` e normalizar o endereço. Hit rate alto; complementa
   o ViaCEP (que dá endereço mas não coordenadas).

NÃO enriquece e-mail/LinkedIn — o Google Maps é diretório de LOCAIS, não de
pessoas. Cliente puro: NÃO escreve no banco; erros são reportados (não levantados),
para não derrubar os demais providers do lead.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

import httpx

from app.config import Settings
from app.core.http_client import request_with_retry
from app.core.normalize import clean_value
from app.core.rate_limiter import AsyncRateLimiter
from app.models.lead import Lead
from app.services.result import ProviderResult

# Tipo de address_component do Google -> coluna do banco.
# (administrative_area_level_1 usa short_name -> UF de 2 letras; o resto, long_name.)
_COMPONENT_MAP: dict[str, str] = {
    "street_number": "numero",
    "route": "endereco",
    "sublocality_level_1": "bairro",
    "sublocality": "bairro",
    "neighborhood": "bairro",
    "locality": "cidade",
    "administrative_area_level_2": "cidade",
    "administrative_area_level_1": "estado",
    "postal_code": "cep",
}

# Colunas que este provider PODE preencher (advisory p/ coverage.FIELD_SOURCES).
TARGET_COLUMNS: frozenset[str] = frozenset(
    {*_COMPONENT_MAP.values(), "latitude", "longitude", "observacoes"}
)


class GoogleMapsService:
    provider = "google_maps"

    def __init__(self, settings: Settings, rate_limiter: AsyncRateLimiter):
        self._settings = settings
        self._rate = rate_limiter

    # ---- API pública -----------------------------------------------------

    async def enrich(self, lead: Lead) -> ProviderResult:
        if not self._settings.google_maps_api_key:
            return ProviderResult(provider=self.provider, error="GOOGLE_MAPS_API_KEY ausente")

        last: ProviderResult | None = None
        # 1) Telefone (a chave mais forte: 100% da base tem phone_e164).
        if lead.phone_e164:
            last = await self._lookup_by_phone(lead.phone_e164)
            if last.matched:
                return last
            # Sem acesso (chave/billing/API): propaga p/ o disjuntor do orquestrador.
            if last.http_status in (401, 403):
                return last

        # 2) Fallback por endereço existente.
        address, cep = self._build_address(lead)
        if address:
            return await self._geocode(address, cep)

        return last or ProviderResult(
            provider=self.provider, matched=False, error="sem telefone nem endereço para consulta"
        )

    # ---- Passo 1: reverse-lookup por telefone ----------------------------

    async def _lookup_by_phone(self, phone: str) -> ProviderResult:
        await self._rate.acquire()
        url = f"{self._base()}/place/findplacefromtext/json"
        params = {
            "input": phone,
            "inputtype": "phonenumber",
            "fields": "place_id,name,geometry,formatted_address",
            "key": self._settings.google_maps_api_key,
        }
        data = await self._get(url, params)
        if isinstance(data, ProviderResult):
            return data

        status = data.get("status")
        if status == "ZERO_RESULTS":
            return ProviderResult(provider=self.provider, http_status=200, matched=False)
        if status != "OK":
            return self._status_error(status, data)

        candidates = data.get("candidates") or []
        if not candidates:
            return ProviderResult(provider=self.provider, http_status=200, matched=False)

        place = candidates[0]
        candidate: dict = self._geo_from(place.get("geometry"))
        place_id = place.get("place_id")
        if self._settings.google_maps_place_details and place_id:
            detailed = await self._place_details(place_id)
            # Componentes/endereço do details têm precedência sobre o geo bruto.
            candidate = {**candidate, **detailed}

        name = clean_value(place.get("name"))
        if name:
            # Sinal de enriquecimento: o número é o contato de um negócio.
            candidate.setdefault("observacoes", f"Google Maps: {name}")

        return ProviderResult(
            provider=self.provider,
            http_status=200,
            matched=True,
            candidate=candidate,
            payload={"source": "phone", "name": name, "place_id": place_id},
        )

    async def _place_details(self, place_id: str) -> dict:
        """Busca address_components + geo de um place_id. Best-effort: erro -> {}."""
        await self._rate.acquire()
        url = f"{self._base()}/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "address_component,geometry,name",
            "key": self._settings.google_maps_api_key,
        }
        data = await self._get(url, params)
        if isinstance(data, ProviderResult) or data.get("status") != "OK":
            return {}
        result = data.get("result") or {}
        candidate = self._parse_components(result.get("address_components") or [])
        candidate.update(self._geo_from(result.get("geometry")))
        return candidate

    # ---- Passo 2: geocoding do endereço existente ------------------------

    async def _geocode(self, address: str, cep: str | None) -> ProviderResult:
        await self._rate.acquire()
        url = f"{self._base()}/geocode/json"
        components = "country:BR"
        if cep:
            components += f"|postal_code:{cep}"
        params = {
            "address": address,
            "region": "br",
            "components": components,
            "key": self._settings.google_maps_api_key,
        }
        data = await self._get(url, params)
        if isinstance(data, ProviderResult):
            return data

        status = data.get("status")
        if status == "ZERO_RESULTS":
            return ProviderResult(provider=self.provider, http_status=200, matched=False)
        if status != "OK":
            return self._status_error(status, data)

        results = data.get("results") or []
        if not results:
            return ProviderResult(provider=self.provider, http_status=200, matched=False)

        result = results[0]
        candidate = self._parse_components(result.get("address_components") or [])
        candidate.update(self._geo_from(result.get("geometry")))
        return ProviderResult(
            provider=self.provider,
            http_status=200,
            matched=bool(candidate),
            candidate=candidate,
            payload={"source": "geocode"},
        )

    # ---- Helpers ---------------------------------------------------------

    def _base(self) -> str:
        return self._settings.google_maps_base_url.rstrip("/")

    async def _get(self, url: str, params: dict) -> dict | ProviderResult:
        """GET com retry; devolve o JSON ou um ProviderResult de erro (rede/HTTP)."""
        try:
            resp = await request_with_retry("GET", url, params=params)
        except httpx.HTTPError as exc:
            return ProviderResult(provider=self.provider, error=str(exc))
        if resp.status_code != 200:
            return ProviderResult(
                provider=self.provider,
                http_status=resp.status_code,
                error=f"HTTP {resp.status_code}",
            )
        return resp.json() or {}

    @staticmethod
    def _geo_from(geometry: dict | None) -> dict:
        loc = (geometry or {}).get("location") or {}
        out: dict = {}
        for src, col in (("lat", "latitude"), ("lng", "longitude")):
            value = loc.get(src)
            if value is None:
                continue
            try:
                out[col] = Decimal(str(value))
            except (InvalidOperation, ValueError):
                continue
        return out

    @staticmethod
    def _parse_components(components: list[dict]) -> dict:
        """address_components do Google -> colunas do banco (primeiro tipo casado vence)."""
        out: dict = {}
        for comp in components:
            for type_ in comp.get("types") or []:
                col = _COMPONENT_MAP.get(type_)
                if not col or col in out:
                    continue
                use_short = type_ == "administrative_area_level_1"
                value = clean_value(comp.get("short_name" if use_short else "long_name"))
                if not value:
                    continue
                if col == "cep":
                    digits = re.sub(r"\D", "", value)
                    if len(digits) != 8:
                        continue
                    value = digits
                out[col] = value
        return out

    @staticmethod
    def _build_address(lead: Lead) -> tuple[str | None, str | None]:
        """Monta a query de geocoding a partir do que o lead JÁ tem.

        Exige cidade OU CEP (só UF/logradouro geocodifica mal). Devolve
        (endereço, cep_em_8_dígitos) — cep usado como filtro de componente.
        """
        cep = clean_value(lead.cep)
        cep_digits = re.sub(r"\D", "", cep) if cep else ""
        cep_digits = cep_digits if len(cep_digits) == 8 else None

        if not clean_value(lead.cidade) and not cep_digits:
            return None, None

        parts = [
            clean_value(lead.endereco),
            clean_value(lead.numero),
            clean_value(lead.bairro),
            clean_value(lead.cidade),
            clean_value(lead.estado),
            cep_digits,
        ]
        address = ", ".join(p for p in parts if p)
        if not address:
            return None, None
        return f"{address}, Brasil", cep_digits

    def _status_error(self, status: str | None, data: dict) -> ProviderResult:
        """Mapeia ``status`` != OK da API para ProviderResult de erro.

        REQUEST_DENIED (chave inválida / API não habilitada / billing off) vira
        403 para o orquestrador ABRIR o disjuntor e parar de chamar o Google.
        """
        message = data.get("error_message") or status or "erro desconhecido"
        http: int | None = None
        hint = ""
        if status == "REQUEST_DENIED":
            http = 403
            hint = (
                " — chave inválida, billing desativado ou API "
                "(Places/Geocoding) não habilitada no Google Cloud"
            )
        elif status == "OVER_QUERY_LIMIT":
            http = 429
        return ProviderResult(
            provider=self.provider,
            http_status=http,
            matched=False,
            error=f"{status}: {message}{hint}",
        )
