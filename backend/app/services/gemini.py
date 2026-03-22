import logging

from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.receipt import ExtractedReceipt

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

    result = ExtractedReceipt.model_validate_json(response.text)
    logger.info(
        "Gemini extracted: supermarket=%s, date=%s, total=%s, line_items=%d",
        result.supermarket_name,
        result.date,
        result.total,
        len(result.line_items),
    )
    return result
