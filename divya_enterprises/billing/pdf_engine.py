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
import os
from pathlib import Path

from django.conf import settings
from reportlab.lib.colors import HexColor, black, white, Color
from reportlab.lib.pagesizes import A4, A5, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .models import BusinessProfile, Invoice


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


def _resolve_logo_path() -> str | None:
    """Find the Divya Enterprises logo file on disk reliably."""
    candidate_paths = [
        Path(__file__).resolve().parent / "static" / "billing" / "images" / "logo.jpg",
        Path(settings.BASE_DIR) / "billing" / "static" / "billing" / "images" / "logo.jpg",
        Path(settings.BASE_DIR) / "static" / "billing" / "images" / "logo.jpg",
    ]
    for p in candidate_paths:
        if p.exists() and p.is_file():
            return str(p)
    return None


# Item row styling constants
ITEM_ROW_FONT_SIZE = 9.0   # Visually prominent ERP item font size (9.0 pt strictly maintained)
ITEM_ROW_HEIGHT = 13.0     # Standard single-line row height
ITEM_LINE_LEADING = 10.0   # Vertical spacing for wrapped 9 pt lines


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

    # Use invoice snapshots as authoritative source for posted invoices.
    # BusinessProfile is only a fallback for drafts or missing snapshots.
    profile = BusinessProfile.objects.first()
    is_posted = invoice.state == Invoice.STATE_POSTED

    default_company = "DIVYA ENTERPRISES"
    default_address = "GROUND FLOOR SHOP NO 30 SHAH ARCADE\n3 RANI SATI MARG MALAD EAST MUMBAI 400097"
    default_phone = "9930008633"
    default_email = "divyaenterprises2501@gmail.com"
    default_gstin = "27ECNPS6389P1Z5"
    default_state = "Maharashtra"
    default_state_code = "27"
    default_terms = (
        "1. Goods once sold will not be taken back or exchanged.\n"
        "2. Bills not paid on due date will attract 24% interest p.a.\n"
        "3. Subject to Mumbai Jurisdiction."
    )

    if is_posted:
        co_name = invoice.seller_business_name_snapshot or (profile.business_name if (profile and profile.business_name) else default_company)
        co_address = invoice.seller_address_snapshot or (profile.registered_address if (profile and profile.registered_address) else default_address)
        co_phone = (profile.phone if (profile and profile.phone) else None) or (profile.contact_details if (profile and profile.contact_details) else None) or default_phone
        co_email = (profile.email if (profile and profile.email) else None) or default_email
        co_gstin = invoice.seller_gstin_snapshot or (profile.gstin if (profile and profile.gstin) else default_gstin)
        co_state = invoice.seller_state_snapshot or (profile.state if (profile and profile.state) else default_state)
        co_state_code = invoice.seller_state_code_snapshot or (profile.state_code if (profile and profile.state_code) else default_state_code)
        terms_text = (profile.terms_and_conditions if (profile and profile.terms_and_conditions) else None) or default_terms
    else:
        co_name = (profile.business_name if (profile and profile.business_name) else None) or invoice.seller_business_name_snapshot or default_company
        co_address = (profile.registered_address if (profile and profile.registered_address) else None) or invoice.seller_address_snapshot or default_address
        co_phone = (profile.phone if (profile and profile.phone) else None) or (profile.contact_details if (profile and profile.contact_details) else None) or default_phone
        co_email = (profile.email if (profile and profile.email) else None) or default_email
        co_gstin = (profile.gstin if (profile and profile.gstin) else None) or invoice.seller_gstin_snapshot or default_gstin
        co_state = (profile.state if (profile and profile.state) else None) or invoice.seller_state_snapshot or default_state
        co_state_code = (profile.state_code if (profile and profile.state_code) else None) or invoice.seller_state_code_snapshot or default_state_code
        terms_text = (profile.terms_and_conditions if (profile and profile.terms_and_conditions) else None) or default_terms

    cust_name = invoice.customer_name_snapshot or (invoice.customer.name if invoice.customer else "Walk-in Customer")
    cust_address = invoice.billing_address_snapshot or (invoice.customer.billing_address if invoice.customer else "")
    cust_phone = (invoice.customer.contact_info if invoice.customer else "")
    cust_gstin = invoice.customer_gstin_snapshot or (invoice.customer.gstin if invoice.customer else "") or "Unregistered"
    cust_state = invoice.state_snapshot or (invoice.customer.state if invoice.customer else "") or "Maharashtra"
    cust_state_code = invoice.customer_state_code_snapshot or (invoice.customer.state_code if invoice.customer else "") or "27"
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

    # Multi-page budgets for A5 landscape
    MAX_LINES_SINGLE_PAGE = 10
    MAX_LINES_PAGE_ONE = 13
    MAX_LINES_SUBSEQUENT = 14

    pages_chunks = []
    if len(lines) <= MAX_LINES_SINGLE_PAGE:
        pages_chunks.append(lines)
    else:
        pages_chunks.append(lines[:MAX_LINES_PAGE_ONE])
        remaining = lines[MAX_LINES_PAGE_ONE:]
        while remaining:
            pages_chunks.append(remaining[:MAX_LINES_SUBSEQUENT])
            remaining = remaining[MAX_LINES_SUBSEQUENT:]

    total_pages = len(pages_chunks)
    c = NumberedCanvas(buffer, pagesize=A4)
    c.setViewerPreference("PrintScaling", "None")
    logo_path = _resolve_logo_path()

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
        header_height = 56
        header_bottom = top_y - header_height

        seller_w = usable_w * 0.58
        meta_w = usable_w - seller_w
        meta_x = left_x + seller_w

        c.line(meta_x, top_y, meta_x, header_bottom)
        c.line(left_x, header_bottom, right_x, header_bottom)

        # Left side: Logo + Seller identity
        text_start_x = left_x + 4
        if logo_path:
            try:
                logo_size = 46
                logo_y = top_y - logo_size - 5
                c.drawImage(logo_path, left_x + 4, logo_y, width=logo_size, height=logo_size, preserveAspectRatio=True)
                text_start_x = left_x + 4 + logo_size + 6
            except Exception:
                text_start_x = left_x + 4

        cur_y = top_y - 11
        c.setFont("Helvetica-Bold", 11)
        c.setFillColor(COLOR_TEXT)
        c.drawString(text_start_x, cur_y, co_name.upper()[:40])

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
            cur_y -= 8.5

        contact_line = ""
        if co_phone:
            contact_line += f"Phone: {co_phone}"
        if co_email:
            contact_line += f" | E-Mail: {co_email}"
        if contact_line:
            c.drawString(text_start_x, cur_y, contact_line[:60])
            cur_y -= 8.5

        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(text_start_x, cur_y, f"GSTIN: {co_gstin} | State: {co_state} ({co_state_code})")

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
        c.drawString(meta_x + 56, meta_y, str(invoice.invoice_number))

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
        cust_box_h = 30
        cust_bottom = header_bottom - cust_box_h
        c.line(left_x, cust_bottom, right_x, cust_bottom)

        cust_col1_w = usable_w * 0.60
        cust_col2_w = usable_w - cust_col1_w
        cust_col2_x = left_x + cust_col1_w
        c.line(cust_col2_x, header_bottom, cust_col2_x, cust_bottom)

        # Left: Customer Details
        cy = header_bottom - 9
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(left_x + 6, cy, "Bill To / Recipient:")
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(left_x + 78, cy, cust_name[:45])

        cy -= 9
        c.setFont("Helvetica", 7.5)
        addr_line = cust_address[:75]
        c.drawString(left_x + 6, cy, f"Address: {addr_line}" if addr_line else "Address: -")

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
        th_height = 14
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
        footer_height = 115 if is_last_page else 85
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
            b_w1 = usable_w * 0.45
            b_w2 = usable_w * 0.25
            b_w3 = usable_w - b_w1 - b_w2

            c.line(left_x + b_w1, words_bot, left_x + b_w1, bottom_y)
            c.line(left_x + b_w1 + b_w2, words_bot, left_x + b_w1 + b_w2, bottom_y)

            c.setFont("Helvetica-Bold", 7)
            c.drawString(left_x + 4, words_bot - 8, "Terms & Conditions")
            c.setFont("Helvetica", 6)
            t_lines = terms_text.splitlines()
            ty = words_bot - 16
            for tl in t_lines[:3]:
                c.drawString(left_x + 4, ty, tl[:50])
                ty -= 6

            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(left_x + b_w1 + (b_w2 / 2), bottom_y + 6, "Receiver's Signature")

            c.setFont("Helvetica-Bold", 7)
            c.drawString(left_x + b_w1 + b_w2 + 6, words_bot - 8, f"For {co_name[:28]}")
            c.setFont("Helvetica-Bold", 7.5)
            c.drawCentredString(right_x - (b_w3 / 2), bottom_y + 6, "Authorised Signatory")

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
        b_w1 = usable_w * 0.45
        b_w2 = usable_w * 0.25
        b_w3 = usable_w - b_w1 - b_w2

        c.line(left_x + b_w1, words_bot, left_x + b_w1, bottom_y)
        c.line(left_x + b_w1 + b_w2, words_bot, left_x + b_w1 + b_w2, bottom_y)

        c.setFont("Helvetica-Bold", 7)
        c.drawString(left_x + 4, words_bot - 8, "Terms & Conditions")
        c.setFont("Helvetica", 6)
        t_lines = terms_text.splitlines()
        ty = words_bot - 16
        for tl in t_lines[:3]:
            c.drawString(left_x + 4, ty, tl[:50])
            ty -= 6

        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(left_x + b_w1 + (b_w2 / 2), bottom_y + 6, "Receiver's Signature")

        c.setFont("Helvetica-Bold", 7)
        c.drawString(left_x + b_w1 + b_w2 + 6, words_bot - 8, f"For {co_name[:28]}")
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(right_x - (b_w3 / 2), bottom_y + 6, "Authorised Signatory")

        c.restoreState()
        c.showPage()

    c.save()
    return buffer.getvalue()
