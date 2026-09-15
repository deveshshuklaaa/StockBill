"""A5 Physical Laser Printing Engine for StockBill Sales Invoices.

Target specifications:
- Paper: A5 Portrait (148 mm x 210 mm)
- Margins: 5 mm (printable width 138 mm / 391.2 pt)
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
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

from .models import BusinessProfile, Invoice


# --- COLOR PALETTE (matching visual reference) ---
COLOR_BORDER = HexColor("#000000")
COLOR_HEADER_BG = HexColor("#D8EFF6")  # Light cyan accent
COLOR_MUTED_BG = HexColor("#F5F5F5")
COLOR_TEXT = HexColor("#000000")
COLOR_DRAFT = HexColor("#888888")
COLOR_CANCELLED = HexColor("#C0392B")

# --- A5 DIMENSIONS ---
PAGE_WIDTH, PAGE_HEIGHT = A5  # 148 mm, 210 mm
MARGIN = 5 * mm  # 14.17 pt
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * MARGIN)  # 138 mm (~391.18 pt)


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


def format_qty_presentation(line) -> tuple[str, str]:
    """Format quantity and pack strings according to StockBill unit rules.

    Returns:
        (qty_display, pack_display)
    """
    sales_unit = str(getattr(line, "sales_unit_name", "") or "").strip().lower()
    conversion = getattr(line, "conversion_factor", None) or Decimal("1.000")
    raw_qty = getattr(line, "quantity", Decimal("0"))
    base_qty = getattr(line, "base_quantity", None) or (raw_qty * conversion)

    def clean_num(d):
        d = Decimal(str(d))
        if d == d.to_integral_value():
            return str(int(d))
        return f"{d:.3f}".rstrip("0").rstrip(".")

    if sales_unit == "master box":
        box_str = clean_num(raw_qty)
        pack_str = clean_num(conversion)
        base_str = clean_num(base_qty)
        return f"{box_str} Box", pack_str
    else:
        qty_str = clean_num(raw_qty)
        return f"{qty_str} pcs", "-"


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
            self.setFont("Helvetica", 6)
            self.setFillColor(COLOR_TEXT)
            page_text = f"Page {self._pageNumber} of {total_pages}"
            self.drawRightString(PAGE_WIDTH - MARGIN - 2, MARGIN + 2, page_text)


def build_invoice_a5_pdf(invoice: Invoice, copy_type: str = "original", lines=None) -> bytes:
    """Build an A5 invoice PDF adhering to StockBill data and the visual reference.

    Args:
        invoice: Authoritative Invoice instance with prefetched line_items.
        copy_type: 'original', 'duplicate', or 'triplicate'
        lines: Optional explicit sequence of line items (defaults to invoice.line_items)
    """
    buffer = io.BytesIO()

    profile = BusinessProfile.objects.first()

    co_name = (profile.business_name if profile else None) or invoice.seller_business_name_snapshot or "DIVYA ENTERPRISES"
    co_address = (profile.registered_address if profile else None) or invoice.seller_address_snapshot or ""
    co_phone = (profile.phone if profile else None) or (profile.contact_details if profile else None) or ""
    co_email = (profile.email if profile else None) or ""
    co_gstin = (profile.gstin if profile else None) or invoice.seller_gstin_snapshot or ""
    terms_text = (profile.terms_and_conditions if profile else None) or (
        "Goods once sold will not be taken back or exchanged.\nBills not paid due date will attract 24% interest."
    )

    cust_name = invoice.customer_name_snapshot or (invoice.customer.name if invoice.customer else "Walk-in Customer")
    cust_address = invoice.billing_address_snapshot or (invoice.customer.billing_address if invoice.customer else "")
    cust_phone = (invoice.customer.contact_info if invoice.customer else "")
    cust_gstin = invoice.customer_gstin_snapshot or (invoice.customer.gstin if invoice.customer else "") or "Unregistered"
    pos = invoice.place_of_supply or invoice.seller_state_code_snapshot or "27"

    copy_labels = {
        "original": "ORIGINAL FOR RECIPIENT",
        "duplicate": "DUPLICATE FOR TRANSPORTER",
        "triplicate": "TRIPLICATE FOR SUPPLIER",
    }
    copy_badge = copy_labels.get(str(copy_type).lower().strip(), "ORIGINAL FOR RECIPIENT")

    if lines is None:
        lines = list(invoice.line_items.select_related("product").all())
    else:
        lines = list(lines)

    MAX_LINES_SINGLE_PAGE = 12
    MAX_LINES_PAGE_ONE = 15
    MAX_LINES_SUBSEQUENT = 16

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
    c = NumberedCanvas(buffer, pagesize=A5)
    logo_path = _resolve_logo_path()

    cumulative_amount = Decimal("0.00")
    running_sr = 1

    for page_idx, page_lines in enumerate(pages_chunks):
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

        # 1. HEADER SECTION
        header_height = 54
        header_bottom = top_y - header_height

        seller_w = usable_w * 0.52
        cust_w = usable_w * 0.48
        cust_x = left_x + seller_w

        c.line(cust_x, top_y, cust_x, header_bottom)
        c.line(left_x, header_bottom, right_x, header_bottom)

        text_start_x = left_x + 3
        logo_w = 0
        if logo_path:
            try:
                logo_size = 38
                logo_y = top_y - logo_size - 6
                c.drawImage(logo_path, left_x + 3, logo_y, width=logo_size, height=logo_size, preserveAspectRatio=True)
                logo_w = logo_size + 4
                text_start_x = left_x + 3 + logo_w
            except Exception:
                logo_w = 0
                text_start_x = left_x + 3

        cur_y = top_y - 9
        c.setFont("Helvetica-Bold", 8)
        c.setFillColor(COLOR_TEXT)
        c.drawString(text_start_x, cur_y, co_name[:34])

        c.setFont("Helvetica", 5.5)
        cur_y -= 8
        addr_line1 = co_address[:42]
        addr_line2 = co_address[42:84]
        if addr_line1:
            c.drawString(text_start_x, cur_y, addr_line1)
            cur_y -= 7
        if addr_line2:
            c.drawString(text_start_x, cur_y, addr_line2)
            cur_y -= 7

        contact_parts = []
        if co_phone:
            contact_parts.append(f"Phone: {co_phone}")
        if co_email:
            contact_parts.append(f"E-Mail: {co_email}")
        if contact_parts:
            c.drawString(text_start_x, cur_y, " | ".join(contact_parts)[:45])
            cur_y -= 7

        if co_gstin:
            c.setFont("Helvetica-Bold", 6)
            c.drawString(text_start_x, cur_y, f"GSTIN: {co_gstin}")

        cur_y = top_y - 9
        c.setFont("Helvetica-Bold", 8)
        c.drawString(cust_x + 4, cur_y, f"M/s {cust_name}"[:32])

        c.setFont("Helvetica", 5.5)
        cur_y -= 8
        if cust_address:
            cust_addr1 = cust_address[:40]
            cust_addr2 = cust_address[40:80]
            c.drawString(cust_x + 4, cur_y, cust_addr1)
            cur_y -= 7
            if cust_addr2:
                c.drawString(cust_x + 4, cur_y, cust_addr2)
                cur_y -= 7

        if cust_phone:
            c.drawString(cust_x + 4, cur_y, f"Ph.No.: {cust_phone}")
            cur_y -= 7

        c.setFont("Helvetica-Bold", 6)
        c.drawString(cust_x + 4, cur_y, f"GSTIN: {cust_gstin}")
        cur_y -= 7
        c.setFont("Helvetica", 5.5)
        c.drawString(cust_x + 4, cur_y, f"Place of Supply: {pos}")

        # 2. INVOICE META BANNER
        meta_height = 24
        meta_bottom = header_bottom - meta_height
        c.line(left_x, meta_bottom, right_x, meta_bottom)

        title_w = usable_w * 0.45
        meta_x = left_x + title_w
        c.line(meta_x, header_bottom, meta_x, meta_bottom)

        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, meta_bottom, title_w, meta_height, fill=1, stroke=0)

        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(left_x + (title_w / 2), meta_bottom + 12, "GST INVOICE")

        c.setFont("Helvetica-Bold", 5.5)
        c.drawCentredString(left_x + (title_w / 2), meta_bottom + 4, f"[{copy_badge}]")

        meta_col1 = meta_x + 4
        meta_col2 = meta_x + (usable_w - title_w) * 0.52

        c.setFont("Helvetica", 6)
        c.drawString(meta_col1, meta_bottom + 14, "Invoice No.:")
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(meta_col1 + 42, meta_bottom + 14, str(invoice.invoice_number))

        c.setFont("Helvetica", 6)
        c.drawString(meta_col2, meta_bottom + 14, "Date:")
        c.setFont("Helvetica-Bold", 6)
        c.drawString(meta_col2 + 22, meta_bottom + 14, invoice.invoice_date.strftime("%d-%m-%Y"))

        c.setFont("Helvetica", 6)
        c.drawString(meta_col1, meta_bottom + 4, "Sales Man:")
        c.drawString(meta_col1 + 42, meta_bottom + 4, "-")

        c.drawString(meta_col2, meta_bottom + 4, "Due Date:")
        c.drawString(meta_col2 + 35, meta_bottom + 4, invoice.invoice_date.strftime("%d-%m-%Y"))

        if invoice.state == Invoice.STATE_CANCELLED:
            c.saveState()
            c.setFillColor(COLOR_CANCELLED)
            c.setFont("Helvetica-Bold", 8)
            reason_txt = f"CANCELLED: {invoice.cancellation_reason or 'No reason provided'}"
            c.drawCentredString(left_x + (usable_w / 2), top_y - 8, reason_txt[:80])
            c.restoreState()
        elif invoice.state == Invoice.STATE_DRAFT:
            c.saveState()
            c.setFillColor(COLOR_DRAFT)
            c.setFont("Helvetica-Bold", 8)
            c.drawCentredString(left_x + (usable_w / 2), top_y - 8, "DRAFT - NOT FOR TAX PURPOSES")
            c.restoreState()

        # 3. PRODUCT TABLE COLUMNS
        col_widths = [14, 42, 25, 103, 36, 25, 31, 20, 23, 23, 49]
        col_headers = ["Sn.", "Qty.", "Pack", "Product", "HSN", "MRP", "Rate", "Dis", "SGST", "CGST", "Amount"]

        tbl_top = meta_bottom
        th_height = 13
        th_bottom = tbl_top - th_height

        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, th_bottom, usable_w, th_height, fill=1, stroke=1)

        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 6)
        x_curr = left_x
        for i, (h_title, w) in enumerate(zip(col_headers, col_widths)):
            if i == 3:
                c.drawString(x_curr + 3, th_bottom + 4, h_title)
            elif i in [0, 2, 4, 8, 9]:
                c.drawCentredString(x_curr + (w / 2), th_bottom + 4, h_title)
            else:
                c.drawRightString(x_curr + w - 3, th_bottom + 4, h_title)

            x_curr += w
            if i < len(col_widths) - 1:
                c.line(x_curr, tbl_top, x_curr, th_bottom)

        # 4. PRODUCT TABLE ROWS
        row_height = 12.5
        curr_row_top = th_bottom

        if not is_first_page:
            bf_bottom = curr_row_top - row_height
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(left_x + col_widths[0] + col_widths[1] + col_widths[2] + 4, bf_bottom + 3.5, "TOTAL B/F")
            c.drawRightString(right_x - 3, bf_bottom + 3.5, f"{cumulative_amount:.2f}")
            c.line(left_x, bf_bottom, right_x, bf_bottom)
            curr_row_top = bf_bottom

        page_subtotal = Decimal("0.00")

        for line in page_lines:
            row_bottom = curr_row_top - row_height
            p_name = line.product_name_snapshot or (line.product.name if line.product else "Item")
            qty_disp, pack_disp = format_qty_presentation(line)
            hsn_disp = line.hsn_sac_snapshot or "-"
            mrp_val = getattr(line, "mrp_snapshot", None) or getattr(line.product, "mrp", Decimal("0.00")) or Decimal("0.00")
            rate_val = line.rate_charged
            dis_val = line.discount_amount
            sgst_rate_str = f"{line.sgst_rate:.2f}" if line.sgst_rate else "0.00"
            cgst_rate_str = f"{line.cgst_rate:.2f}" if line.cgst_rate else "0.00"
            line_total_val = line.line_total

            page_subtotal += line_total_val
            cumulative_amount += line_total_val

            c.setFont("Helvetica", 6)
            x_curr = left_x

            c.drawCentredString(x_curr + (col_widths[0] / 2), row_bottom + 3.5, str(running_sr))
            x_curr += col_widths[0]

            c.drawRightString(x_curr + col_widths[1] - 3, row_bottom + 3.5, qty_disp)
            x_curr += col_widths[1]

            c.drawCentredString(x_curr + (col_widths[2] / 2), row_bottom + 3.5, pack_disp)
            x_curr += col_widths[2]

            c.drawString(x_curr + 3, row_bottom + 3.5, p_name[:26])
            x_curr += col_widths[3]

            c.drawCentredString(x_curr + (col_widths[4] / 2), row_bottom + 3.5, hsn_disp[:10])
            x_curr += col_widths[4]

            c.drawRightString(x_curr + col_widths[5] - 3, row_bottom + 3.5, f"{mrp_val:.2f}")
            x_curr += col_widths[5]

            c.drawRightString(x_curr + col_widths[6] - 3, row_bottom + 3.5, f"{rate_val:.2f}")
            x_curr += col_widths[6]

            c.drawRightString(x_curr + col_widths[7] - 3, row_bottom + 3.5, f"{dis_val:.2f}")
            x_curr += col_widths[7]

            c.drawCentredString(x_curr + (col_widths[8] / 2), row_bottom + 3.5, sgst_rate_str)
            x_curr += col_widths[8]

            c.drawCentredString(x_curr + (col_widths[9] / 2), row_bottom + 3.5, cgst_rate_str)
            x_curr += col_widths[9]

            c.drawRightString(x_curr + col_widths[10] - 3, row_bottom + 3.5, f"{line_total_val:.2f}")

            x_grid = left_x
            for w in col_widths[:-1]:
                x_grid += w
                c.setStrokeColor(HexColor("#E0E0E0"))
                c.setLineWidth(0.5)
                c.line(x_grid, curr_row_top, x_grid, row_bottom)

            curr_row_top = row_bottom
            running_sr += 1

        # 5. FOOTER & SUMMARY SECTION
        footer_height = 125 if is_last_page else 105
        footer_top = bottom_y + footer_height

        x_grid = left_x
        for w in col_widths[:-1]:
            x_grid += w
            c.setStrokeColor(HexColor("#E0E0E0"))
            c.setLineWidth(0.5)
            c.line(x_grid, curr_row_top, x_grid, footer_top)

        c.setStrokeColor(COLOR_BORDER)
        c.setLineWidth(0.75)
        c.line(left_x, footer_top, right_x, footer_top)

        # --- FOOTER SUMMARY SECTION ---
        gst_w = usable_w * 0.60
        totals_w = usable_w * 0.40
        totals_x = left_x + gst_w

        words_h = 13
        words_bot = bottom_y + 42
        words_top = words_bot + words_h

        c.line(totals_x, footer_top, totals_x, words_top)

        # Lines to consider for GST classification:
        # On continuation page, cumulative lines up to this page
        current_cumulative_lines = []
        for p in pages_chunks[:page_num]:
            current_cumulative_lines.extend(p)

        gst_classes = {}
        for l in current_cumulative_lines:
            rate_key = l.tax_rate
            if rate_key not in gst_classes:
                gst_classes[rate_key] = {
                    "taxable": Decimal("0.00"),
                    "sch": Decimal("0.00"),
                    "disc": Decimal("0.00"),
                    "sgst": Decimal("0.00"),
                    "cgst": Decimal("0.00"),
                    "total_gst": Decimal("0.00"),
                }
            tx_val = getattr(l, "taxable_value_snapshot", None) or (l.line_total - l.tax_amount)
            gst_classes[rate_key]["taxable"] += tx_val
            gst_classes[rate_key]["disc"] += l.discount_amount
            gst_classes[rate_key]["sgst"] += l.sgst_amount
            gst_classes[rate_key]["cgst"] += l.cgst_amount
            gst_classes[rate_key]["total_gst"] += l.tax_amount

        gst_cols = [32, 40, 23, 23, 35, 35, 46]
        gst_hdrs = ["CLASS", "TOTAL", "SCH.", "DISC.", "SGST", "CGST", "TOTAL GST"]

        gh_h = 10
        gh_bot = footer_top - gh_h
        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, gh_bot, gst_w, gh_h, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 5)

        gx = left_x
        for i, (gh, gw) in enumerate(zip(gst_hdrs, gst_cols)):
            if i == 0:
                c.drawString(gx + 2, gh_bot + 3, gh)
            else:
                c.drawRightString(gx + gw - 2, gh_bot + 3, gh)
            gx += gw

        gy = gh_bot
        gr_h = 8.5
        sum_taxable = Decimal("0.00")
        sum_disc = Decimal("0.00")
        sum_sgst = Decimal("0.00")
        sum_cgst = Decimal("0.00")
        sum_tot_gst = Decimal("0.00")

        sorted_rates = sorted(gst_classes.keys())
        for r in sorted_rates:
            data = gst_classes[r]
            sum_taxable += data["taxable"]
            sum_disc += data["disc"]
            sum_sgst += data["sgst"]
            sum_cgst += data["cgst"]
            sum_tot_gst += data["total_gst"]

            gy -= gr_h
            c.setFont("Helvetica", 5)
            gx = left_x

            c.drawString(gx + 2, gy + 2.5, f"GST {r:.2f}%")
            gx += gst_cols[0]
            c.drawRightString(gx + gst_cols[1] - 2, gy + 2.5, f"{data['taxable']:.2f}")
            gx += gst_cols[1]
            c.drawRightString(gx + gst_cols[2] - 2, gy + 2.5, "0.00")
            gx += gst_cols[2]
            c.drawRightString(gx + gst_cols[3] - 2, gy + 2.5, f"{data['disc']:.2f}")
            gx += gst_cols[3]
            c.drawRightString(gx + gst_cols[4] - 2, gy + 2.5, f"{data['sgst']:.2f}")
            gx += gst_cols[4]
            c.drawRightString(gx + gst_cols[5] - 2, gy + 2.5, f"{data['cgst']:.2f}")
            gx += gst_cols[5]
            c.drawRightString(gx + gst_cols[6] - 2, gy + 2.5, f"{data['total_gst']:.2f}")

        gy -= gr_h
        c.line(left_x, gy + gr_h, totals_x, gy + gr_h)
        c.setFont("Helvetica-Bold", 5.5)
        gx = left_x
        c.drawString(gx + 2, gy + 2.5, "TOTAL")
        gx += gst_cols[0]
        c.drawRightString(gx + gst_cols[1] - 2, gy + 2.5, f"{sum_taxable:.2f}")
        gx += gst_cols[1]
        c.drawRightString(gx + gst_cols[2] - 2, gy + 2.5, "0.00")
        gx += gst_cols[2]
        c.drawRightString(gx + gst_cols[3] - 2, gy + 2.5, f"{sum_disc:.2f}")
        gx += gst_cols[3]
        c.drawRightString(gx + gst_cols[4] - 2, gy + 2.5, f"{sum_sgst:.2f}")
        gx += gst_cols[4]
        c.drawRightString(gx + gst_cols[5] - 2, gy + 2.5, f"{sum_cgst:.2f}")
        gx += gst_cols[5]
        c.drawRightString(gx + gst_cols[6] - 2, gy + 2.5, f"{sum_tot_gst:.2f}")

        if not is_last_page:
            # Right side: Continued indicator
            c.setFont("Helvetica-Bold", 9)
            c.drawString(totals_x + 12, footer_top - 35, f"Continued... {page_num + 1}")
            c.setFont("Helvetica", 6.5)
            c.drawString(totals_x + 12, footer_top - 50, f"Page Total: {page_subtotal:.2f}")

            # Words bar on continuation page
            c.line(left_x, words_top, right_x, words_top)
            c.line(left_x, words_bot, right_x, words_bot)
            c.setFont("Helvetica-Oblique", 6.5)
            c.drawString(left_x + 4, words_bot + 4, f"(Continued on Page {page_num + 1})")

            # Bottom 3 boxes
            b_w1 = usable_w * 0.42
            b_w2 = usable_w * 0.25
            b_w3 = usable_w - b_w1 - b_w2

            c.line(left_x + b_w1, words_bot, left_x + b_w1, bottom_y)
            c.line(left_x + b_w1 + b_w2, words_bot, left_x + b_w1 + b_w2, bottom_y)

            c.setFont("Helvetica-Bold", 6)
            c.drawString(left_x + 3, words_bot - 8, "Terms & Conditions")
            c.setFont("Helvetica", 5)
            t_lines = terms_text.splitlines()
            ty = words_bot - 16
            for tl in t_lines[:3]:
                c.drawString(left_x + 3, ty, tl[:46])
                ty -= 6

            c.setFont("Helvetica-Bold", 6)
            c.drawCentredString(left_x + b_w1 + (b_w2 / 2), bottom_y + 6, "Receiver's Signature")

            c.setFont("Helvetica", 6)
            c.drawString(left_x + b_w1 + b_w2 + 4, words_bot - 8, f"For {co_name[:24]}")
            c.setFont("Helvetica-Bold", 6)
            c.drawCentredString(right_x - (b_w3 / 2), bottom_y + 6, "Authorised Signatory")

            c.showPage()
            continue

        gst_classes = {}
        for l in lines:
            rate_key = l.tax_rate
            if rate_key not in gst_classes:
                gst_classes[rate_key] = {
                    "taxable": Decimal("0.00"),
                    "sch": Decimal("0.00"),
                    "disc": Decimal("0.00"),
                    "sgst": Decimal("0.00"),
                    "cgst": Decimal("0.00"),
                    "total_gst": Decimal("0.00"),
                }
            tx_val = getattr(l, "taxable_value_snapshot", None) or (l.line_total - l.tax_amount)
            gst_classes[rate_key]["taxable"] += tx_val
            gst_classes[rate_key]["disc"] += l.discount_amount
            gst_classes[rate_key]["sgst"] += l.sgst_amount
            gst_classes[rate_key]["cgst"] += l.cgst_amount
            gst_classes[rate_key]["total_gst"] += l.tax_amount

        gst_cols = [32, 40, 23, 23, 35, 35, 46]
        gst_hdrs = ["CLASS", "TOTAL", "SCH.", "DISC.", "SGST", "CGST", "TOTAL GST"]

        gh_h = 10
        gh_bot = footer_top - gh_h
        c.setFillColor(COLOR_HEADER_BG)
        c.rect(left_x, gh_bot, gst_w, gh_h, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 5)

        gx = left_x
        for i, (gh, gw) in enumerate(zip(gst_hdrs, gst_cols)):
            if i == 0:
                c.drawString(gx + 2, gh_bot + 3, gh)
            else:
                c.drawRightString(gx + gw - 2, gh_bot + 3, gh)
            gx += gw

        gy = gh_bot
        gr_h = 8.5
        sum_taxable = Decimal("0.00")
        sum_disc = Decimal("0.00")
        sum_sgst = Decimal("0.00")
        sum_cgst = Decimal("0.00")
        sum_tot_gst = Decimal("0.00")

        sorted_rates = sorted(gst_classes.keys())
        for r in sorted_rates:
            data = gst_classes[r]
            sum_taxable += data["taxable"]
            sum_disc += data["disc"]
            sum_sgst += data["sgst"]
            sum_cgst += data["cgst"]
            sum_tot_gst += data["total_gst"]

            gy -= gr_h
            c.setFont("Helvetica", 5)
            gx = left_x

            c.drawString(gx + 2, gy + 2.5, f"GST {r:.2f}%")
            gx += gst_cols[0]
            c.drawRightString(gx + gst_cols[1] - 2, gy + 2.5, f"{data['taxable']:.2f}")
            gx += gst_cols[1]
            c.drawRightString(gx + gst_cols[2] - 2, gy + 2.5, "0.00")
            gx += gst_cols[2]
            c.drawRightString(gx + gst_cols[3] - 2, gy + 2.5, f"{data['disc']:.2f}")
            gx += gst_cols[3]
            c.drawRightString(gx + gst_cols[4] - 2, gy + 2.5, f"{data['sgst']:.2f}")
            gx += gst_cols[4]
            c.drawRightString(gx + gst_cols[5] - 2, gy + 2.5, f"{data['cgst']:.2f}")
            gx += gst_cols[5]
            c.drawRightString(gx + gst_cols[6] - 2, gy + 2.5, f"{data['total_gst']:.2f}")

        gy -= gr_h
        c.line(left_x, gy + gr_h, totals_x, gy + gr_h)
        c.setFont("Helvetica-Bold", 5.5)
        gx = left_x
        c.drawString(gx + 2, gy + 2.5, "TOTAL")
        gx += gst_cols[0]
        c.drawRightString(gx + gst_cols[1] - 2, gy + 2.5, f"{sum_taxable:.2f}")
        gx += gst_cols[1]
        c.drawRightString(gx + gst_cols[2] - 2, gy + 2.5, "0.00")
        gx += gst_cols[2]
        c.drawRightString(gx + gst_cols[3] - 2, gy + 2.5, f"{sum_disc:.2f}")
        gx += gst_cols[3]
        c.drawRightString(gx + gst_cols[4] - 2, gy + 2.5, f"{sum_sgst:.2f}")
        gx += gst_cols[4]
        c.drawRightString(gx + gst_cols[5] - 2, gy + 2.5, f"{sum_cgst:.2f}")
        gx += gst_cols[5]
        c.drawRightString(gx + gst_cols[6] - 2, gy + 2.5, f"{sum_tot_gst:.2f}")

        ty = footer_top - 10
        tr_h = 9
        labels = [
            ("SUB TOTAL", f"{sum_taxable:.2f}"),
            ("SGST PAYABLE", f"{sum_sgst:.2f}"),
            ("CGST PAYABLE", f"{sum_cgst:.2f}"),
            ("ADD/LESS", "0.00"),
            ("CR/DR NOTE", "0.00"),
        ]
        sum_igst = sum(l.igst_amount for l in lines)
        if sum_igst > Decimal("0.00"):
            labels.insert(3, ("IGST PAYABLE", f"{sum_igst:.2f}"))

        for lbl, val in labels:
            c.setFont("Helvetica", 6)
            c.drawString(totals_x + 4, ty + 2, lbl)
            c.drawRightString(right_x - 4, ty + 2, val)
            ty -= tr_h

        c.setFillColor(COLOR_HEADER_BG)
        c.rect(totals_x, ty - 2, totals_w, 13, fill=1, stroke=1)
        c.setFillColor(COLOR_TEXT)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(totals_x + 4, ty + 2, "GRAND TOTAL")
        c.drawRightString(right_x - 4, ty + 2, f"{invoice.total_amount:.2f}")

        c.line(left_x, words_top, right_x, words_top)
        c.line(left_x, words_bot, right_x, words_bot)

        c.setFont("Helvetica-Bold", 6.5)
        words_str = amount_to_words(invoice.total_amount)
        c.drawString(left_x + 4, words_bot + 4, words_str)

        b_w1 = usable_w * 0.42
        b_w2 = usable_w * 0.25
        b_w3 = usable_w - b_w1 - b_w2

        c.line(left_x + b_w1, words_bot, left_x + b_w1, bottom_y)
        c.line(left_x + b_w1 + b_w2, words_bot, left_x + b_w1 + b_w2, bottom_y)

        c.setFont("Helvetica-Bold", 6)
        c.drawString(left_x + 3, words_bot - 8, "Terms & Conditions")
        c.setFont("Helvetica", 5)
        t_lines = terms_text.splitlines()
        ty = words_bot - 16
        for tl in t_lines[:3]:
            c.drawString(left_x + 3, ty, tl[:46])
            ty -= 6

        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(left_x + b_w1 + (b_w2 / 2), bottom_y + 6, "Receiver's Signature")

        c.setFont("Helvetica", 6)
        c.drawString(left_x + b_w1 + b_w2 + 4, words_bot - 8, f"For {co_name[:24]}")
        c.setFont("Helvetica-Bold", 6)
        c.drawCentredString(right_x - (b_w3 / 2), bottom_y + 6, "Authorised Signatory")

        c.showPage()

    c.save()
    return buffer.getvalue()
