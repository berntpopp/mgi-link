"""Live MouseMine (InterMine) client — the cold-start marker fallback.

Implements the ``MarkerProvider`` Protocol against the MouseMine InterMine web
service. Used ONLY when the local SQLite index is unavailable AND
``enable_live_fallback`` is on. Synchronous (matches ``ingest/downloader.py``);
the rare blocking call during a cold start is an accepted trade-off.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import quoteattr

import httpx

from mgi_link.constants import HUMAN_TAXON_ID, MOUSE_TAXON_ID
from mgi_link.exceptions import RateLimitError, ServiceUnavailableError

if TYPE_CHECKING:
    from mgi_link.config import MouseMineConfig

_BACKOFF_BASE = 0.5

# View column order for a Gene identity lookup (see Task 3 Step 1 verification).
_GENE_VIEW = (
    "Gene.primaryIdentifier",
    "Gene.symbol",
    "Gene.name",
    "Gene.sequenceOntologyTerm.name",
    "Gene.chromosome.primaryIdentifier",
    "Gene.chromosomeLocation.start",
    "Gene.chromosomeLocation.end",
    "Gene.chromosomeLocation.strand",
    "Gene.ncbiGeneNumber",
    "Gene.synonyms.value",
)
_SYMBOL_VIEW = ("Gene.primaryIdentifier", "Gene.symbol", "Gene.synonyms.value")
_ORTHOLOG_VIEW = (
    "Gene.homologues.homologue.symbol",
    "Gene.homologues.homologue.crossReferences.identifier",
    "Gene.homologues.homologue.organism.taxonId",
)


def _query(
    view: tuple[str, ...],
    path: str,
    op: str,
    value: str,
    *,
    extra: str | None = None,
) -> str:
    """Build a single-constraint InterMine PathQuery XML string."""
    extra_attr = f" extraValue={quoteattr(extra)}" if extra else ""
    return (
        f'<query model="genomic" view="{" ".join(view)}">'
        f"<constraint path={quoteattr(path)} op={quoteattr(op)} "
        f"value={quoteattr(value)}{extra_attr}/></query>"
    )


class MouseMineClient:
    """Sync InterMine client implementing the MarkerProvider Protocol."""

    def __init__(self, config: MouseMineConfig) -> None:
        """Open a pooled httpx client and prime the rate limiter."""
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=config.timeout,
            headers={"User-Agent": config.user_agent},
            follow_redirects=False,
        )
        self._min_interval = 1.0 / config.rate_limit_per_s if config.rate_limit_per_s > 0 else 0.0
        self._last = 0.0

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    # -- HTTP ------------------------------------------------------------------

    def _throttle(self) -> None:
        if self._min_interval <= 0:
            return
        wait = self._min_interval - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

    def _rows(self, query_xml: str) -> list[list[Any]]:
        """Issue the query with retries; return the positional results list."""
        params = {"query": query_xml, "format": "json"}
        last: Exception | None = None
        for attempt in range(self._config.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get("/query/results", params=params)
            except httpx.HTTPError as exc:  # network/timeout
                last = exc
                if attempt < self._config.max_retries:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                continue
            if resp.is_redirect:
                raise ServiceUnavailableError(
                    f"MouseMine returned unexpected redirect {resp.status_code}."
                )
            if resp.status_code == 429:
                if attempt < self._config.max_retries:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                raise RateLimitError()
            if resp.status_code >= 500:
                if attempt < self._config.max_retries:
                    time.sleep(_BACKOFF_BASE * (2**attempt))
                    continue
                raise ServiceUnavailableError()
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ServiceUnavailableError() from exc
            data = resp.json()
            results = data.get("results", [])
            return [list(r) for r in results]
        # Sever the transport exception text: str(last) is a network/httpx error
        # (never an upstream response body), but a fixed message keeps any transport
        # detail out of the caller-visible frame and out of logs. The chained cause
        # is preserved for server-side debugging only.
        raise ServiceUnavailableError("MouseMine request failed.") from last

    # -- MarkerProvider --------------------------------------------------------

    def get_marker(self, mgi_id: str) -> dict[str, Any] | None:
        """Return a marker dict (repository.get_marker shape) or None."""
        rows = self._rows(_query(_GENE_VIEW, "Gene.primaryIdentifier", "=", mgi_id))
        return _marker_from_rows(rows)

    def lookup_symbol(self, symbol: str) -> list[tuple[str, str]]:
        """Resolve a symbol/synonym to (mgi_id, 'current'|'synonym') pairs."""
        rows = self._rows(_query(_SYMBOL_VIEW, "Gene", "LOOKUP", symbol, extra=MOUSE_TAXON_ID))
        best: dict[str, str] = {}
        target = symbol.strip().upper()
        for r in rows:
            mgi_id, gene_symbol = r[0], r[1]
            stype = "current" if (gene_symbol or "").upper() == target else "synonym"
            if best.get(mgi_id) != "current":
                best[mgi_id] = stype
        pairs = list(best.items())
        pairs.sort(key=lambda p: 0 if p[1] == "current" else 1)
        return pairs

    def lookup_by_xref(self, source: str, value: str) -> list[str]:
        """Human symbol/HGNC -> mouse ortholog MGI ids (parity with the index)."""
        if source == "human_symbol":
            path = "Gene.homologues.homologue.symbol"
        elif source == "hgnc_id":
            path = "Gene.homologues.homologue.crossReferences.identifier"
        else:
            return []
        view = ("Gene.primaryIdentifier",)
        rows = self._rows(_query(view, path, "=", value))
        seen: dict[str, None] = {}
        for r in rows:
            seen[r[0]] = None
        return list(seen)

    def get_ortholog(self, mgi_id: str) -> dict[str, Any] | None:
        """Return the mouse->human ortholog dict (get_marker shape) or None."""
        rows = self._rows(_query(_ORTHOLOG_VIEW, "Gene.primaryIdentifier", "=", mgi_id))
        human_rows = [r for r in rows if len(r) >= 3 and str(r[2]) == HUMAN_TAXON_ID]
        if not human_rows:
            return None
        hgnc_id = next(
            (str(r[1]) for r in human_rows if str(r[1] or "").startswith("HGNC:")),
            None,
        )
        return {"human_symbol": human_rows[0][0], "hgnc_id": hgnc_id, "omim_gene_id": None}


def _marker_from_rows(rows: list[list[Any]]) -> dict[str, Any] | None:
    """Collapse repeated synonym-join rows into one marker (repo shape)."""
    if not rows:
        return None
    first = rows[0]
    synonyms: list[str] = []
    for r in rows:
        syn = r[9] if len(r) > 9 else None
        if syn and syn not in synonyms:
            synonyms.append(syn)
    entrez = first[8] if len(first) > 8 else None
    return {
        "mgi_id": first[0],
        "symbol": first[1],
        "name": first[2],
        "marker_type": "Gene",
        "feature_type": first[3],
        "chromosome": first[4],
        "cm_position": None,
        "coord_start": first[5],
        "coord_end": first[6],
        "strand": first[7],
        "status": None,
        "entrez_id": str(entrez) if entrez is not None else None,
        "ensembl_gene_id": None,
        "refseq_id": None,
        "synonyms": synonyms,
    }
