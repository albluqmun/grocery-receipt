from pydantic import BaseModel


class OFFCandidate(BaseModel):
    """A product candidate returned by Open Food Facts search."""

    code: str
    product_name: str
    categories: str | None = None
    image_url: str | None = None


class EnrichmentResult(BaseModel):
    """Response from product enrichment operations."""

    processed: int
    enriched: int
    not_found: int
    skipped: int
    failed: bool = False


class ResetResult(BaseModel):
    """Response from bulk reset of failed enrichments."""

    reset: int
