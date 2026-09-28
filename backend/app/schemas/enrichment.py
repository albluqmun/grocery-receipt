from pydantic import BaseModel


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
