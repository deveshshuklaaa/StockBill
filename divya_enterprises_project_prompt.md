# Project Brief: Divya Enterprises — Inventory Management & Billing System

## Context
Build a production-ready inventory management and billing system for **Divya Enterprises**, an FMCG distributor company. This is a real client project (not academic), currently scoped for a **single shop / single warehouse**, but the architecture must be scalable to support multiple suppliers, multiple warehouses, and multiple roles in the future without requiring a rewrite.

A companion Flutter mobile app will consume the same backend API later — so **the backend must be API-first** (Django REST Framework), not a monolithic template-rendered app.

---

## Tech Stack

- **Backend:** Django + Django REST Framework (DRF)
- **Database:** PostgreSQL
- **Web Frontend:** React (consumes the DRF API)
- **Mobile (future phase, not now):** Flutter, consuming the same DRF API
- **Auth:** Django auth + DRF Token/JWT authentication, with role-based permissions
- **PDF Invoice Generation:** WeasyPrint (HTML → PDF)
- **Hosting (initial/free-tier phase):** Render or Railway (managed Postgres + backend), Vercel/Netlify for React frontend

---

## User Roles

1. **Admin**
   - Full access
   - Can add/edit/delete products
   - Can add/edit/delete customers
   - Can view cost price, margins, and all financial reports
   - Can manage staff accounts

2. **Staff**
   - Can create invoices/bills
   - Can view stock levels
   - Cannot access admin-only data (e.g., cost price, profit margins)
   - Cannot add/edit products or customers
   - Cannot manage users

---

## Core Features

### 1. Product & Inventory Management
- Products have: name, category, brand, unit type (e.g., carton/box/piece), default selling price, cost price, GST tax slab, current stock quantity.
- Support for **broken/loose quantity sales** — some products are sold in fixed units (cartons/boxes) while others can be sold in partial/broken quantities (e.g., 5 pieces out of a 12-pack). Unit conversion (e.g., 1 carton = 12 pieces) must be modeled so stock deducts correctly regardless of how it's sold.
- Product variants (size, flavor, pack size) tracked as distinct SKUs.
- **No expiry/batch tracking required at this stage** (explicitly descoped — may be added later if purchase volume grows; design the Product/stock model so this could be added later without a full rewrite, but do not build it now).
- Low-stock alerts, with a configurable threshold **per product** (not a single global threshold).
- Single warehouse/location for now, but the data model should not hardcode a single-location assumption (e.g., avoid embedding location directly on Product — prefer a separate stock/location relationship even if only one location exists today).
- Single supplier for now, but the data model should allow adding more suppliers later (i.e., don't hardcode supplier info directly onto Product).

### 2. Customers
- Customer types: **B2B** (registered businesses, requires GSTIN) and **B2C** (individual/walk-in consumers, no GSTIN required).
- Support for **fixed/regular customer accounts** as well as **one-off walk-in retail billing** (walk-in sales may not need a full customer record).
- Customer-wise sales history and outstanding balance view.

### 3. Pricing (Important — non-standard)
- **Prices are NOT fixed per product and NOT fixed per customer.** Rate can vary customer-to-customer, and can vary for the *same* customer across different invoices/transactions.
- Therefore: do **not** build a stored "customer price list" table. Instead:
  - `Product` holds a default/suggested price only (for staff convenience when billing).
  - The **actual rate charged is entered/edited at invoice-line-item creation time** and stored on that line item permanently.
  - Historical invoices must never change even if the product's default price changes later.

### 4. Billing & Invoicing
- GST-compliant invoices. Tax slabs supported: **5%, 18%, 40%** (India's post-GST-2.0-reform slab structure — no 12% or 28% slabs). Tax rate is stored **per product**.
- Invoices must correctly handle both B2B (GSTIN shown) and B2C (no GSTIN) formats.
- Support **both immediate/cash payment and credit-based billing** (pay later).
- For credit billing: maintain a proper **ledger** (invoices and payments as separate immutable entries) — outstanding balance must be *calculated* (sum of invoices − sum of payments), never stored as a single mutable "amount_due" field that can drift out of sync.
- Support payment reminders/tracking for outstanding dues.
- Generate invoices as PDF (for digital sharing, e.g. WhatsApp) **and** support printing to a physical printer at the office.

### 5. Reports
- Daily sales report
- Stock valuation report
- Profit/loss report (requires cost price vs selling price tracking)
- Top-selling products report
- Customer-wise sales history and outstanding balances

---

## Suggested Core Data Models (starting point — refine as needed)

```
Product
  - name, category, brand
  - unit_type (carton/box/piece), unit_conversion_factor
  - default_price, cost_price
  - tax_slab (5 / 18 / 40)
  - current_stock
  - low_stock_threshold

Customer
  - name, contact_info
  - customer_type (B2B / B2C)
  - gstin (nullable, required only for B2B)

Invoice
  - customer (FK, nullable for anonymous walk-in if needed)
  - date
  - payment_status (paid / credit / partially_paid)
  - total_amount

InvoiceLineItem
  - invoice (FK)
  - product (FK)
  - quantity
  - rate_charged   <-- captured at time of sale, independent of Product.default_price
  - tax_rate

Payment
  - customer (FK)
  - invoice (FK, nullable — payments can be against a running balance too)
  - amount
  - date

User (extends Django auth)
  - role (admin / staff)
```

---

## Project Structure Request

Please scaffold:
1. A Django project with a clean app structure (e.g., separate apps for `inventory`, `billing`, `customers`, `accounts`/auth).
2. DRF serializers, viewsets, and URL routing for all core models above.
3. Role-based permission classes for Admin vs Staff (e.g., restrict cost_price and margin data from Staff-facing serializers/endpoints).
4. PostgreSQL configuration (via environment variables, not hardcoded).
5. Basic WeasyPrint invoice PDF generation endpoint.
6. A README documenting setup steps, environment variables needed, and how to run migrations.

Do not implement the React frontend or Flutter app yet — this phase is backend/API only. Confirm the schema and API structure with me before writing full business logic for invoicing/ledger calculations.
