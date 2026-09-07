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

## Reporting endpoints

- `GET /api/reports/daily-sales/?date=YYYY-MM-DD` (defaults to today)
- `GET /api/reports/stock-valuation/`
- `GET /api/reports/profit-loss/?from=YYYY-MM-DD&to=YYYY-MM-DD` (admin only)
- `GET /api/reports/top-products/?from=YYYY-MM-DD&to=YYYY-MM-DD&sort_by=quantity|revenue&limit=10`
- `GET /api/customers/<id>/report/`

Staff can access daily sales, stock valuation, top-products, and customer reports. Cost-price and profit/loss fields are excluded from staff responses, and the profit/loss endpoint returns `403` for staff. Profit/loss uses each product's current `cost_price` because historical cost snapshots are not tracked.

## Confirmed billing rules implemented in schema

This milestone aligns the scaffold to the confirmed business rules:

- stock deduction happens at invoice creation and is modeled as part of the invoice workflow
- invoice line items capture the charged rate and slab-wise tax amount permanently
- credit-note reversal is part of the schema for invoice correction without mutating original invoices
- walk-in cash sales remain distinct from registered customer credit billing via nullable customer references
- payment status is exposed as a read-only computed value, not a client-editable field

## Future next steps

- add React frontend in a separate phase

