import logging
import re

from google import genai
from google.genai import types
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.receipt import ExtractedReceipt


class ReceiptParseError(ValueError):
    """Raised when Gemini's response cannot be parsed into ExtractedReceipt."""


logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = (
    "Extract data from this Spanish supermarket receipt as JSON.\n\n"
    "Header fields:\n"
    "- supermarket_name: chain name (e.g. MERCADONA)\n"
    "- supermarket_locality: city from the address, or null\n"
    "- invoice_number: code after 'FACTURA SIMPLIFICADA:' "
    "(e.g. '3923-014-675403'), or null\n"
    "- date: YYYY-MM-DD\n"
    "- total: the TOTAL (€) amount (not subtotals, not tax breakdown)\n\n"
    "Line items — by-unit and by-weight examples:\n\n"
    '  "1 QUESO CURADO  4,78"\n'
    '  → {"product_name":"QUESO CURADO","quantity":1,'
    '"unit_price":4.78,"line_total":4.78}\n\n'
    '  "1 BANANA / 1,168 kg  1,45 €/kg  1,68"\n'
    '  → {"product_name":"BANANA","quantity":1.168,'
    '"unit_price":1.45,"line_total":1.68}\n\n'
    "Rules:\n"
    "- All numeric values: plain numbers, dot decimal separator "
    '(1.168 not "1,168" or "1.168 kg").\n'
    "- Exclude parking, discounts, coupons, and non-product lines."
)


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


_DECIMAL_COMMA_RE = re.compile(r'"(\d+),(\d+)"')
_UNIT_SUFFIX_RE = re.compile(r'"(\d+(?:\.\d+)?)\s+(?:kg|€/kg|g|ml|l|ud)"', re.IGNORECASE)


def _sanitize_numeric_values(raw: str) -> str:
    """Fix common Gemini quirks in numeric JSON string values.

    - European decimal commas: "22,74" → "22.74"
    - Unit suffixes: "1.168 kg" → "1.168"
    """
    fixed = _DECIMAL_COMMA_RE.sub(r'"\1.\2"', raw)
    fixed = _UNIT_SUFFIX_RE.sub(r'"\1"', fixed)
    if fixed != raw:
        logger.debug("Sanitized numeric values in Gemini response")
    return fixed


async def extract_receipt_from_pdf(pdf_bytes: bytes) -> ExtractedReceipt:
    """Send a receipt PDF to Gemini and return structured extraction."""
    logger.info("Sending PDF (%d bytes) to Gemini model=%s", len(pdf_bytes), settings.gemini_model)
    client = _get_client()

    response = await client.aio.models.generate_content(
        model=settings.gemini_model,
        contents=[
            types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf"),
            EXTRACTION_PROMPT,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedReceipt,
        ),
    )

    raw_json = _sanitize_numeric_values(response.text)
    try:
        result = ExtractedReceipt.model_validate_json(raw_json)
    except ValidationError as exc:
        logger.error("Failed to parse Gemini response: %s\nRaw JSON: %s", exc, raw_json)
        raise ReceiptParseError(str(exc)) from exc
    logger.info(
        "Gemini extracted: supermarket=%s, date=%s, total=%s, line_items=%d",
        result.supermarket_name,
        result.date,
        result.total,
        len(result.line_items),
    )
    return result
