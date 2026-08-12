#
# ABOUT
# AI-powered green bean data extractor for TilauScope — scrapes a product URL and
# extracts structured GreenBean data via submit_bean_extract() / aw.tilau_ai_service.
# LICENSE
# This file is part of TilauScope, a fork of Artisan Roaster Scope.
# TilauScope is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option) any
# later version. It is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero General Public License
# for more details. You should have received a copy of the GNU Affero General
# Public License along with this program. If not, see
# <https://www.gnu.org/licenses/>.


# AUTHOR
# TiLau 2026
# -*- coding: utf-8 -*-


from __future__ import annotations

import json
import logging
import re
from typing import Final, TYPE_CHECKING
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from instructor.auto_client import from_provider
from pydantic import BaseModel, Field

from tilauscope.tilauscope_types import GreenBean
from tilauscope.ai_support import TilauAIConfig
import instructor as _instructor
import openai as _openai


def _get_wheel_notes() -> list[str]:
    """Return all flavour note labels from the TilauScope flavour wheel, sorted."""
    try:
        from tilauscope.tilau_wheel import FLAVOR_WHEEL_DATA  # noqa: PLC0415
        return sorted({
            note
            for cat in FLAVOR_WHEEL_DATA.values()
            for grp in cat["groups"].values()
            for sub in grp["subgroups"].values()
            for note in sub["notes"]
        })
    except Exception:
        return []
from tilauscope.ai_service import TilauAIService, AITask, _CancelToken

if TYPE_CHECKING:
    from collections.abc import Callable

_log: Final[logging.Logger] = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pydantic schema for the extracted bean data
# ─────────────────────────────────────────────────────────────────────────────

class GreenBeanSchema(BaseModel):
    name:          str   = Field("", description="The name of the green beans")
    farm:          str   = Field("", description="The farm name")
    country:       str   = Field("", description="The country of origin")
    supplier:      str   = Field("", description="The supplier name")
    category:      str   = Field("", description="The category of the green beans")
    process:       str   = Field("", description="The processing method")
    crop:          int   = Field(0,   description="The crop year")
    density:       float = Field(0.0, description="Density in grams per liter")
    last_humidity: float = Field(0.0, description="Humidity measurement")
    water_activity:float = Field(0.0, description="Water activity")
    altitude:      int   = Field(0,   description="Average altitude in meters")
    species:       str   = Field("", description="Bean species")
    varieties:     str   = Field("", description="Bean varieties")
    flavour_notes: str   = Field("", description="Flavour notes")
    sca:           float = Field(0.0, description="SCA rating")
    is_blend:      bool  = Field(False, description="Whether the beans are a blend")
    bean1_ratio:   float = Field(0.0, description="Ratio 1-100 of first bean or 100 if single origin")
    bean2_name:    str   = Field("", description="Name of second bean in blend")
    bean2_ratio:   float = Field(0.0, description="Ratio of second bean")
    bean3_name:    str   = Field("", description="Name of third bean in blend")
    bean3_ratio:   float = Field(0.0, description="Ratio of third bean")
    tips:          str   = Field("", description="Roasting tips from supplier")


# ─────────────────────────────────────────────────────────────────────────────
# Scraping helpers  –  static-site optimised, no headless browser
# ─────────────────────────────────────────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_MIN_TEXT_LENGTH = 300  # chars — if below, page is likely JS-only


