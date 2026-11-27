"""A5 Physical Laser Printing Engine for StockBill Sales Invoices.

Target specifications:
- Paper: A5 Landscape (210 mm x 148 mm)
- PDF dimensions: 595.28 pt x 419.53 pt (exact landscape(A5))
- Margins: 5 mm (printable width 566.94 pt / 200 mm)
- Resolution: Exact millimeter layout via ReportLab
- Output: Compact, clean ERP-grade invoice matching the MARG reference structure
- Authoritative Data: StockBill persisted snapshot fields only
"""

from decimal import Decimal
import io
import logging
import os
import re

from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from .models import BusinessProfile, Invoice

logger = logging.getLogger(__name__)


# --- COLOR PALETTE (matching visual reference) ---
COLOR_BORDER = HexColor("#000000")
COLOR_HEADER_BG = HexColor("#D8EFF6")  # Light cyan accent
COLOR_MUTED_BG = HexColor("#F5F5F5")
COLOR_TEXT = HexColor("#000000")
COLOR_DRAFT = HexColor("#888888")
COLOR_CANCELLED = HexColor("#C0392B")

# --- A5 LANDSCAPE INVOICE CANVAS & LAYOUT DIMENSIONS ---
# Existing StockBill invoice layout coordinates are based on A5 landscape.
PAGE_WIDTH, PAGE_HEIGHT = landscape(A5)  # 595.275 pt, 419.528 pt (210 mm x 148 mm)
MARGIN = 5 * mm  # 14.17 pt
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * MARGIN)  # ~566.94 pt
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * MARGIN)  # ~391.18 pt

# --- A4 PORTRAIT CONTAINER & PRINTING GEOMETRY ---
# PDF page container is A4 portrait (595.28 pt x 841.89 pt) without rotation.
# The A5 landscape invoice is positioned near the top of the A4 page, mirroring
# Marg ERP's proven physical printing geometry.
A4_WIDTH, A4_HEIGHT = A4  # 595.276 pt x 841.890 pt (210 mm x 297 mm)

# Target reference geometry: ~196 mm x 135 mm placed near top of A4 portrait
INVOICE_SCALE = 0.98  # Outer border: 196.0 mm x 135.2 mm (555.59 pt x 383.36 pt)
INVOICE_X_OFFSET = (A4_WIDTH - INVOICE_SCALE * PAGE_WIDTH) / 2  # 5.95 pt -> 7.0 mm side margins
INVOICE_TOP_MARGIN = 18.0  # 6.35 mm from top of A4 sheet (matching Marg's 17.6 pt)
INVOICE_Y_OFFSET = A4_HEIGHT - INVOICE_TOP_MARGIN - INVOICE_SCALE * (PAGE_HEIGHT - MARGIN)  # ~426.64 pt

# Bounding box coordinates on the final A4 page for verification and testing
INVOICE_BOX_X0 = INVOICE_X_OFFSET + INVOICE_SCALE * MARGIN  # 19.84 pt (7.0 mm)
INVOICE_BOX_X1 = INVOICE_X_OFFSET + INVOICE_SCALE * (PAGE_WIDTH - MARGIN)  # 575.43 pt (7.0 mm right margin)
INVOICE_BOX_Y0 = INVOICE_Y_OFFSET + INVOICE_SCALE * MARGIN  # 440.53 pt (bottom of invoice box)
INVOICE_BOX_Y1 = INVOICE_Y_OFFSET + INVOICE_SCALE * (PAGE_HEIGHT - MARGIN)  # 823.89 pt (18.0 pt top margin)
INVOICE_BOX_WIDTH = INVOICE_BOX_X1 - INVOICE_BOX_X0  # 555.59 pt (196.00 mm)
INVOICE_BOX_HEIGHT = INVOICE_BOX_Y1 - INVOICE_BOX_Y0  # 383.36 pt (135.24 mm)


def amount_to_words(amount) -> str:
    """Convert a numeric monetary amount into Indian currency words.

    Example:
        42995.00 -> 'Rs. Forty Two Thousand Nine Hundred and Ninety Five only'
        100.50   -> 'Rs. One Hundred and Paise Fifty only'
    """
    try:
        val = Decimal(str(amount)).quantize(Decimal("0.01"))
    except Exception:
        return "Rs. Zero only"

    if val == Decimal("0.00"):
        return "Rs. Zero only"

    rupees = int(val)
    paise = int((val - rupees) * 100)

    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen"
    ]
    tens = [
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"
    ]

    def two_digits(n: int) -> str:
        if n < 20:
            return ones[n]
        return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])

    def three_digits(n: int) -> str:
        if n == 0:
            return ""
        h = n // 100
        rem = n % 100
        res = ""
        if h > 0:
            res += ones[h] + " Hundred"
        if rem > 0:
            if res:
                res += " and "
            res += two_digits(rem)
        return res

    parts = []
    crores = rupees // 10000000
    rupees %= 10000000
    lakhs = rupees // 100000
    rupees %= 100000
    thousands = rupees // 1000
    rupees %= 1000
    hundreds = rupees

    if crores > 0:
        parts.append(two_digits(crores) + " Crore")
    if lakhs > 0:
        parts.append(two_digits(lakhs) + " Lakh")
    if thousands > 0:
        parts.append(two_digits(thousands) + " Thousand")
    if hundreds > 0:
        parts.append(three_digits(hundreds))

    words = " ".join(parts).strip() if parts else "Zero"
    res = f"Rs. {words}"
    if paise > 0:
        res += f" and {two_digits(paise)} Paise"
    res += " only"
    return res


def profile_logo_reader(profile):
    """The shop's uploaded logo (Business Profile) for drawImage, or None.

    Reprints of old invoices use the current logo on purpose; the logo is
    branding, not an invoice particular, so it is not snapshotted.
    """
    logo = getattr(profile, "logo", None) if profile else None
    if not logo:
        return None
    try:
        return ImageReader(io.BytesIO(bytes(logo)))
    except Exception:  # a damaged stored image must never break invoicing
        logger.warning("Business Profile logo could not be read; printing without it.", exc_info=True)
        return None


# Item row styling constants
ITEM_ROW_FONT_SIZE = 9.0   # Visually prominent ERP item font size (9.0 pt strictly maintained)
ITEM_ROW_HEIGHT = 13.0     # Standard single-line row height
ITEM_LINE_LEADING = 10.0   # Vertical spacing for wrapped 9 pt lines

