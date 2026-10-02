# StockBill

StockBill is an FMCG distributor inventory, billing, purchasing, customer-financial, supplier, GST, reporting, and stock-management system developed for **Divya Enterprises**.

---

## Project Status

- **Status:** V1 implementation complete.
- **Repository State:** The `main` branch is clean and synchronized with [GitHub](https://github.com/deveshshuklaaa/StockBill).
- **Target Deployment:** Local / single client PC environment. StockBill is designed to run as an on-premise local distributor desktop/server system, not a public multi-tenant cloud application.
- **Data Boundary:** Application source code and database schema migrations are tracked in Git. Production and master database data are maintained and migrated independently outside of version control.

---

## Tech Stack

### Backend
- **Language:** Python 3.12+
- **Web Framework:** Django 5.x
- **API Framework:** Django REST Framework (DRF)
- **PDF Generation:** WeasyPrint (with ReportLab / PyMuPDF utilities)
- **Excel Processing:** openpyxl

### Database
- **Engine:** PostgreSQL 16+
- **Driver:** psycopg2-binary
- **Integrity:** PostgreSQL-level immutability triggers and constraints for authoritative financial and ledger tables

### Frontend
- **Framework:** React 19
- **Build Tool:** Vite 8
- **Routing:** React Router 7
- **HTTP Client:** Axios (with request token interceptors and session management)
- **Styling:** Custom Vanilla CSS design system
- **Language:** JavaScript (ES modules)

### Development & Tooling
- **Package Managers:** npm, pip
- **Virtual Environment:** Python `.venv`
- **Testing:** Django Test Suite (backend), Vitest + React Testing Library (frontend)
- **Linting:** oxlint

---

## Core Features

### Product Catalogue
- **Dynamic Category & Attribute Architecture:** Flexible category-level attribute definitions (`brand`, `net_weight`, `units_per_master_box`).
- **Typed Product Attributes:** Attribute definitions support typed values (strings, numeric dimensions) dynamically linked via `CategoryAttribute` and `ProductAttributeValue`.
- **Product Variants as Separate Records:** Each packaging or weight variant is maintained as an independent, fully-tracked product entity.
- **Identification & Master Fields:** Unique SKU, product name, MRP, net weight, units per master box, and HSN/SAC codes.
- **Product Archival:** Inactive products are archived via an `is_active` flag, preserving historical integrity across prior documents without breaking foreign keys.

### Inventory
- **Base-Unit Inventory:** All warehouse balances and movements are tracked strictly in base units (e.g., pieces).
- **Authoritative Balance Tracking (`InventoryBalance`):** Real-time stock quantity and running Weighted Average Cost (WAC) tracked per product and warehouse.
- **Append-Only Stock Ledger (`StockLedger`):** Immutable, audit-verifiable historical ledger of every stock movement (purchases, sales, adjustments, transfers).
- **Weighted Average Cost (WAC):** Perpetual WAC recalculation upon every purchase receipt based on landed pre-tax, post-discount purchase cost.
- **Stock Adjustments (`StockAdjustment`):** Controlled manual stock corrections (In/Out) with mandatory reason classification, reference tracking, and ledger impact.
- **Opening Stock (`OpeningStock`):** Dedicated opening stock entry mechanism with automated balance and ledger seeding.
- **Warehouse Management (`Warehouse`):** Multi-warehouse support with primary default warehouse (`MAIN`).
- **Warehouse Transfers (`WarehouseTransfer`):** Multi-step transfer workflow between source and destination warehouses with live stock validation.
- **Stock Thresholds & Alerts:** Low-stock threshold tracking per product to highlight inventory replenishment needs.

### Purchasing
- **Supplier Management:** Comprehensive supplier master records with GSTIN, state code, and contact information.
- **Purchase Invoices (`PurchaseInvoice`):** Multi-line supplier purchases supporting both base pieces and master box conversions.
- **Lifecycle Management:** Strict `DRAFT` &rarr; `POSTED` &rarr; `CANCELLED` state machine.
- **Supplier GST Information & Calculations:** Automatic intra-state (CGST + SGST) and inter-state (IGST) tax calculation based on supplier and business profile state codes.
- **Supplier-Wise MRP Purchase Pricing (`SupplierPurchasePricing`):** Configurable purchase cost rate slabs defined per **Supplier + MRP** (e.g., Supplier X supplies all MRP ₹10 products at ₹6.20).
- **Historical Cost Snapshots:** Line items permanently store historical purchase rate, discounts, and applied tax rates at the time of posting.
- **WAC Update on Posting:** Authoritative balance and cost recalculation executed atomically in a database transaction upon posting.

> **Important Business Rule:** Supplier purchase pricing is mapped by **Supplier + MRP**, NOT Supplier + Product.

### Sales / Billing
- **Customer Management:** Authoritative customer master records with contact details, billing addresses, GSTIN, credit limits, and credit periods.
- **Sales Invoices (`Invoice`):** Fast multi-line billing interface with automatic customer pricing lookup, tax mode selection, and flexible discounts.
- **Lifecycle Management:** Strict `DRAFT` &rarr; `POSTED` &rarr; `CANCELLED` state machine.
- **Flexible Sales Units:** Sell in loose pieces or full master boxes; lines automatically convert master boxes to base piece quantities.
- **Customer-Wise MRP Pricing (`CustomerMRPPricing`):** Tiered customer pricing slabs mapped by **Customer + MRP**, auto-filling agreed wholesale rates.
- **Tax Compliance & Modes:** Inclusive and Exclusive tax calculation modes with slab-wise CGST/SGST/IGST breakdown.
- **Payment Types & Credit Limits:** Support for immediate cash billing and credit sales validated against real-time customer available credit.
- **Payments & Receipts (`Payment`):** Incremental payment collection linked to invoices and customer accounts with receipt generation.
- **Payment Reversals:** Audited payment reversal workflow for bounced cheques or erroneous entries.
- **Credit Notes (`CreditNote`):** Controlled return and credit allowance mechanism linked to original invoices without mutating posted invoices.
- **Invoice Amendment Workflow:** Supervised correction workflow allowing cancellation and re-issuance with explicit amendment lineage.
- **Historical Invoice Snapshots:** Immutable capture of customer billing address, product name, SKU, HSN, rate, discount, and tax at the moment of posting.
- **PDF Invoice Generation:** Server-rendered GST-compliant tax invoices generated via WeasyPrint.

### Customers
- Full CRUD operations with soft-archival (`is_active`).
- Live outstanding balance calculation: `Opening Balance + Invoices + Debit Notes - Payments + Reversals - Credit Notes`.
- Enforced credit limits with available credit checks during invoice drafting.
- Detailed customer ledger and statement reporting.
- Customer-specific MRP wholesale pricing slabs.

### Suppliers
- Supplier directory with active/inactive states.
- State-code tracking for GST place-of-supply logic.
- Historical purchase invoices and payment audit trail.
- Supplier-specific MRP purchase rate rules.

### Reports
- **Daily Sales Report:** Segregated view of cash sales, credit sales, and actual collections for any chosen date.
- **Sales Summary Report:** Filterable sales analytics by date range, customer, and payment status.
- **Sales GST Report:** Authoritative 16-column tax filing report with live filtering and Excel (`.xlsx`) export.
- **Item-Wise Invoice Summary:** Modal and exportable summary grouping items across selected invoices with total quantities and MRPs.
- **Purchase Summary Report:** Supplier purchases, taxable amounts, and input tax breakdown.
- **Inventory Valuation Report:** Stock quantities, WAC valuation, and inventory value per warehouse.
- **Stock Movement Report:** Chronological trace of inventory changes by product, warehouse, and movement type.
- **Product Sales Report:** Sales volume, revenue, and contribution by product.
- **Customer Sales Report:** Sales volume and balance breakdown per customer.
- **Tax Summary Report:** Consolidated output tax vs. input tax summaries.
- **Profit & Loss Report (Admin Only):** Revenue, COGS, and gross profit analytics calculated from immutable transaction snapshots.
- **Top Products Report:** Ranking of top-performing items by quantity or revenue.
- **Executive Dashboard:** Live high-level KPIs for inventory value, daily turnover, and receivables.

### Security & Integrity
- **Role-Based Authorization:** Clear privilege separation between `admin` (supervisory controls, pricing edits, adjustments, configuration) and `staff` (routine billing, customer/inventory viewing).
- **Session Security:** Token authentication stored exclusively in `sessionStorage` (cleared immediately upon browser close or logout).
- **Posted Document Immutability:** Posted invoices and purchases cannot be edited; corrections require formal cancellation, credit notes, or amendments.
- **Append-Only Ledger & Reversals:** Stock movements, payments, and credit notes are strictly append-only; payments cannot be deleted, only formally reversed with audit reason.
- **PostgreSQL Immutability Triggers:** Database-level trigger functions protect historical tables against unauthorized `UPDATE` or `DELETE` operations.
- **Idempotency Protection:** Unique client idempotency keys (`InvoiceIdempotencyKey`, `PurchaseIdempotencyKey`, etc.) prevent duplicate document creation on network retries.
- **Audit Logging (`AuditLog`):** Sensitive administrative and financial actions are captured in an append-only audit trail.
- **Transactional Atomicity:** All ledger modifications and accounting updates are executed within atomic database transactions (`transaction.atomic`).

---

## Business Rules

1. **Base-Unit Invariant:** Inventory is stored, counted, and balanced strictly in base units (piece).
2. **Master Box Representation:** A Master Box is a commercial packaging unit for buying and selling. It converts to a fixed number of base pieces via `units_per_master_box`. Master boxes do not exist as independent inventory balances.
3. **Cost Basis (WAC):** Weighted Average Cost is maintained per product and per warehouse. WAC reflects the pre-tax, post-discount purchase cost.
4. **Separation of Concerns:** Product MRP, Customer Selling Price, Supplier Purchase Rate, and Inventory WAC/COGS are distinct values governed by separate business mechanisms.
5. **Authoritative Snapshots:** Posted invoices and purchases store self-contained historical snapshots of prices, taxes, and customer/supplier metadata.
6. **Frontend Decoupling:** The React frontend displays and previews calculations, but the Django backend is the sole authoritative engine for GST, pricing, balances, and inventory valuation.
7. **Document Immutability:** Once posted, invoices, purchases, adjustments, and ledger entries cannot be mutated directly in the database.

---

## GST Configuration

- **Configured Production Tax Rates:**
  - `GST 5%` (Rate: `5.00%`, active)
  - `GST 18%` (Rate: `18.00%`, active)
  - `GST 40%` (Rate: `40.00%`, active)
- **Company Profile:**
  - **Trade Name:** DIVYA ENTERPRISES
  - **GSTIN:** `27ECNPS6389P1Z5`
  - **State:** Maharashtra (State Code: `27`)
  - **Place of Supply Logic:** Intra-state (CGST + SGST) is applied when customer/supplier state code matches `27`; Inter-state (IGST) is applied when state codes differ.

---

## V1 Scope / Intentional Exclusions

The following workflows are intentionally excluded from the V1 release scope and are planned for future milestones:
- **Sales Returns Workflow:** Dedicated customer return modules are omitted from V1; invoice cancellations and credit notes are used where necessary.
- **Purchase Returns Workflow:** Debit notes and purchase return workflows to suppliers are omitted from V1.
- **Barcode Scanning Workflow:** Barcode generation, printing, and automated scanner input are omitted from V1.

---

## Project Data Model Overview

The Django application backend is structured into modular domain applications under `divya_enterprises/`:

```text
divya_enterprises/
├── accounts/       # Authentication, user roles, staff permissions
├── customers/      # Customer master, customer-wise MRP pricing
├── inventory/      # Products, catalogue, warehouses, stock ledger, purchasing, adjustments
└── billing/        # Invoices, line items, payments, credit/debit notes, audit log, business profile
```

### Key Models by Domain

- **`accounts`**:
  - `User`: Custom user model with `role` (`admin`, `staff`), `is_staff`, and `is_superuser` flags.
- **`customers`**:
  - `Customer`: Customer master record (GSTIN, credit limits, balances, contact details).
  - `CustomerMRPPricing`: Customer-specific rate overrides mapped by `(customer, mrp)`.
- **`inventory`**:
  - `Category`, `AttributeDefinition`, `CategoryAttribute`, `ProductAttributeValue`: Dynamic product attribute system.
  - `Product`: Product master entity with SKU, MRP, brand, net weight, pack size, and HSN.
  - `TaxRate`: System tax rate master (5%, 18%, 40%).
  - `Warehouse`: Storage locations (`MAIN`).
  - `InventoryBalance`: Warehouse-level real-time stock balance and WAC.
  - `StockLedger`: Append-only chronological inventory movement log.
  - `StockAdjustment`: Controlled stock corrections with audit reason.
  - `OpeningStock`: Initial stock intake records.
  - `WarehouseTransfer`: Inter-warehouse stock transfer tracking.
  - `Supplier`: Supplier master records with GSTIN and address.
  - `SupplierPurchasePricing`: Supplier purchase cost slabs mapped by `(supplier, mrp)`.
  - `PurchaseInvoice` & `PurchaseLineItem`: Supplier procurement records.
  - `PurchaseIdempotencyKey`: Retriable purchase submission protection.
- **`billing`**:
  - `BusinessProfile`: Company identity, GSTIN, registered address, and default invoice terms.
  - `Invoice` & `InvoiceLineItem`: Authoritative sales billing records with financial snapshots.
  - `InvoiceIdempotencyKey`: Network duplicate protection for sales billing.
  - `Payment`: Financial receipt collections against customer invoices.
  - `CreditNote` & `CreditNoteLineItem`: Invoice adjustments and credit allowances.
  - `DebitNote`: Customer debit adjustments.
  - `AuditLog`: Action tracking for administrative and financial events.

---

## Local Development Setup

Follow these exact steps to set up StockBill on a development workstation.

### 1. Clone Repository
```powershell
git clone https://github.com/deveshshuklaaa/StockBill.git
cd StockBill
```

### 2. Configure Python Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 3. Install Backend Dependencies
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Create a `.env` file in the repository root:
```ini
DEBUG=True
SECRET_KEY=<your-development-secret-key>
ALLOWED_HOSTS=localhost,127.0.0.1

DB_NAME=stockbill
DB_USER=postgres
DB_PASSWORD=<your-postgresql-password>
DB_HOST=localhost
DB_PORT=5432

POSTGRES_DB=stockbill
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<your-postgresql-password>
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 5. Validate System & Migrations
```powershell
cd divya_enterprises
python manage.py check
python manage.py showmigrations
```

To initialize a new blank schema on a fresh PostgreSQL instance:
```powershell
python manage.py migrate
```

### 6. Start Backend API Server
```powershell
python manage.py runserver 0.0.0.0:8000
```
Backend API will be available at `http://localhost:8000/api/`.

### 7. Install & Start Frontend
In a new terminal window:
```powershell
cd frontend
npm install
npm run dev
```
Frontend web application will be available at `http://localhost:5173/`.

### 8. Build Frontend for Production
```powershell
cd frontend
npm run build
```

---

## Database Management & Clean Architecture

- **Code vs. Data Separation:** Git tracks application code, unit tests, and Django migrations. Database records (master catalogue, customer databases, transactions) are strictly isolated from Git.
- **Fresh Installs:** A new database can be scaffolded at any time by running `python manage.py migrate` against an empty PostgreSQL database.
- **Zero Credentials in Git:** Production credentials, API tokens, and database dumps must never be committed to source control.

---

## Client PC Migration Package

For deploying the verified production master data to a client machine, StockBill uses an out-of-band migration package kept outside the Git repository (e.g., `C:\StockBill-Migration\`):

- **`stockbill_clean_production.dump`**: Clean PostgreSQL custom-format archive (`-Fc --no-owner --no-acl`) containing the prepared production dataset.
- **`stockbill_clean_production.dump.sha256`**: SHA-256 verification checksum.
- **`migration_verification.txt`**: Table-by-table record count and test-restore audit report.
- **`RESTORE_INSTRUCTIONS.md`**: Step-by-step restoration guide for the client machine.

Refer to `RESTORE_INSTRUCTIONS.md` inside the migration package for the exact restoration commands.

---

## Development Notes

1. **Authoritative Backend:** React is purely a presentation layer. All financial, GST, margin, and stock calculations must be performed or validated by the backend.
2. **Immutable Transactions:** Never modify posted invoices or ledger balances directly. Use the official cancellation, adjustment, or credit note workflows.
3. **Master Data vs. Transactional Data:** Master data changes (e.g., updating a customer address or product MRP) must not mutate historical invoice snapshots.
4. **Invariants:** All modifications to inventory or billing logic must preserve the core invariants outlined in `INVARIANTS.md`.

---

## Testing & Quality Assurance

### Backend Test Suite
Run the full Django test suite from `divya_enterprises/`:
```powershell
cd divya_enterprises
..\.venv\Scripts\python.exe manage.py test
```

### Frontend Test Suite
Run Vitest component and workflow tests from `frontend/`:
```powershell
cd frontend
npm test -- --run
```

### Code Quality & Linter
Run Oxlint against frontend source files:
```powershell
cd frontend
npm run lint
```

---

## Reference Production Master Data Snapshot

The V1 production baseline contains the following verified master data:

- **Customers:** 133 active customer accounts (all starting with ₹0.00 balance)
- **Products:** 84 products across snack and food lines (all starting with 0.000 current stock)
- **Active Categories:** 1 (`Packaged Food`)
- **Suppliers:** 2 active manufacturers:
  - *Chheda Agro Food Park Pvt. Ltd.* (GSTIN: `27ABECS9815P1ZI`)
  - *Chheda Specialities Foods Pvt. Ltd.* (GSTIN: `27AACCC6221G1ZZ`)
- **Customer MRP Pricing Slabs:** 4 active customer price matrices
- **Supplier MRP Purchase Pricing Slabs:** 4 active supplier purchase price matrices
- **Tax Rates:** 3 configured rates (5%, 18%, 40%)
- **Warehouse:** 1 central warehouse (`MAIN`)
- **Transactions:** 0 (all sales invoices, purchase invoices, ledger records, adjustments, and balances clean at zero)

---

## License

Proprietary software developed for **Divya Enterprises**. All rights reserved. Unauthorized copying, distribution, or deployment of this software is strictly prohibited.
