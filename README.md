# Divya Enterprises Inventory & Billing Backend

This repository contains the Django + DRF backend for the Divya Enterprises inventory management and billing system. This phase focuses on the backend API and data model design only.

## Features scaffolded

- Django project with modular app structure
- PostgreSQL-ready environment configuration
- Custom user model with admin/staff roles
- Inventory models and APIs
- Customer models and APIs
- Billing models and APIs
- Invoice PDF generation endpoint using WeasyPrint
- Role-based permission scaffolding for admin vs staff visibility
- Read-only daily sales, stock valuation, profit/loss, top-products, and customer reports

## Project structure

```text
.
├── README.md
├── requirements.txt
├── .env.example
├── divya_enterprises/
│   ├── manage.py
│   ├── divya_enterprises/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── wsgi.py
│   │   └── asgi.py
│   ├── accounts/
│   ├── inventory/
│   ├── customers/
│   └── billing/
└── .gitignore
```

## Environment setup

1. Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate   # Linux/macOS
.venv\Scripts\activate      # Windows PowerShell
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy environment variables:

```bash
copy .env.example .env
```

4. Update values in `.env` for your PostgreSQL database.

## Run database migrations

```bash
python manage.py migrate
```

## Create a superuser

```bash
python manage.py createsuperuser
```

## Start the development server

```bash
python manage.py runserver
```

## API base URL

The app exposes API routes under `/api/`.

## Frontend setup

The Vite + React frontend lives in `frontend/` and uses `VITE_API_BASE_URL` for the Django API base URL. Copy `frontend/.env.example` to `frontend/.env`, install dependencies, and start it with:

```bash
cd frontend
npm install
npm run dev
```

Authentication uses the DRF token endpoint at `/api/auth/token/`. The token and current user are kept in `sessionStorage`, never `localStorage`, so signing out or closing the browser tab removes the financial application session. Axios attaches the token to every API request through a request interceptor.

## Reporting endpoints

- `GET /api/reports/daily-sales/?date=YYYY-MM-DD` (defaults to today)
- `GET /api/reports/stock-valuation/`
- `GET /api/reports/profit-loss/?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin only)
- `GET /api/reports/top-products/?from=YYYY-MM-DD&to=YYYY-MM-DD&sort_by=quantity|revenue&limit=10`
- `GET /api/customers/<id>/report/`

Staff can access daily sales, stock valuation, top-products, and customer reports. Cost-price and profit/loss fields are excluded from staff responses, and the profit/loss endpoint returns `403` for staff. Profit/loss uses each product's current `cost_price` because historical cost snapshots are not tracked.

Daily sales keeps sale origin separate from collections: `sold_cash_today` and `sold_on_credit_today` are based on the immutable invoice `payment_type`, while `cash_collected_today` sums payments by `payment_date`, including collections against older credit invoices. The payment-type migration backfills historical invoices with linked payments as cash and unpaid invoices as credit; this is a one-time historical approximation only.

## Confirmed billing rules implemented in schema

This milestone aligns the scaffold to the confirmed business rules:

- stock deduction happens at invoice creation and is modeled as part of the invoice workflow
- invoice line items capture the charged rate and slab-wise tax amount permanently
- credit-note reversal is part of the schema for invoice correction without mutating original invoices
- walk-in cash sales remain distinct from registered customer credit billing via nullable customer references
- payment status is exposed as a read-only computed value, not a client-editable field
- inventory balances are tracked per warehouse and stock changes create structured ledger events
- sale lines snapshot cost and COGS so later product cost changes do not rewrite historical profit
- product deletion archives the product, and payment detail endpoints are read-only
- purchase receipt API updates weighted-average warehouse cost transactionally
- invoice creation supports an `Idempotency-Key` for safe client retries

## Future next steps

- add React frontend in a separate phase

## Docker setup

Set `DB_PASSWORD` and `SECRET_KEY` in the root `.env`, then run `docker compose up --build`. The `web` image includes the Linux libraries required by WeasyPrint and waits on the PostgreSQL service. Do not commit `.env` or production credentials.

The current costing method is weighted average per product and warehouse. The current GST implementation stores slab and line-tax snapshots but is not a legal CGST/SGST/IGST compliance engine; see [INVARIANTS.md](INVARIANTS.md) for the explicit boundaries.

The backend uses PostgreSQL immutability triggers for critical historical tables. Run tests from `divya_enterprises/` so standard `python manage.py test` discovery executes the full suite.