# Fixed blocks of each page (unscaled pt). Pagination measures the space left
# between them, so the drawing code below uses the same values.
HEADER_HEIGHT = 56.0
CUSTOMER_BOX_MIN_HEIGHT = 30.0
TABLE_HEADER_HEIGHT = 14.0
FOOTER_HEIGHT_LAST = 115.0       # GST summary, totals, words, terms, signatures
FOOTER_HEIGHT_CONTINUED = 85.0   # "Continued..." footer on non-final pages
# Upper limits on item rows per page (kept from the original fixed budgets);
# a page also ends earlier when the next row would not fit above its footer.
STOCKBILL_CREDIT_TEXT = "Generated by StockBill"
STOCKBILL_CREDIT_COLOR = HexColor("#8A8F8C")
MAX_LINES_PAGE_ONE = 13
MAX_LINES_SUBSEQUENT = 14


def format_qty_presentation(line) -> tuple[str, str]:
    """Format quantity and pack strings according to StockBill unit rules.

    - Qty column: displays only numeric quantity (no 'pcs', 'Box', etc.).
    - Pack column: displays the product's units_per_master_box, or '-' if not configured.

    Returns:
        (qty_display, pack_display)
    """
    raw_qty = getattr(line, "quantity", Decimal("0"))

    def clean_num(d):
        d = Decimal(str(d))
        if d == d.to_integral_value():
            return str(int(d))
        return f"{d:.3f}".rstrip("0").rstrip(".")

    qty_str = clean_num(raw_qty) if raw_qty is not None else "0"

    product = getattr(line, "product", None)
    pack_val = None
    if product is not None:
        pack_val = getattr(product, "units_per_master_box", None)
        if callable(pack_val):
            pack_val = pack_val()

    # Fallback to direct attribute lookup if product doesn't have the property or returned None
    if pack_val is None and product is not None and hasattr(product, "attribute_values"):
        try:
            from inventory.models import ProductAttributeValue
            attr_val = (
                ProductAttributeValue.objects.filter(
                    product=product,
                    attribute_definition__code="units_per_master_box",
                    attribute_definition__is_active=True,
                )
                .values_list("value_integer", flat=True)
                .first()
            )
            if attr_val and attr_val > 0:
                pack_val = attr_val
        except Exception:
            pass

    if pack_val is not None and pack_val > 0:
        pack_disp = clean_num(pack_val)
    else:
        pack_disp = "-"

    return qty_str, pack_disp


def wrap_product_description(
    text: str,
    max_w: float,
    font_name: str = "Helvetica",
    font_size: float = ITEM_ROW_FONT_SIZE,
) -> list[str]:
    """Wrap product description words into 9 pt lines that each fit within max_w.

    Never auto-scales or reduces the font below 9 pt.
    """
    text = str(text or "").strip()
    if not text:
        return []
    words = text.split()
    lines = []
    curr = []
    for w in words:
        test = " ".join(curr + [w]) if curr else w
        if stringWidth(test, font_name, font_size) <= max_w:
            curr.append(w)
        else:
            if curr:
                lines.append(" ".join(curr))
                curr = []
            if stringWidth(w, font_name, font_size) <= max_w:
                curr = [w]
            else:
                chunk = ""
                for char in w:
                    if stringWidth(chunk + char, font_name, font_size) <= max_w:
                        chunk += char
                    else:
                        if chunk:
                            lines.append(chunk)
                        chunk = char
                if chunk:
                    curr = [chunk]
    if curr:
        lines.append(" ".join(curr))
    return lines


def get_item_row_height(desc_lines: list[str]) -> float:
    """Calculate row height: 13.0 pt for single-line, expanding for multi-line."""
    num_lines = max(1, len(desc_lines))
    if num_lines == 1:
        return ITEM_ROW_HEIGHT
    return ITEM_ROW_HEIGHT + (num_lines - 1) * ITEM_LINE_LEADING


# Customer ("Bill To") block. The recipient's name and address are tax-invoice
# particulars, so they are wrapped and shrunk to fit, never cut off.
CUSTOMER_COLUMN_RATIO = 0.60          # left (customer) share of the block width
CUSTOMER_NAME_X = 78.0                # name starts after "Bill To / Recipient:"
CUSTOMER_NAME_SIZES = (8.5, 7.5)      # shrink once, then wrap at 7.5 pt
CUSTOMER_NAME_LEADING = 9.0
CUSTOMER_ADDRESS_LABEL = "Address: "
CUSTOMER_ADDRESS_SIZES = (7.5, 7.0, 6.5)
CUSTOMER_ADDRESS_MAX_LINES = 3        # beyond this, step the font down first
_LINE_BREAKS = re.compile(r"\r\n|\r|\n")


def normalize_address(text) -> str:
    """One-line address: line breaks become ", ", blank parts are dropped."""
    parts = (part.strip() for part in _LINE_BREAKS.split(str(text or "")))
    return ", ".join(part for part in parts if part)


def fit_wrapped_text(text: str, max_w: float, font_name: str, sizes, max_lines: int):
    """Wrap ``text`` to ``max_w`` at the first size that needs <= max_lines.

    If even the smallest size needs more lines, all of them are returned at
    that size: text is never dropped. Returns (lines, font_size).
    """
    for size in sizes:
        lines = wrap_product_description(text, max_w, font_name=font_name, font_size=size)
        if len(lines) <= max_lines:
            return lines, size
    return lines, size


def layout_customer_block(cust_name, cust_address) -> dict:
    """Lines, font sizes and box height for the Bill To block."""
    col_w = PRINTABLE_WIDTH * CUSTOMER_COLUMN_RATIO
    name = " ".join(str(cust_name or "").split()) or "-"
    name_lines, name_size = fit_wrapped_text(
        name, col_w - CUSTOMER_NAME_X - 6, "Helvetica-Bold", CUSTOMER_NAME_SIZES, max_lines=1
    )
    label_w = stringWidth(CUSTOMER_ADDRESS_LABEL, "Helvetica", 7.5)
    address = normalize_address(cust_address)
    if address:
        addr_lines, addr_size = fit_wrapped_text(
            address, col_w - 12 - label_w, "Helvetica", CUSTOMER_ADDRESS_SIZES, CUSTOMER_ADDRESS_MAX_LINES
        )
    else:
        addr_lines, addr_size = ["-"], CUSTOMER_ADDRESS_SIZES[0]
    addr_leading = addr_size + 1.0
    box_h = (
        CUSTOMER_BOX_MIN_HEIGHT
        + (len(name_lines) - 1) * CUSTOMER_NAME_LEADING
        + (len(addr_lines) - 1) * addr_leading
    )
    return {
        "name_lines": name_lines,
        "name_size": name_size,
        "addr_lines": addr_lines,
        "addr_size": addr_size,
        "addr_leading": addr_leading,
        "addr_label_w": label_w,
        "box_h": box_h,
    }