def _extract_json_ld(soup: BeautifulSoup) -> str:
    """Extract all JSON-LD blocks. Marketplace sites embed product data here."""
    results: list[str] = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            obj = json.loads(tag.string or "")
            results.append(json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass
    return "\n".join(results)


def _extract_meta(soup: BeautifulSoup) -> str:
    """Extract Open Graph and standard meta tags that often hold product info."""
    lines: list[str] = []
    for tag in soup.find_all("meta"):
        name    = tag.get("property") or tag.get("name") or ""
        content = tag.get("content") or ""
        if name and content:
            lines.append(f"{name}: {content}")
    return "\n".join(lines)


def _extract_microdata(soup: BeautifulSoup) -> str:
    """Extract itemprop microdata (schema.org Product / Offer etc.)."""
    lines: list[str] = []
    for tag in soup.find_all(itemprop=True):
        prop  = tag.get("itemprop", "")
        value = tag.get("content") or tag.get_text(strip=True)
        if prop and value:
            lines.append(f"{prop}: {value[:300]}")  # cap per field
    return "\n".join(lines)


def _extract_product_sections(soup: BeautifulSoup) -> str:
    """
    Heuristic extraction of product-description sections.
    Targets common class/id patterns used by Shopify, WooCommerce, PrestaShop,
    and custom roaster sites.
    """
    CANDIDATE_SELECTORS = [
        # Generic semantic
        "main", "article",
        # Product description zones
        "[class*='product-description']",
        "[class*='product-detail']",
        "[class*='product__description']",
        "[class*='product-info']",
        "[class*='product-content']",
        "[class*='roast-detail']",
        "[class*='bean-detail']",
        "[class*='coffee-detail']",
        # Specification tables
        "table", "dl",
        # Tabs / accordions that might hide specs
        "[class*='tab-content']",
        "[class*='accordion-content']",
        "[class*='spec']",
        "[class*='characteristic']",
        "[class*='attribute']",
    ]
    seen: set[int] = set()
    chunks: list[str] = []
    for sel in CANDIDATE_SELECTORS:
        for node in soup.select(sel):
            nid = id(node)
            if nid in seen:
                continue
            seen.add(nid)
            text = node.get_text(separator=" ", strip=True)
            if len(text) > 40:
                chunks.append(text[:2000])  # cap per section
    return "\n\n".join(chunks)


def scrape_url(url: str) -> tuple[str, str]:
    """
    Fetch a product URL and return (rich_structured_text, diagnostic_note).

    Strategy (no headless browser):
    1. JSON-LD  → most reliable for marketplace/Shopify pages
    2. Open Graph + meta tags
    3. Microdata (itemprop)
    4. Semantic HTML extraction (product zones, tables, dl)
    5. Full visible text fallback

    Returns a merged text optimised for the AI prompt, and a short note
    describing what was found (for debugging).
    """
    response = requests.get(url, headers=_HEADERS, timeout=15)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    # Remove noise
    for tag in soup(["script", "style", "nav", "footer", "header",
                     "noscript", "aside", "iframe"]):
        tag.decompose()

    sections: list[str] = []
    notes: list[str]    = []

    # 1. JSON-LD
    json_ld = _extract_json_ld(soup)
    if json_ld:
        sections.append(f"[STRUCTURED DATA – JSON-LD]\n{json_ld}")
        notes.append("json-ld")

    # 2. Meta / OG
    meta = _extract_meta(soup)
    if meta:
        sections.append(f"[META TAGS]\n{meta}")
        notes.append("meta")

    # 3. Microdata
    micro = _extract_microdata(soup)
    if micro:
        sections.append(f"[MICRODATA]\n{micro}")
        notes.append("microdata")

    # 4. Product sections
    product_text = _extract_product_sections(soup)
    if product_text:
        sections.append(f"[PRODUCT CONTENT]\n{product_text}")
        notes.append("product-sections")

    # 5. Full text fallback (capped)
    full_text = soup.get_text(separator="\n", strip=True)
    if len(full_text) > _MIN_TEXT_LENGTH:
        sections.append(f"[PAGE TEXT FALLBACK]\n{full_text[:6000]}")
        notes.append("full-text")
    elif not sections:
        # Likely a JS-only page — return raw HTML so AI can try
        sections.append(f"[RAW HTML – JS-rendered page, limited data]\n{response.text[:4000]}")
        notes.append("raw-html-fallback")

    diagnostic = ", ".join(notes) if notes else "no-content"
    return "\n\n---\n\n".join(sections), diagnostic


# ─────────────────────────────────────────────────────────────────────────────
# CoffeeAIParser  –  prompt builder, no thread ownership
# ─────────────────────────────────────────────────────────────────────────────

class CoffeeAIParser:
    """
    Builds the AI extraction prompt and calls instructor.
    Does NOT own a QThread – this runs inside TilauAIService's worker thread.
    """

    def __init__(
        self,
        ai: TilauAIConfig,
        categories: list[str],
        process_categories: dict[str, list[str]],
        coffee_producing_countries: list[str] | None,
        coffee_bean_types: dict[str, list[str]],
        coffee_bean_species: list[str],
    ) -> None:
        self._ai = ai
        self.categories = categories
        self.process_categories = process_categories
        self.countries = coffee_producing_countries or ["Other"]
        self.bean_types = coffee_bean_types
        self.species = coffee_bean_species

    def _build_client(self):
        """Lazily build the instructor client inside the worker thread.

        Uses instructor.from_openai() with the provider's OpenAI-compat
        endpoint — no provider-specific SDK (e.g. google-genai) required.
        normalize_engine() migrates legacy bare engine strings.
      """
        from tilauscope.ai_support import normalize_engine, provider_base_url  # noqa: PLC0415
        engine   = normalize_engine(self._ai.engine)
        model    = engine.split("/", 1)[1] if "/" in engine else engine
        base_url = provider_base_url(engine)
        raw      = _openai.OpenAI(api_key=self._ai.apikey, base_url=base_url)
        client   = _instructor.from_openai(raw)
        return client, model

    def get_bean_from_url(
        self,
        url: str,
        cancel_token: _CancelToken | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> GreenBean | None:
        """
        Scrape *url* and return a populated GreenBean, or None on failure.

        cancel_token and on_token are optional for backward compatibility with
        beancave.py's BeanAIWorker which calls get_bean_from_url(url) directly.
        When called via TilauAIService/submit_bean_extract they are provided.
        """
        def _emit(msg: str) -> None:
            if on_token is not None:
                on_token(msg)

        def _cancelled() -> bool:
            return cancel_token is not None and cancel_token.is_cancelled

        _emit("scraping…")
        try:
            page_text, diag = scrape_url(url)
        except Exception as exc:
            _log.error("bean_extractor scrape error: %s", exc)
            raise

        if _cancelled():
            return None

        _log.debug("bean_extractor: scraped %s (%s)", url, diag)
        _emit(f"analysing ({diag})…")

        system_prompt = (
            "You are an expert Coffee Quality Control Analyst and roasting specialist. "
            "Parse the web data provided and map it precisely to the JSON schema. "
            "Rules:\n"
            "1. Never invent data. Use field defaults when information is absent.\n"
            "2. Output ASCII only — no accented characters.\n"
            "3. 'farm': if absent look for estate, region, station, mill, cooperative.\n"
            "4. Altitude: convert to meters, use average if a range is given.\n"
            "5. Roasting tips: summarise as concise bullet points.\n"
            "6. Prefer STRUCTURED DATA sections (JSON-LD, microdata) over plain text.\n"
            f"7. Country must match one of: {self.countries}\n"
            f"8. Species must match one of: {self.species}\n"
            f"9. Process/category must match one of: {self.categories}\n"
            "10. For marketplace/shop pages the product name usually contains origin, "
            "variety, and process — parse it carefully.\n"
            "11. Blends: if the page describes a blend (the word 'blend', or "
            "several origins/coffees listed as components), set is_blend=true "
            "and fill the component names and ratios. If the ratios are not "
            "stated: two coffees -> 50/50; three coffees -> 34/33/33. If there "
            "are more than three components, keep the first three and list the "
            "remaining ones at the end of the roasting tips.\n"
            "12. Varieties: ONLY use values from this allowed list per "
            f"species: {self.bean_types}. If the page's variety is not in the "
            "list, leave 'varieties' empty and mention the original wording "
            "in the roasting tips.\n"
            "13. Flavour notes: MUST be in English only. "
            "Match each note to the closest term in this reference list when possible: "
            f"{', '.join(_get_wheel_notes()) or 'use English descriptors'}. "
            "If no close match exists in the list, keep the original English term as-is. "
            "Output as a comma-separated list. Never translate flavour notes.\n"
        )

        user_prompt = (
            f"Source URL: {url}\n\n"
            f"Page data:\n---\n{page_text}\n---\n\n"
            "Extract the green bean information according to the rules above."
        )

        if _cancelled():
            return None

        client, model_name = self._build_client()
        from typing import cast  # noqa: PLC0415
        extracted = cast(
            GreenBeanSchema,
            client.chat.completions.create(
                model=model_name,
                response_model=GreenBeanSchema,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
            ),
        )
        return GreenBean(**extracted.model_dump())


# ─────────────────────────────────────────────────────────────────────────────
# Public submission helper
# ─────────────────────────────────────────────────────────────────────────────

def submit_bean_extract(
    ai_service: TilauAIService,
    parser: CoffeeAIParser,
    url: str,
) -> bool:
    """
    Submit a BEAN_EXTRACT task to *ai_service*.

    Returns False if the service is already busy with another extraction.

    The caller connects to:
        ai_service.task_finished  → (AITask.BEAN_EXTRACT, GreenBean | None)
        ai_service.task_error     → (AITask.BEAN_EXTRACT, str)
        ai_service.token_received → (AITask.BEAN_EXTRACT, str) for progress hints
        ai_service.task_busy      → (AITask.BEAN_EXTRACT) to grey the button
    """
    def _work(cancel: _CancelToken, on_token: Callable[[str], None]):
        return parser.get_bean_from_url(url, cancel, on_token)

    return ai_service.submit(AITask.BEAN_EXTRACT, _work)