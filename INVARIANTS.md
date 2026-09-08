# StockBill business invariants

- Inventory balances are stored per product and warehouse in base units. `Product.current_stock` remains a compatibility cache equal to the sum of warehouse balances.
- Every balance-changing operation runs inside `transaction.atomic()`, locks the relevant balance with `select_for_update()`, and creates a `StockLedger` event.
- Product conversion factors must be positive. Existing invoice quantities are interpreted as base-unit quantities until display-unit capture is introduced.
- Sale lines snapshot `cost_price_snapshot` and `cogs_amount`; changing a product's current cost does not change historical gross profit.
- Posted invoices are read-only through the API. Corrections use credit notes; products are archived rather than deleted.
- Payments are append-only through the API. A correction requires a future reversal/adjustment transaction.
- Credit notes cannot exceed the original line quantity minus prior reversals and return stock transactionally.
- Invoice creation accepts an `Idempotency-Key`; retries return the original invoice.
- Customer outstanding balance is opening balance plus invoices minus payments minus credit notes.
- GST currently snapshots the configured product slab and line tax values. CGST/SGST/IGST split, HSN/SAC, place of supply, and tax-inclusive pricing are not yet implemented and must not be represented as legal GST compliance.
- Historical migrated products are seeded into `Main Warehouse` with an `OPENING_STOCK` ledger event.