ELLIPSIS = "…"
TERMS_FONT_SIZES = (6.0, 5.5, 5.0)          # step down to fit; 5 pt minimum
SIGNATURE_NAME_FONT_SIZES = (7.0, 6.5, 6.0)  # "For <business name>"; 6 pt minimum
SIGNATURE_NAME_MAX_LINES = 2


def _with_ellipsis(text, max_w, font_name, font_size):
    """``text`` shortened as needed so that text + "…" fits ``max_w``."""
    text = text.rstrip()
    while text and stringWidth(text + ELLIPSIS, font_name, font_size) > max_w:
        text = text[:-1].rstrip()
    return text + ELLIPSIS


def layout_terms(terms_text, max_w, first_baseline, min_baseline):
    """Wrap terms to the box width, stepping the font down until they fit.

    Each terms line is wrapped (never cut) to ``max_w``. Line i sits at
    first_baseline - i * font_size; nothing goes below ``min_baseline``.
    If even 5 pt does not fit, as many lines as fit are kept and the last
    ends with "…" (truncated=True: the terms are too long for the box).
    """
    paragraphs = [part.strip() for part in str(terms_text or "").splitlines() if part.strip()]
    lines = []
    for size in TERMS_FONT_SIZES:
        lines = [line for part in paragraphs for line in wrap_product_description(part, max_w, "Helvetica", size)]
        capacity = int((first_baseline - min_baseline) // size) + 1
        if len(lines) <= capacity:
            return {"lines": lines, "font_size": size, "truncated": False}
    kept = lines[:capacity]
    if kept:
        kept[-1] = _with_ellipsis(kept[-1], max_w, "Helvetica", size)
    return {"lines": kept, "font_size": size, "truncated": True}


def shrink_then_wrap(text, max_w, font_name, sizes, max_lines):
    """Fit ``text`` on one line at the first size in ``sizes`` that fits;
    otherwise wrap it at the smallest size into at most ``max_lines`` lines.
    Text that still does not fit ends with a visible "…" (truncated=True),
    never a silent cut."""
    text = " ".join(str(text or "").split())
    for size in sizes:
        if stringWidth(text, font_name, size) <= max_w:
            return {"lines": [text] if text else [], "font_size": size, "truncated": False}
    size = sizes[-1]
    lines = wrap_product_description(text, max_w, font_name, size)
    if len(lines) <= max_lines:
        return {"lines": lines, "font_size": size, "truncated": False}
    kept = lines[:max_lines]
    kept[-1] = _with_ellipsis(" ".join([kept[-1]] + lines[max_lines:]), max_w, font_name, size)
    return {"lines": kept, "font_size": size, "truncated": True}


def layout_signature_name(co_name, max_w):
    """"For <business name>": shrink to fit (down to 6 pt), then wrap to 2 lines."""
    text = f"For {' '.join(str(co_name or '').split())}".rstrip()
    return shrink_then_wrap(text, max_w, "Helvetica-Bold", SIGNATURE_NAME_FONT_SIZES, SIGNATURE_NAME_MAX_LINES)


HEADER_NAME_FONT_SIZES = (11.0, 10.0, 9.0, 8.0)  # 8 pt minimum, then 2 lines


def layout_header_name(co_name, max_w):
    """Business name in the invoice header (upper case): shrink, then wrap."""
    return shrink_then_wrap(str(co_name or "").upper(), max_w, "Helvetica-Bold", HEADER_NAME_FONT_SIZES, 2)


def draw_footer_boxes(c, *, left_x, right_x, bottom_y, words_bot, usable_w, terms_text, co_name):
    """Bottom row of every page: Terms & Conditions | Receiver's | For <name>.

    Shared by the continuation-page and last-page footers. Terms wrap inside
    their own column and never reach the signature columns; returns the
    terms layout so callers/tests can see when terms had to be shortened.
    """
    b_w1 = usable_w * 0.45
    b_w2 = usable_w * 0.25
    b_w3 = usable_w - b_w1 - b_w2

    c.line(left_x + b_w1, words_bot, left_x + b_w1, bottom_y)
    c.line(left_x + b_w1 + b_w2, words_bot, left_x + b_w1 + b_w2, bottom_y)

    c.setFont("Helvetica-Bold", 7)
    c.drawString(left_x + 4, words_bot - 8, "Terms & Conditions")
    # First line sits just under the title (whose baseline is words_bot - 8);
    # the last may go down to 2 pt above the bottom border. That is 5 lines
    # at 6 pt and 6 lines at 5 pt.
    first_baseline = words_bot - 14.5
    terms = layout_terms(terms_text, b_w1 - 8, first_baseline=first_baseline, min_baseline=bottom_y + 2)
    c.setFont("Helvetica", terms["font_size"])
    ty = first_baseline
    for line in terms["lines"]:
        c.drawString(left_x + 4, ty, line)
        ty -= terms["font_size"]
    if terms["truncated"]:
        logger.warning("Invoice terms are too long for the terms box; shown up to an ellipsis.")

    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(left_x + b_w1 + (b_w2 / 2), bottom_y + 6, "Receiver's Signature")

    name = layout_signature_name(co_name, b_w3 - 12)
    c.setFont("Helvetica-Bold", name["font_size"])
    ny = words_bot - 8
    for line in name["lines"]:
        c.drawString(left_x + b_w1 + b_w2 + 6, ny, line)
        ny -= name["font_size"] + 1
    c.setFont("Helvetica-Bold", 7.5)
    c.drawCentredString(right_x - (b_w3 / 2), bottom_y + 6, "Authorised Signatory")
    return {"terms": terms, "signature_name": name}


def rows_area_height(cust_box_h: float, is_first_page: bool, is_last_page: bool) -> float:
    """Vertical space for item rows between the table header and the footer."""
    rows_top = PAGE_HEIGHT - MARGIN - HEADER_HEIGHT - cust_box_h - TABLE_HEADER_HEIGHT
    if not is_first_page:
        rows_top -= ITEM_ROW_HEIGHT  # "TOTAL B/F" row
    footer = FOOTER_HEIGHT_LAST if is_last_page else FOOTER_HEIGHT_CONTINUED
    return rows_top - (MARGIN + footer)


def paginate_line_heights(row_heights: list[float], cust_box_h: float) -> list[int]:
    """Split item rows into pages; returns the number of rows on each page.

    A page holds at most MAX_LINES_PAGE_ONE / MAX_LINES_SUBSEQUENT rows and
    never more height than fits above its footer. The final page needs the
    taller totals footer, so rows that fit only above the shorter
    "Continued..." footer move on to a further page instead of overprinting
    the GST summary.
    """
    counts = []
    start = 0
    is_first = True
    total = len(row_heights)
    while True:
        remaining = row_heights[start:]
        limit = MAX_LINES_PAGE_ONE if is_first else MAX_LINES_SUBSEQUENT
        if len(remaining) <= limit and sum(remaining) <= rows_area_height(cust_box_h, is_first, True) + 0.01:
            counts.append(len(remaining))
            return counts
        capacity = rows_area_height(cust_box_h, is_first, False) + 0.01
        used = 0.0
        taken = 0
        for height in remaining[:limit]:
            if taken and used + height > capacity:
                break
            used += height
            taken += 1
        if start + taken == total and taken > 1:
            # Everything fit only above the short footer: leave at least one
            # row for the final page, which carries the totals.
            taken -= 1
        counts.append(taken)
        start += taken
        is_first = False


def draw_product_description(
    c,
    lines: list[str],
    x: float,
    curr_row_top: float,
    leading: float = ITEM_LINE_LEADING,
    font_size: float = ITEM_ROW_FONT_SIZE,
):
    """Draw wrapped product description lines strictly at 9 pt."""
    c.setFont("Helvetica", font_size)
    y = curr_row_top - 9.5
    for line in lines:
        c.drawString(x + 4, y, line)
        y -= leading


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to compute and print total page numbers."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int):
        self.setStrokeColor(COLOR_BORDER)
        self.setLineWidth(0.5)

        if total_pages > 1:
            self.saveState()
            self.translate(INVOICE_X_OFFSET, INVOICE_Y_OFFSET)
            self.scale(INVOICE_SCALE, INVOICE_SCALE)
            self.setFont("Helvetica", 6)
            self.setFillColor(COLOR_TEXT)
            page_text = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(PAGE_WIDTH - MARGIN - 2, MARGIN + 2, page_text)
            self.restoreState()


def build_invoice_a5_pdf(invoice: Invoice, copy_type: str = "original", lines=None) -> bytes:
    """Build an A5 Landscape invoice PDF adhering to StockBill data and the visual reference.

    Args:
        invoice: Authoritative Invoice instance with prefetched line_items.
        copy_type: 'original', 'duplicate', 'reprint', or 'triplicate'
        lines: Optional explicit sequence of line items (defaults to invoice.line_items)
    """
    buffer = io.BytesIO()

    # Every shop detail comes from the invoice's snapshots or the Business
    # Profile, never from code. Issued (posted/cancelled) invoices use their
    # snapshots first; drafts use the current profile first. A value that
    # exists in neither prints as blank, never as another business's data.
    profile = BusinessProfile.objects.first()
    is_issued = invoice.state in (Invoice.STATE_POSTED, Invoice.STATE_CANCELLED)

    def profile_value(field):
        return (getattr(profile, field, "") or "") if profile else ""

    def seller_value(snapshot_field, profile_field):
        snapshot = getattr(invoice, snapshot_field, "") or ""
        current = profile_value(profile_field)
        return (snapshot or current) if is_issued else (current or snapshot)

    co_name = seller_value("seller_business_name_snapshot", "business_name")
    co_address = seller_value("seller_address_snapshot", "registered_address")
    co_gstin = seller_value("seller_gstin_snapshot", "gstin")
    co_state = seller_value("seller_state_snapshot", "state")
    co_state_code = seller_value("seller_state_code_snapshot", "state_code")
    co_phone = profile_value("phone") or profile_value("contact_details")
    co_email = profile_value("email")
    # Terms are contractual: issued invoices print the terms snapshotted when
    # they were posted; drafts print the current profile terms.
    terms_text = (invoice.terms_snapshot or "") if is_issued else profile_value("terms_and_conditions")

    cust_name = invoice.customer_name_snapshot or (invoice.customer.name if invoice.customer else "Walk-in Customer")
    cust_address = invoice.billing_address_snapshot or (invoice.customer.billing_address if invoice.customer else "")
    cust_phone = (invoice.customer.contact_info if invoice.customer else "")
    cust_gstin = invoice.customer_gstin_snapshot or (invoice.customer.gstin if invoice.customer else "") or "Unregistered"
    # A customer with no state is billed in the seller's state.
    cust_state = invoice.state_snapshot or (invoice.customer.state if invoice.customer else "") or co_state
    cust_state_code = invoice.customer_state_code_snapshot or (invoice.customer.state_code if invoice.customer else "") or co_state_code
    pos = invoice.place_of_supply or cust_state_code or co_state_code

    # Presentation copy labels
    copy_labels = {
        "original": "ORIGINAL",
        "duplicate": "DUPLICATE",
        "reprint": "REPRINT",
        "triplicate": "TRIPLICATE",
    }
    copy_badge = copy_labels.get(str(copy_type).lower().strip(), "ORIGINAL")

    if lines is None:
        lines = list(
            invoice.line_items.select_related("product")
            .prefetch_related("product__attribute_values__attribute_definition")
            .all()
        )
    else:
        lines = list(lines)

    c = NumberedCanvas(buffer, pagesize=A4)
    c.setViewerPreference("PrintScaling", "None")
    logo_reader = profile_logo_reader(profile)
    show_credit = bool(getattr(profile, "show_stockbill_credit", False))

    cumulative_amount = Decimal("0.00")
    running_sr = 1

    # Check whether supply has IGST
    has_igst = any(getattr(l, "igst_amount", Decimal("0")) > Decimal("0") for l in lines)

    # Product table columns budget (total width = 566.94 pt)
    # [Sr, Qty, Pack, Product, HSN, MRP, Rate/Piece, Dis, SGST, CGST, Amount]
    if has_igst:
        col_widths = [18, 48, 35, 166, 48, 42, 56, 30, 72, 51.94]
        col_headers = ["Sr.", "Qty.", "Pack", "Product Description", "HSN", "MRP", "Rate / Piece", "Dis", "IGST", "Amount"]
    else:
        col_widths = [18, 48, 35, 166, 48, 42, 56, 30, 36, 36, 51.94]
        col_headers = ["Sr.", "Qty.", "Pack", "Product Description", "HSN", "MRP", "Rate / Piece", "Dis", "SGST", "CGST", "Amount"]

    # Paginate by measured row height (wrapped product names make rows taller).
    # The Bill To box grows with the wrapped name/address, on every page.
    cust_layout = layout_customer_block(cust_name, cust_address)
    cust_box_h = cust_layout["box_h"]
    row_heights = [
        get_item_row_height(
            wrap_product_description(
                line.product_name_snapshot or (line.product.name if line.product else "Item"),
                col_widths[3] - 8.0,
                font_name="Helvetica",
                font_size=ITEM_ROW_FONT_SIZE,
            )
        )
        for line in lines
    ]
    pages_chunks = []
    start = 0
    for count in paginate_line_heights(row_heights, cust_box_h):
        pages_chunks.append(lines[start:start + count])
        start += count
    total_pages = len(pages_chunks)

    for page_idx, page_lines in enumerate(pages_chunks):
        c.saveState()
        c.translate(INVOICE_X_OFFSET, INVOICE_Y_OFFSET)
        c.scale(INVOICE_SCALE, INVOICE_SCALE)

        page_num = page_idx + 1
        is_first_page = (page_num == 1)
        is_last_page = (page_num == total_pages)

        top_y = PAGE_HEIGHT - MARGIN
        left_x = MARGIN
        right_x = PAGE_WIDTH - MARGIN
        bottom_y = MARGIN
        usable_w = PRINTABLE_WIDTH

        c.setStrokeColor(COLOR_BORDER)
        c.setLineWidth(0.75)
        c.rect(left_x, bottom_y, usable_w, top_y - bottom_y)

        # Optional "Generated by StockBill" (Business Profile setting): in the
        # margin below the invoice border, so it can never overlap the footer.
        if show_credit:
            c.saveState()
            c.setFont("Helvetica", 6)
            c.setFillColor(STOCKBILL_CREDIT_COLOR)
            c.drawCentredString(left_x + usable_w / 2, bottom_y - 8, STOCKBILL_CREDIT_TEXT)
            c.restoreState()

        # Subtle background watermark for cancelled or draft invoices
        if invoice.state in (Invoice.STATE_CANCELLED, Invoice.STATE_DRAFT):
            c.saveState()
            c.setFont("Helvetica-Bold", 45)
            if invoice.state == Invoice.STATE_CANCELLED:
                c.setFillColor(Color(0.85, 0.2, 0.2, alpha=0.10))
                wm_text = "CANCELLED"
            else:
                c.setFillColor(Color(0.5, 0.5, 0.5, alpha=0.10))
                wm_text = "DRAFT"
            c.translate(PAGE_WIDTH / 2, PAGE_HEIGHT / 2)
            c.rotate(28)
            c.drawCentredString(0, 0, wm_text)
            c.restoreState()

        # ------------------------------------------------------------------
        # 1. HEADER SECTION (Company Details + Invoice Metadata)
        # ------------------------------------------------------------------
        header_height = HEADER_HEIGHT
        header_bottom = top_y - header_height

        seller_w = usable_w * 0.58
        meta_w = usable_w - seller_w
        meta_x = left_x + seller_w

        c.line(meta_x, top_y, meta_x, header_bottom)
        c.line(left_x, header_bottom, right_x, header_bottom)

        # Left side: Logo + Seller identity
        text_start_x = left_x + 4
        if logo_reader is not None:
            try:
                logo_size = 46
                logo_y = top_y - logo_size - 5
                c.drawImage(logo_reader, left_x + 4, logo_y, width=logo_size, height=logo_size,
                            preserveAspectRatio=True, anchor="c", mask="auto")
                text_start_x = left_x + 4 + logo_size + 6
            except Exception:
                text_start_x = left_x + 4

        cur_y = top_y - 11
        c.setFillColor(COLOR_TEXT)
        # Full business name: shrinks to fit the seller column, then wraps.
        header_name = layout_header_name(co_name, (left_x + seller_w - 4) - text_start_x)
        c.setFont("Helvetica-Bold", header_name["font_size"])
        for i, name_line in enumerate(header_name["lines"]):
            if i:
                cur_y -= header_name["font_size"] + 1
            c.drawString(text_start_x, cur_y, name_line)
        # A two-line name leaves less room: tighten the lines below it.
        detail_leading = 8.5 if len(header_name["lines"]) <= 1 else 8.0

        c.setFont("Helvetica", 7)
        cur_y -= 9
        # Multi-line address — prefer newline splits (database format), fall back to comma grouping
        if "\n" in co_address:
            addr_lines = [l.strip() for l in co_address.split("\n") if l.strip()]
        else:
            addr_parts = [p.strip() for p in co_address.split(",") if p.strip()]
            if len(addr_parts) > 2:
                addr_lines = [", ".join(addr_parts[:2]), ", ".join(addr_parts[2:])]
            else:
                addr_lines = [", ".join(addr_parts)]
        for addr_line in addr_lines[:2]:  # max 2 lines in header
            c.drawString(text_start_x, cur_y, addr_line[:60])
            cur_y -= detail_leading

        # Only the details the profile has; no empty "Phone:" / "E-Mail:" labels.
        contact_parts = []
        if co_phone:
            contact_parts.append(f"Phone: {co_phone}")
        if co_email:
            contact_parts.append(f"E-Mail: {co_email}")
        if contact_parts:
            c.drawString(text_start_x, cur_y, " | ".join(contact_parts)[:60])
            cur_y -= detail_leading

        tax_parts = []
        if co_gstin:
            tax_parts.append(f"GSTIN: {co_gstin}")
        if co_state or co_state_code:
            tax_parts.append(f"State: {co_state} ({co_state_code})" if co_state_code else f"State: {co_state}")
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(text_start_x, cur_y, " | ".join(tax_parts))

        # Right side: Invoice Title + Copy Badge + Meta
        title_box_h = 16
        c.setFillColor(COLOR_HEADER_BG)
        c.rect(meta_x, top_y - title_box_h, meta_w, title_box_h, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 9)
        if invoice.state == Invoice.STATE_CANCELLED:
            c.drawString(meta_x + 6, top_y - 11, "CANCELLED INVOICE")
            c.drawRightString(right_x - 6, top_y - 11, "[ CANCELLED ]")
        elif invoice.state == Invoice.STATE_DRAFT:
            c.drawString(meta_x + 6, top_y - 11, "DRAFT INVOICE")
            c.drawRightString(right_x - 6, top_y - 11, "[ DRAFT ]")
        else:
            c.drawString(meta_x + 6, top_y - 11, "TAX INVOICE")
            c.drawRightString(right_x - 6, top_y - 11, f"[ {copy_badge} ]")

        meta_y = top_y - title_box_h - 10
        c.setFont("Helvetica-Bold", 8)
        c.drawString(meta_x + 6, meta_y, "Invoice No:")
        c.setFont("Helvetica-Bold", 8.5)
        # Drafts have no tax-invoice number until they are posted.
        c.drawString(meta_x + 56, meta_y, invoice.invoice_number or "DRAFT")

        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(right_x - 58, meta_y, "Date:")
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(right_x - 6, meta_y, invoice.invoice_date.strftime("%d-%m-%Y"))

        meta_y -= 12
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(meta_x + 6, meta_y, "Payment:")
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(meta_x + 56, meta_y, f"{invoice.payment_type.title()} ({invoice.payment_status.title()})")

        c.setFont("Helvetica-Bold", 7.5)
        c.drawRightString(right_x - 58, meta_y, "Due Date:")
        c.setFont("Helvetica", 7.5)
        c.drawRightString(right_x - 6, meta_y, invoice.invoice_date.strftime("%d-%m-%Y"))

        meta_y -= 12
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(meta_x + 6, meta_y, f"Place of Supply: {pos} - {cust_state}")

        # ------------------------------------------------------------------
        # 2. CUSTOMER BLOCK (Bill To)
        # ------------------------------------------------------------------
        # cust_box_h is computed before pagination (above).
        cust_bottom = header_bottom - cust_box_h
        c.line(left_x, cust_bottom, right_x, cust_bottom)

        cust_col1_w = usable_w * CUSTOMER_COLUMN_RATIO
        cust_col2_w = usable_w - cust_col1_w
        cust_col2_x = left_x + cust_col1_w
        c.line(cust_col2_x, header_bottom, cust_col2_x, cust_bottom)

        # Left: Customer Details (full name and address, wrapped to the column)
        cy = header_bottom - 9
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(left_x + 6, cy, "Bill To / Recipient:")
        c.setFont("Helvetica-Bold", cust_layout["name_size"])
        for i, name_line in enumerate(cust_layout["name_lines"]):
            if i:
                cy -= CUSTOMER_NAME_LEADING
            c.drawString(left_x + CUSTOMER_NAME_X, cy, name_line)

        cy -= 9
        c.setFont("Helvetica", 7.5)
        c.drawString(left_x + 6, cy, CUSTOMER_ADDRESS_LABEL.strip())
        c.setFont("Helvetica", cust_layout["addr_size"])
        addr_x = left_x + 6 + cust_layout["addr_label_w"]
        for i, addr_line in enumerate(cust_layout["addr_lines"]):
            if i:
                cy -= cust_layout["addr_leading"]
            c.drawString(addr_x, cy, addr_line)

        cy -= 8.5
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(left_x + 6, cy, f"GSTIN: {cust_gstin} | State: {cust_state} ({cust_state_code})" + (f" | Phone: {cust_phone}" if cust_phone else ""))

        # Right: Transport / Notes / Status
        cy_r = header_bottom - 9
        c.setFont("Helvetica", 7)
        c.drawString(cust_col2_x + 6, cy_r, "Reverse Charge:")
        c.setFont("Helvetica-Bold", 7)
        c.drawString(cust_col2_x + 72, cy_r, "No")

        cy_r -= 9
        c.setFont("Helvetica", 7)
        c.drawString(cust_col2_x + 6, cy_r, "Transport / Vehicle:")
        c.drawString(cust_col2_x + 78, cy_r, "-")

        cy_r -= 8.5
        if invoice.state == Invoice.STATE_CANCELLED:
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(COLOR_CANCELLED)
            c.drawString(cust_col2_x + 6, cy_r, f"Cancelled: {invoice.cancellation_reason or 'No reason provided'}"[:38])
            c.setFillColor(COLOR_TEXT)
        elif invoice.state == Invoice.STATE_DRAFT:
            c.setFont("Helvetica-Bold", 7)
            c.setFillColor(COLOR_DRAFT)
            c.drawString(cust_col2_x + 6, cy_r, "DRAFT - NOT FOR TAX PURPOSES")
            c.setFillColor(COLOR_TEXT)
        elif invoice.notes:
            c.setFont("Helvetica", 7)
            c.drawString(cust_col2_x + 6, cy_r, f"Notes: {invoice.notes[:35]}")

        # ------------------------------------------------------------------
        # 3. PRODUCT TABLE HEADERS
        # ------------------------------------------------------------------
        tbl_top = cust_bottom
        th_height = TABLE_HEADER_HEIGHT
        th_bottom = tbl_top - th_height

        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, th_bottom, usable_w, th_height, fill=1, stroke=1)

        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 7.5)
        x_curr = left_x
        for i, (h_title, w) in enumerate(zip(col_headers, col_widths)):
            if i == 3:  # Product Description
                c.drawString(x_curr + 4, th_bottom + 4, h_title)
            elif i in [0, 2, 4]:  # Sr, Pack, HSN
                c.drawCentredString(x_curr + (w / 2), th_bottom + 4, h_title)
            else:
                c.drawRightString(x_curr + w - 4, th_bottom + 4, h_title)

            x_curr += w
            if i < len(col_widths) - 1:
                c.saveState()
                c.setStrokeColor(HexColor("#555555"))
                c.setLineWidth(0.35)
                c.line(x_curr, tbl_top, x_curr, th_bottom)
                c.restoreState()

        # ------------------------------------------------------------------
        # 4. PRODUCT TABLE ROWS
        # ------------------------------------------------------------------
        curr_row_top = th_bottom

        if not is_first_page:
            bf_row_h = ITEM_ROW_HEIGHT
            bf_bottom = curr_row_top - bf_row_h
            c.setFont("Helvetica-Bold", 8.0)
            c.drawString(left_x + col_widths[0] + col_widths[1] + col_widths[2] + 4, bf_bottom + 3.5, "TOTAL B/F")
            c.drawRightString(right_x - 4, bf_bottom + 3.5, f"{cumulative_amount:.2f}")
            c.line(left_x, bf_bottom, right_x, bf_bottom)
            curr_row_top = bf_bottom

        page_subtotal = Decimal("0.00")

        for line in page_lines:
            p_name = line.product_name_snapshot or (line.product.name if line.product else "Item")
            desc_lines = wrap_product_description(p_name, col_widths[3] - 8.0, font_name="Helvetica", font_size=ITEM_ROW_FONT_SIZE)
            row_height = get_item_row_height(desc_lines)
            row_bottom = curr_row_top - row_height

            qty_disp, pack_disp = format_qty_presentation(line)
            hsn_disp = line.hsn_sac_snapshot or "-"
            mrp_val = getattr(line, "mrp_snapshot", None) or getattr(line.product, "mrp", Decimal("0.00")) or Decimal("0.00")
            rate_val = line.rate_charged  # per piece rate
            dis_val = line.discount_amount
            sgst_rate_str = f"{line.sgst_rate:.2f}%" if line.sgst_rate else "0.00%"
            cgst_rate_str = f"{line.cgst_rate:.2f}%" if line.cgst_rate else "0.00%"
            igst_rate_str = f"{line.igst_rate:.2f}%" if line.igst_rate else "0.00%"
            line_total_val = line.line_total

            page_subtotal += line_total_val
            cumulative_amount += line_total_val

            row_baseline = curr_row_top - 9.5
            c.setFont("Helvetica", ITEM_ROW_FONT_SIZE)
            x_curr = left_x

            # Sr.
            c.drawCentredString(x_curr + (col_widths[0] / 2), row_baseline, str(running_sr))
            x_curr += col_widths[0]

            # Qty.
            c.drawRightString(x_curr + col_widths[1] - 4, row_baseline, qty_disp)
            x_curr += col_widths[1]

            # Pack
            c.drawCentredString(x_curr + (col_widths[2] / 2), row_baseline, pack_disp)
            x_curr += col_widths[2]

            # Product Description (strictly 9 pt, wrapped naturally into lines)
            draw_product_description(c, desc_lines, x_curr, curr_row_top, leading=ITEM_LINE_LEADING, font_size=ITEM_ROW_FONT_SIZE)
            x_curr += col_widths[3]

            # HSN
            c.drawCentredString(x_curr + (col_widths[4] / 2), row_baseline, hsn_disp[:10])
            x_curr += col_widths[4]

            # MRP
            c.drawRightString(x_curr + col_widths[5] - 4, row_baseline, f"{mrp_val:.2f}")
            x_curr += col_widths[5]

            # Rate / Piece
            c.drawRightString(x_curr + col_widths[6] - 4, row_baseline, f"{rate_val:.2f}")
            x_curr += col_widths[6]

            # Dis
            c.drawRightString(x_curr + col_widths[7] - 4, row_baseline, f"{dis_val:.2f}")
            x_curr += col_widths[7]

            if has_igst:
                # IGST
                c.drawRightString(x_curr + col_widths[8] - 4, row_baseline, igst_rate_str)
                x_curr += col_widths[8]
            else:
                # SGST
                c.drawRightString(x_curr + col_widths[8] - 4, row_baseline, sgst_rate_str)
                x_curr += col_widths[8]

                # CGST
                c.drawRightString(x_curr + col_widths[9] - 4, row_baseline, cgst_rate_str)
                x_curr += col_widths[9]

            # Amount
            c.drawRightString(x_curr + col_widths[-1] - 4, row_baseline, f"{line_total_val:.2f}")

            curr_row_top = row_bottom
            running_sr += 1

        # ------------------------------------------------------------------
        # 5. FOOTER & SUMMARY SECTION
        # ------------------------------------------------------------------
        footer_height = FOOTER_HEIGHT_LAST if is_last_page else FOOTER_HEIGHT_CONTINUED
        footer_top = bottom_y + footer_height

        # Draw thin vertical column separators throughout the entire item table body down to footer
        c.saveState()
        c.setStrokeColor(HexColor("#555555"))
        c.setLineWidth(0.35)
        x_grid = left_x
        for w in col_widths[:-1]:
            x_grid += w
            c.line(x_grid, th_bottom, x_grid, footer_top)
        c.restoreState()

        c.setStrokeColor(COLOR_BORDER)
        c.setLineWidth(0.75)
        c.line(left_x, footer_top, right_x, footer_top)

        gst_w = usable_w * 0.58
        totals_w = usable_w - gst_w
        totals_x = left_x + gst_w

        words_h = 13
        words_bot = bottom_y + 42
        words_top = words_bot + words_h

        c.line(totals_x, footer_top, totals_x, words_top)

        # Continuation Page Footer
        if not is_last_page:
            c.setFont("Helvetica-Bold", 8.5)
            c.drawString(totals_x + 12, footer_top - 25, f"Continued... Page {page_num + 1}")
            c.setFont("Helvetica-Bold", 7.5)
            c.drawString(totals_x + 12, footer_top - 40, f"Page Total: Rs. {page_subtotal:.2f}")

            c.line(left_x, words_top, right_x, words_top)
            c.line(left_x, words_bot, right_x, words_bot)
            c.setFont("Helvetica-Oblique", 7)
            c.drawString(left_x + 6, words_bot + 4, f"(Continued on Page {page_num + 1})")

            # Bottom 3 boxes
            draw_footer_boxes(c, left_x=left_x, right_x=right_x, bottom_y=bottom_y, words_bot=words_bot,
                              usable_w=usable_w, terms_text=terms_text, co_name=co_name)

            c.restoreState()
            c.showPage()
            continue

        # ------------------------------------------------------------------
        # FINAL PAGE FOOTER: GST Summary + Totals + Words + Signatures
        # ------------------------------------------------------------------
        gst_classes = {}
        for l in lines:
            rate_key = l.tax_rate
            if rate_key not in gst_classes:
                gst_classes[rate_key] = {
                    "taxable": Decimal("0.00"),
                    "disc": Decimal("0.00"),
                    "sgst": Decimal("0.00"),
                    "cgst": Decimal("0.00"),
                    "igst": Decimal("0.00"),
                    "total_gst": Decimal("0.00"),
                }
            tx_val = getattr(l, "taxable_value_snapshot", None)
            if tx_val is None:
                tx_val = l.line_total - l.tax_amount
            gst_classes[rate_key]["taxable"] += tx_val
            gst_classes[rate_key]["disc"] += l.discount_amount
            gst_classes[rate_key]["sgst"] += getattr(l, "sgst_amount", Decimal("0"))
            gst_classes[rate_key]["cgst"] += getattr(l, "cgst_amount", Decimal("0"))
            gst_classes[rate_key]["igst"] += getattr(l, "igst_amount", Decimal("0"))
            gst_classes[rate_key]["total_gst"] += l.tax_amount

        # GST table headers & columns
        if has_igst:
            gst_cols = [50, 65, 45, 80, 88.82]
            gst_hdrs = ["CLASS", "TAXABLE", "DISC.", "IGST", "TOTAL GST"]
        else:
            gst_cols = [50, 65, 45, 42, 42, 84.82]
            gst_hdrs = ["CLASS", "TAXABLE", "DISC.", "SGST", "CGST", "TOTAL GST"]

        gh_h = 11
        gh_bot = footer_top - gh_h
        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, gh_bot, gst_w, gh_h, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 6.5)

        gx = left_x
        for i, (gh, gw) in enumerate(zip(gst_hdrs, gst_cols)):
            if i == 0:
                c.drawString(gx + 3, gh_bot + 3.5, gh)
            else:
                c.drawRightString(gx + gw - 3, gh_bot + 3.5, gh)
            gx += gw

        gy = gh_bot
        gr_h = 9
        sum_taxable = Decimal("0.00")
        sum_disc = Decimal("0.00")
        sum_sgst = Decimal("0.00")
        sum_cgst = Decimal("0.00")
        sum_igst = Decimal("0.00")
        sum_tot_gst = Decimal("0.00")

        sorted_rates = sorted(gst_classes.keys())
        for r in sorted_rates:
            data = gst_classes[r]
            sum_taxable += data["taxable"]
            sum_disc += data["disc"]
            sum_sgst += data["sgst"]
            sum_cgst += data["cgst"]
            sum_igst += data["igst"]
            sum_tot_gst += data["total_gst"]

            gy -= gr_h
            c.setFont("Helvetica", 6.5)
            gx = left_x

            c.drawString(gx + 3, gy + 2.5, f"GST {r:.2f}%")
            gx += gst_cols[0]
            c.drawRightString(gx + gst_cols[1] - 3, gy + 2.5, f"{data['taxable']:.2f}")
            gx += gst_cols[1]
            c.drawRightString(gx + gst_cols[2] - 3, gy + 2.5, f"{data['disc']:.2f}")
            gx += gst_cols[2]
            if has_igst:
                c.drawRightString(gx + gst_cols[3] - 3, gy + 2.5, f"{data['igst']:.2f}")
                gx += gst_cols[3]
            else:
                c.drawRightString(gx + gst_cols[3] - 3, gy + 2.5, f"{data['sgst']:.2f}")
                gx += gst_cols[3]
                c.drawRightString(gx + gst_cols[4] - 3, gy + 2.5, f"{data['cgst']:.2f}")
                gx += gst_cols[4]
            c.drawRightString(gx + gst_cols[-1] - 3, gy + 2.5, f"{data['total_gst']:.2f}")

        gy -= gr_h
        c.line(left_x, gy + gr_h, totals_x, gy + gr_h)
        c.setFont("Helvetica-Bold", 6.5)
        gx = left_x
        c.drawString(gx + 3, gy + 2.5, "TOTAL")
        gx += gst_cols[0]
        c.drawRightString(gx + gst_cols[1] - 3, gy + 2.5, f"{sum_taxable:.2f}")
        gx += gst_cols[1]
        c.drawRightString(gx + gst_cols[2] - 3, gy + 2.5, f"{sum_disc:.2f}")
        gx += gst_cols[2]
        if has_igst:
            c.drawRightString(gx + gst_cols[3] - 3, gy + 2.5, f"{sum_igst:.2f}")
            gx += gst_cols[3]
        else:
            c.drawRightString(gx + gst_cols[3] - 3, gy + 2.5, f"{sum_sgst:.2f}")
            gx += gst_cols[3]
            c.drawRightString(gx + gst_cols[4] - 3, gy + 2.5, f"{sum_cgst:.2f}")
            gx += gst_cols[4]
        c.drawRightString(gx + gst_cols[-1] - 3, gy + 2.5, f"{sum_tot_gst:.2f}")

        # Right side: Invoice Totals
        ty = footer_top - 10
        tr_h = 9
        labels = [
            ("SUB TOTAL (TAXABLE)", f"{sum_taxable:.2f}"),
        ]
        if sum_disc > Decimal("0.00"):
            labels.append(("TOTAL DISCOUNT", f"{sum_disc:.2f}"))
        if has_igst:
            labels.append(("IGST PAYABLE", f"{sum_igst:.2f}"))
        else:
            labels.append(("SGST PAYABLE", f"{sum_sgst:.2f}"))
            labels.append(("CGST PAYABLE", f"{sum_cgst:.2f}"))

        # Check round-off
        computed_grand = sum_taxable + sum_tot_gst
        round_off = invoice.total_amount - computed_grand
        if abs(round_off) >= Decimal("0.01"):
            labels.append(("ROUND OFF", f"{round_off:+.2f}"))

        for lbl, val in labels:
            c.setFont("Helvetica-Bold", 7)
            c.drawString(totals_x + 6, ty + 2, lbl)
            c.setFont("Helvetica-Bold", 7.5)
            c.drawRightString(right_x - 6, ty + 2, val)
            ty -= tr_h

        # Grand Total Box
        c.setFillColor(COLOR_HEADER_BG)
        c.rect(totals_x, words_top, totals_w, (ty + 8) - words_top, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(totals_x + 6, words_top + 4, "GRAND TOTAL")
        c.drawRightString(right_x - 6, words_top + 4, f"Rs. {invoice.total_amount:.2f}")

        # Words bar
        c.line(left_x, words_top, right_x, words_top)
        c.line(left_x, words_bot, right_x, words_bot)

        c.setFont("Helvetica-Bold", 7.5)
        words_str = amount_to_words(invoice.total_amount)
        c.drawString(left_x + 6, words_bot + 4, f"Amount in Words: {words_str}")

        # Bottom 3 boxes
        draw_footer_boxes(c, left_x=left_x, right_x=right_x, bottom_y=bottom_y, words_bot=words_bot,
                          usable_w=usable_w, terms_text=terms_text, co_name=co_name)

        c.restoreState()
        c.showPage()

    c.save()
    return buffer.getvalue()
