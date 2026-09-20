from decimal import Decimal, ROUND_HALF_UP

TAX_MODE_EXCLUSIVE = "exclusive"
TAX_MODE_INCLUSIVE = "inclusive"

PAISE_QUANTUM = Decimal("0.01")


def round_inr(value):
    return value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def round_paise(value):
    """Round to paise; used by purchase lines to mirror supplier bills."""
    return value.quantize(PAISE_QUANTUM, rounding=ROUND_HALF_UP)


def calculate_gst(seller_profile, customer, lines, place_of_supply_state_code=None, tax_mode=TAX_MODE_EXCLUSIVE, rounding=round_paise):
    """
    Computes deterministic GST totals across an invoice using StockBill rounding policy:
    1. Calculate total line GST at paise precision (using Python Decimal).
    2. Round total line GST to ₹0.01 (round_paise with ROUND_HALF_UP).
    3. For intra-state GST, split the rounded line GST into CGST and SGST:
       - CGST is rounded to paise (round_paise(line_tax_target / 2)).
       - SGST = rounded line GST - CGST.
       - Therefore CGST + SGST always equals the line GST exactly (no odd-paisa drift).
    4. For inter-state GST, full tax is allocated to IGST (rounded to paise).
    5. Line total = taxable value (quantized to 0.01) + line GST.
    6. Invoice totals are the exact sums of the line components.
    """

    seller_state_code = getattr(seller_profile, 'state_code', None) if seller_profile else None

    # Defaults place of supply to customer code if registered, else seller code.
    if not place_of_supply_state_code:
        if customer and getattr(customer, 'state_code', None):
            place_of_supply_state_code = customer.state_code
        else:
            place_of_supply_state_code = seller_state_code

    is_inter_state = False
    if seller_state_code and place_of_supply_state_code:
        is_inter_state = seller_state_code != place_of_supply_state_code

    result = {
        "place_of_supply": place_of_supply_state_code or "",
        "is_inter_state": is_inter_state,
        "tax_mode": tax_mode,
        "lines": [],
        "totals": {
            "subtotal": Decimal("0.00"),  # Base before discount
            "discount_total": Decimal("0.00"),
            "taxable_value": Decimal("0.00"),
            "cgst_total": Decimal("0.00"),
            "sgst_total": Decimal("0.00"),
            "igst_total": Decimal("0.00"),
            "total_tax": Decimal("0.00"),
            "grand_total": Decimal("0.00"),
        }
    }

    for idx, line in enumerate(lines):
        qty = Decimal(str(line.get("quantity", 1)))
        rate = Decimal(str(line.get("rate_charged", 0)))
        discount = Decimal(str(line.get("discount_amount", 0)))
        tax_rate_val = Decimal(str(line.get("tax_rate", 0)))

        # Determine gross based on inputs (tax inclusive or exclusive rate)
        gross_line_amount = qty * rate

        net_base_amount = gross_line_amount - discount

        taxable_value = Decimal("0.00")
        total_tax_raw = Decimal("0.00")

        if tax_mode == TAX_MODE_INCLUSIVE:
            # For INCLUSIVE: The net base amount already includes tax.
            # Taxable Value = Net Base Amount / (1 + Rate)
            taxable_value = net_base_amount / (Decimal(1) + (tax_rate_val / Decimal(100)))
            total_tax_raw = net_base_amount - taxable_value
        else:
            # EXCLUSIVE
            taxable_value = net_base_amount
            total_tax_raw = taxable_value * (tax_rate_val / Decimal(100))

        # Precision tax calculation per line component
        cgst_rate = Decimal("0.00")
        sgst_rate = Decimal("0.00")
        igst_rate = Decimal("0.00")
        cgst_amount = Decimal("0.00")
        sgst_amount = Decimal("0.00")
        igst_amount = Decimal("0.00")

        half_rate = tax_rate_val / Decimal(2)

        if is_inter_state:
            igst_rate = tax_rate_val
            igst_amount = rounding(total_tax_raw)
        else:
            cgst_rate = half_rate
            sgst_rate = half_rate
            line_tax_target = rounding(total_tax_raw)
            cgst_amount = rounding(line_tax_target / Decimal(2))
            sgst_amount = line_tax_target - cgst_amount

        # Line level total
        line_tax = cgst_amount + sgst_amount + igst_amount
        line_total = taxable_value.quantize(Decimal("0.01")) + line_tax

        result["lines"].append({
            "original_index": idx,
            "quantity": qty.quantize(Decimal("0.001")),
            "rate_charged": rate.quantize(Decimal("0.01")),
            "discount_amount": discount.quantize(Decimal("0.01")),
            "taxable_value": taxable_value.quantize(Decimal("0.01")),
            "cgst_rate": cgst_rate.quantize(Decimal("0.01")),
            "cgst_amount": cgst_amount,
            "sgst_rate": sgst_rate.quantize(Decimal("0.01")),
            "sgst_amount": sgst_amount,
            "igst_rate": igst_rate.quantize(Decimal("0.01")),
            "igst_amount": igst_amount,
            "tax_amount": line_tax,
            "line_total": line_total,
        })

        result["totals"]["subtotal"] += gross_line_amount.quantize(Decimal("0.01"))
        result["totals"]["discount_total"] += discount.quantize(Decimal("0.01"))
        result["totals"]["taxable_value"] += taxable_value.quantize(Decimal("0.01"))
        result["totals"]["cgst_total"] += cgst_amount
        result["totals"]["sgst_total"] += sgst_amount
        result["totals"]["igst_total"] += igst_amount
        result["totals"]["total_tax"] += line_tax
        result["totals"]["grand_total"] += line_total

    return result
