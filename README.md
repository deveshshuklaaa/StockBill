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

## Confirmed billing rules implemented in schema

This milestone aligns the scaffold to the confirmed business rules:

- stock deduction happens at invoice creation and is modeled as part of the invoice workflow
- invoice line items capture the charged rate and slab-wise tax amount permanently
- credit-note reversal is part of the schema for invoice correction without mutating original invoices
- walk-in cash sales remain distinct from registered customer credit billing via nullable customer references
- payment status is exposed as a read-only computed value, not a client-editable field

## Future next steps

- implement invoice creation transaction logic with stock validation and ledger updates
- implement credit-note reversal logic and outstanding-balance calculations
- add tests for stock deduction, tax calculation, and partial payment status transitions
- add React frontend in a separate phase

