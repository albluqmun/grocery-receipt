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
    "Extract all data from this supermarket receipt. "
    "Return a JSON object with these fields:\n"
    "- supermarket_name: name of the supermarket chain (e.g. 'MERCADONA')\n"
    "- supermarket_locality: city/town from the address, or null\n"
    "- invoice_number: the receipt/invoice identifier "
    "(e.g. 'FACTURA SIMPLIFICADA: 3823-014-675403' → '3823-014-675403'), or null\n"
    "- date: receipt date in YYYY-MM-DD format\n"
    "- total: total amount in euros\n"
    "- line_items: array of purchased items, each with:\n"
    "  - product_name: product name exactly as shown on receipt\n"
    "  - quantity: number of units, or weight in kg for weighted products\n"
    "  - unit_price: price per unit, or price per kg for weighted products\n"
    "  - line_total: total price for this line\n\n"
    "Rules for line items:\n"
    "- For products sold by weight (showing kg and €/kg), "
    "use the weight as quantity and the per-kg price as unit_price.\n"
    "- For products sold by unit, use the count as quantity "
    "and line_total divided by quantity as unit_price.\n"
    "- Do NOT include parking, discounts, or non-product lines.\n"
    "- Use decimal numbers for all numeric values (not strings)."
)


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.gemini_api_key)
    return _client


_DECIMAL_COMMA_RE = re.compile(r'"(\d+),(\d+)"')


def _fix_decimal_commas(raw: str) -> str:
    """Replace European decimal commas with dots in JSON numeric string values.

    Gemini sometimes returns '\"22,74\"' instead of '\"22.74\"' for Spanish receipts.
    Only touches quoted strings that look like decimal numbers (e.g. "1,45", "0,416").
    """
    fixed = _DECIMAL_COMMA_RE.sub(r'"\1.\2"', raw)
    if fixed != raw:
        logger.debug("Fixed European decimal commas in Gemini response")
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

    raw_json = _fix_decimal_commas(response.text)
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
