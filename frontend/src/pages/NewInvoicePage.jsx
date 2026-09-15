import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import { amendInvoice, fetchInvoice, updateDraftInvoice } from '../api/invoices'
import StatusMessage from '../components/StatusMessage'
import { formatNetWeight, formatQuantityWithUnit, formatStockWithBoxes, masterBoxSize } from '../utils/format'

const WALK_IN = { id: null, name: 'Walk-in (no account)', customer_type: 'B2C' }

function rows(data) {
  return Array.isArray(data) ? data : data?.results || []
}

function money(value) {
  return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}`
}

function makeInvoiceNumber() {
  const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
  return `INV-${stamp}`
}

function variantSummary(product) {
  const parts = []
  const weight = formatNetWeight(product?.attributes?.net_weight)
  if (weight) parts.push(weight)
  if (product.mrp != null) parts.push(`MRP ₹${Number(product.mrp).toFixed(2)}`)
  if (product.sku) parts.push(`SKU: ${product.sku}`)
  if (product.category_name) parts.push(product.category_name)
  return parts.join(' · ')
}

function calculateLine(line, taxMode) {
  const quantity = Number(line.quantity) || 0
  const factor = Number(line.conversionFactor) || 1
  const baseQty = quantity * factor
  const rate = Number(line.rate_charged) || 0
  const discount = Number(line.discount_amount) || 0
  const taxRate = Number(line.tax_rate) || 0

  const gross = baseQty * rate
  const net = gross - discount
  let taxable = net
  let tax = net * taxRate / 100
  if (taxMode === 'inclusive') {
    taxable = net / (1 + taxRate / 100)
    tax = net - taxable
  }
  return { subtotal: gross, discount, taxable, tax, total: taxable + tax, baseQty }
}

export default function NewInvoicePage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const editDraftId = searchParams.get('edit')   // ?edit=<draftId>  → edit DRAFT
  const amendId     = searchParams.get('amend')  // ?amend=<id>      → correct POSTED

  const isEditMode  = Boolean(editDraftId)
  const isAmendMode = Boolean(amendId)

  const [customers, setCustomers] = useState([])
  const [customerSearch, setCustomerSearch] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [customer, setCustomer] = useState(WALK_IN)
  const [paymentType, setPaymentType] = useState('cash')
  const [taxMode, setTaxMode] = useState('exclusive')
  const [placeOfSupply, setPlaceOfSupply] = useState('')
  const [notes, setNotes] = useState('')

  const [balance, setBalance] = useState(null)
  const [lines, setLines] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)

  // Amendment-only
  const [amendReason, setAmendReason] = useState('')
  const [originalInvoice, setOriginalInvoice] = useState(null)

  // Load initial customer list
  useEffect(() => {
    api.get('/customers/', { params: { is_active: 'true', page: 1 } })
      .then((customerResponse) => { setCustomers(rows(customerResponse.data)) })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => { if (!isEditMode && !isAmendMode) setLoading(false) })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Preload draft (edit mode) or original invoice (amend mode)
  useEffect(() => {
    const sourceId = editDraftId || amendId
    if (!sourceId) { setLoading(false); return }

    fetchInvoice(sourceId)
      .then(async (inv) => {
        if (isAmendMode) setOriginalInvoice(inv)
        if (inv.customer) {
          try {
            const { data: cust } = await api.get(`/customers/${inv.customer}/`)
            setCustomer(cust)
            setPlaceOfSupply(cust.state_code || inv.place_of_supply || '')
          } catch { setCustomer(WALK_IN) }
        } else {
          setCustomer(WALK_IN)
        }
        setPaymentType(inv.payment_type || 'cash')
        setTaxMode(inv.tax_mode || 'exclusive')
        setPlaceOfSupply((prev) => prev || inv.place_of_supply || '')
        setNotes(inv.notes || '')

        const lineDetails = await Promise.all(
          (inv.line_items || []).map(async (line) => {
            try {
              const { data: product } = await api.get(`/products/${line.product}/`)
              return {
                key: `${line.product}-${Math.random()}`,
                product: line.product,
                productData: product,
                quantity: Number(line.quantity),
                salesUnit: line.sales_unit_name || 'piece',
                conversionFactor: Number(line.conversion_factor || 1),
                rate_charged: Number(line.rate_charged),
                discount_amount: Number(line.discount_amount || 0),
                tax_rate: Number(line.tax_rate || 0),
              }
            } catch { return null }
          })
        )
        setLines(lineDetails.filter(Boolean))
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [editDraftId, amendId]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const query = customerSearch.trim()
    if (!query) return undefined
    let cancelled = false
    const timer = setTimeout(() => {
      api.get('/customers/', { params: { search: query, is_active: 'true', page: 1 } })
        .then(({ data }) => { if (!cancelled) setCustomers(rows(data).slice(0, 8)) })
        .catch(() => { if (!cancelled) setCustomers([]) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer) }
  }, [customerSearch])

  useEffect(() => {
    const query = productSearch.trim()
    if (!query) { setProductResults([]); setProductBusy(false); return undefined }
    let cancelled = false
    setProductBusy(true)
    const timer = setTimeout(() => {
      api.get('/products/', { params: { search: query, is_active: 'true', page: 1 } })
        .then(({ data }) => { if (!cancelled) setProductResults(rows(data).slice(0, 8)) })
        .catch(() => { if (!cancelled) setProductResults([]) })
        .finally(() => { if (!cancelled) setProductBusy(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer); setProductBusy(false) }
  }, [productSearch])

  useEffect(() => {
    if (!customer.id) {
      setBalance(null)
      setPaymentType('cash')
      if (!isEditMode && !isAmendMode) setPlaceOfSupply('')
      return
    }
    if (!isEditMode && !isAmendMode) setPlaceOfSupply(customer.state_code || '')
    api.get(`/customers/${customer.id}/report/`)
      .then(({ data }) => setBalance(data.outstanding_balance))
      .catch((err) => setError(apiErrorMessage(err)))
  }, [customer]) // eslint-disable-line react-hooks/exhaustive-deps

  const filteredCustomers = customers.slice(0, 8)

  const totals = useMemo(() => lines.reduce((result, line) => {
    const calculated = calculateLine(line, taxMode)
    result.subtotal += calculated.subtotal
    result.discount += calculated.discount
    result.taxable += calculated.taxable
    result.tax += calculated.tax
    result.total += calculated.total
    result.taxBySlab[line.tax_rate] = (result.taxBySlab[line.tax_rate] || 0) + calculated.tax
    return result
  }, { subtotal: 0, discount: 0, taxable: 0, tax: 0, total: 0, taxBySlab: {} }), [lines, taxMode])

  function chooseCustomer(value) {
    setCustomer(value)
    setCustomerSearch('')
    if (value.id) setPlaceOfSupply(value.state_code || '')
  }

  function addProduct(product) {
    const existing = lines.find((line) => line.product === product.id)
    if (existing) {
      updateLine(existing.key, 'quantity', Number(existing.quantity || 0) + 1)
    } else {
      setLines([...lines, {
        key: product.id,
        product: product.id,
        productData: product,
        quantity: 1,
        salesUnit: 'piece',
        conversionFactor: 1,
        rate_charged: product.mrp != null ? Number(product.mrp) : '',
        discount_amount: 0,
        tax_rate: Number(product.tax_rate) || 0,
      }])
    }
    setProductSearch('')
  }

  function updateLine(key, field, value) {
    setLines(lines.map((line) => {
      if (line.key !== key) return line
      const next = { ...line, [field]: value }
      if (field === 'salesUnit') {
        const box = masterBoxSize(line.productData)
        if (value === 'master box' && box) {
          next.conversionFactor = box
          next.quantity = 1
        } else {
          next.conversionFactor = 1
        }
      }
      return next
    }))
  }

  function removeLine(key) {
    setLines(lines.filter((line) => line.key !== key))
  }

  async function submit(event, asDraft = false) {
    if (event) event.preventDefault()
    if (submitting) return
    setError('')
    if (!lines.length) {
      setError('Add at least one product before creating the invoice.')
      return
    }
    if (isAmendMode && !amendReason.trim()) {
      setError('A correction reason is required before submitting.')
      return
    }
    setSubmitting(true)

    const lineItems = lines.map((line) => ({
      product: line.product,
      quantity: Number(line.quantity),
      sales_unit_name: line.salesUnit,
      conversion_factor: Number(line.conversionFactor),
      // rate_charged is ALWAYS per base unit/piece
      rate_charged: Number(line.rate_charged),
      discount_amount: Number(line.discount_amount || 0),
      tax_rate: line.tax_rate,
    }))

    try {
      if (isEditMode) {
        const payload = {
          customer: customer.id,
          payment_type: customer.id ? paymentType : 'cash',
          tax_mode: taxMode,
          place_of_supply: placeOfSupply,
          notes,
          line_items: lineItems,
        }
        const data = await updateDraftInvoice(editDraftId, payload)
        navigate(`/invoices/${data.id}`)
        return
      }

      if (isAmendMode) {
        const stamp = new Date().toISOString().replace(/[-:TZ.]/g, '').slice(0, 14)
        const payload = {
          reason: amendReason.trim(),
          invoice_number: `INV-${stamp}`,
          customer: customer.id,
          payment_type: customer.id ? paymentType : 'cash',
          tax_mode: taxMode,
          place_of_supply: placeOfSupply,
          notes,
          line_items: lineItems,
        }
        const result = await amendInvoice(amendId, payload)
        navigate(`/invoices/${result.replacement.id}`)
        return
      }

      // Normal creation (draft or posted)
      const payload = {
        invoice_number: makeInvoiceNumber(),
        customer: customer.id,
        payment_type: customer.id ? paymentType : 'cash',
        tax_mode: taxMode,
        place_of_supply: placeOfSupply,
        notes,
        line_items: lineItems,
      }
      const idempotencyKey = `invoice-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
      const url = asDraft ? '/invoices/drafts/' : '/invoices/'
      const { data } = await api.post(url, payload, {
        headers: { 'Idempotency-Key': idempotencyKey },
      })
      navigate(`/invoices/${data.id}`)
    } catch (err) {
      setError(apiErrorMessage(err, { action: isEditMode ? 'saving draft' : isAmendMode ? 'correcting invoice' : asDraft ? 'saving draft' : 'creating invoice' }))
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) return <section className="page-section"><div className="empty-state">Loading invoice workspace...</div></section>

  const pageTitle    = isEditMode ? 'Edit draft invoice' : isAmendMode ? 'Correct invoice' : 'New invoice'
  const pageEyebrow  = isEditMode ? 'Billing / edit draft' : isAmendMode ? `Billing / correct ${originalInvoice?.invoice_number || ''}` : 'Billing / new transaction'
  const submitLabel  = isEditMode ? 'Save draft' : isAmendMode ? 'Create correction' : 'Create invoice'
  const submitNote   = isEditMode ? 'Draft saved without stock movement.' : isAmendMode ? 'Original cancelled + replacement created atomically.' : 'Server evaluates taxes with determinism upon submission. Deducts stock immediately.'

  return (
    <section className="page-section invoice-page">
      <header className="page-header invoice-header">
        <div>
          <p className="eyebrow">{pageEyebrow}</p>
          <h1>{pageTitle}</h1>
          <p className="page-subtitle">
            {isEditMode && 'Changes are saved to draft. Stock is not affected until posted.'}
            {isAmendMode && 'The original invoice will be cancelled and replaced atomically. Rate is always per piece/base unit.'}
            {!isEditMode && !isAmendMode && 'Exact GST splits are computed deterministically when saved.'}
          </p>
        </div>
        {isAmendMode && <Link className="quiet-button" to={`/invoices/${amendId}`}>← Back to original</Link>}
        {isEditMode  && <Link className="quiet-button" to={`/invoices/${editDraftId}`}>← Back to draft</Link>}
        {!isEditMode && !isAmendMode && <Link className="quiet-button" to="/products">Back to products</Link>}
      </header>
      <StatusMessage>{error}</StatusMessage>

      {isAmendMode && (
        <div className="record-form" style={{ marginBottom: 20 }}>
          <div className="form-heading"><div><p className="eyebrow">Amendment</p><h2>Correction reason (required)</h2></div></div>
          <label style={{ display: 'block' }}>
            Reason
            <textarea
              id="amend-reason"
              style={{ display: 'block', width: '100%', marginTop: 6, border: '1px solid #cbd5cd', padding: '10px 11px', fontFamily: 'inherit', resize: 'vertical', borderRadius: 6 }}
              rows={2}
              value={amendReason}
              onChange={(e) => setAmendReason(e.target.value)}
              placeholder="Why is this invoice being corrected? (e.g. wrong quantity, wrong rate)"
              aria-label="Correction reason"
            />
          </label>
          {originalInvoice && (
            <p style={{ marginTop: 8, fontSize: 13, color: '#666' }}>
              Original invoice <strong>{originalInvoice.invoice_number}</strong> will be cancelled and a new replacement will be created. Payments against the original must be re-recorded against the replacement.
            </p>
          )}
        </div>
      )}

      <form onSubmit={submit} className="invoice-layout">
        <div className="invoice-workspace">
          <section className="invoice-card customer-card">
            <div className="section-kicker">01 / Customer</div>
            <div className="customer-picker">
              <input
                value={customer.id ? customer.name : customerSearch}
                onChange={(event) => { setCustomerSearch(event.target.value); if (customer.id) setCustomer(WALK_IN) }}
                placeholder="Search customer by name..."
                aria-label="Search customer"
              />
              {customerSearch && (
                <div className="suggestion-list">
                  {filteredCustomers.map((item) => (
                    <button type="button" key={item.id} onClick={() => chooseCustomer(item)}>
                      <strong>{item.name}</strong>
                      <span>{[item.customer_type, item.contact_info, item.gstin].filter(Boolean).join(' · ')}</span>
                    </button>
                  ))}
                  {!filteredCustomers.length && <div className="suggestion-empty">No matching customer</div>}
                </div>
              )}
            </div>
            <button
              type="button"
              className={customer.id ? 'walk-in-option' : 'walk-in-option selected'}
              onClick={() => chooseCustomer(WALK_IN)}
            >
              Walk-in (no account)<span>{customer.id ? 'Switch' : 'Selected'}</span>
            </button>
            {customer.id && (
              <div className="customer-context">
                <strong>{customer.name}</strong>
                <span>{customer.customer_type} account</span>
                <b>{balance === null ? 'Loading balance...' : `${money(balance)} outstanding`}</b>
              </div>
            )}
          </section>
          <section className="invoice-card">
            <div className="section-heading">
              <div>
                <div className="section-kicker">02 / Configuration</div>
                <h2>Payment & Tax</h2>
              </div>
              <div className="payment-toggle">
                <button type="button" className={paymentType === 'cash' ? 'selected' : ''} onClick={() => setPaymentType('cash')}>Cash</button>
                <button type="button" className={paymentType === 'credit' ? 'selected' : ''} onClick={() => setPaymentType('credit')} disabled={!customer.id}>Credit</button>
              </div>
            </div>
            {!customer.id && <p className="inline-note" style={{ marginBottom: 10 }}>Walk-in sales are cash only.</p>}
            <div style={{ display: 'flex', gap: '20px', marginTop: '10px' }}>
              <label style={{ flex: 1 }}>Place of supply (State Code)<input value={placeOfSupply} onChange={e => setPlaceOfSupply(e.target.value)} maxLength="2" placeholder="e.g 27" style={{ marginTop: '5px' }} /></label>
              <label style={{ flex: 1 }}>Tax Mode<select value={taxMode} onChange={e => setTaxMode(e.target.value)} style={{ marginTop: '5px', padding: '10px' }}><option value="exclusive">Exclusive</option><option value="inclusive">Inclusive</option></select></label>
            </div>
            <label style={{ display: 'block', marginTop: '10px' }}>Notes<input value={notes} onChange={e => setNotes(e.target.value)} placeholder="Optional notes on invoice" style={{ marginTop: '5px' }} /></label>
          </section>

          <section className="invoice-card lines-card">
            <div className="section-heading">
              <div>
                <div className="section-kicker">03 / Items</div>
                <h2>What is going out?</h2>
              </div>
              <span className="line-count">{lines.length} line{lines.length === 1 ? '' : 's'}</span>
            </div>
            <div className="product-search">
              <input value={productSearch} onChange={(event) => setProductSearch(event.target.value)} placeholder="Search products by name to add..." aria-label="Search products" />
              {productSearch && (
                <div className="suggestion-list product-suggestions">
                  {productBusy && !productResults.length && <div className="suggestion-empty">Searching...</div>}
                  {productResults.map((product) => {
                    const summary = variantSummary(product)
                    const stock = formatStockWithBoxes(product.current_stock, product)
                    return (
                      <button type="button" key={product.id} onClick={() => addProduct(product)}>
                        <strong>{product.name}</strong>
                        {summary && <span className="variant-line">{summary}</span>}
                        <span>{stock} available{product.mrp != null ? ` · MRP ₹${Number(product.mrp).toFixed(2)}` : ''}</span>
                      </button>
                    )
                  })}
                  {!productBusy && !productResults.length && <div className="suggestion-empty">No matching product</div>}
                </div>
              )}
            </div>
            {!lines.length ? (
              <div className="lines-empty">Start typing above to add the first product.</div>
            ) : (
              <div className="invoice-lines">
                {lines.map((line, index) => {
                  const calculated = calculateLine(line, taxMode)
                  const box = masterBoxSize(line.productData)
                  const baseQty = Number(line.quantity || 0) * Number(line.conversionFactor || 1)
                  const overStock = baseQty > Number(line.productData.current_stock)
                  const fixedUnit = Number(line.productData.unit_conversion_factor) <= 1
                  return (
                    <div className="invoice-line" key={line.key}>
                      <div className="line-number">{String(index + 1).padStart(2, '0')}</div>
                      <div className="line-product">
                        <strong>{line.productData.name}</strong>
                        <span>{formatStockWithBoxes(line.productData.current_stock, line.productData)} available</span>
                        {line.salesUnit === 'master box' && box ? (
                          <span className="variant-line">
                            {line.quantity || 0} Box × {box} = {formatQuantityWithUnit(baseQty, line.productData.base_unit || 'piece')}
                            {' · '}rate ₹{Number(line.rate_charged || 0).toFixed(2)}/pc
                          </span>
                        ) : (
                          <span className="variant-line">
                            {baseQty} {line.productData.base_unit || 'pieces'}
                            {' · '}rate ₹{Number(line.rate_charged || 0).toFixed(2)}/pc
                          </span>
                        )}
                      </div>
                      <label>Unit
                        <select
                          value={line.salesUnit}
                          onChange={(event) => updateLine(line.key, 'salesUnit', event.target.value)}
                          aria-label={`Sales unit for ${line.productData.name}`}
                        >
                          <option value="piece">{line.productData.base_unit === 'piece' ? 'Piece' : line.productData.base_unit || 'Piece'}</option>
                          {box && <option value="master box">Master Box ({box})</option>}
                        </select>
                      </label>
                      <label>Qty<input type="number" min="0.001" step={fixedUnit ? '1' : '0.001'} value={line.quantity} onChange={(event) => updateLine(line.key, 'quantity', event.target.value)} className={overStock ? 'input-warning' : ''} /></label>
                      <label>Rate / Piece<input type="number" min="0" step="0.01" value={line.rate_charged} onChange={(event) => updateLine(line.key, 'rate_charged', event.target.value)} placeholder="₹ / piece" aria-label={`Selling rate per piece for ${line.productData.name}`} /></label>
                      <label>Disc<input type="number" min="0" step="0.01" value={line.discount_amount} onChange={(event) => updateLine(line.key, 'discount_amount', event.target.value)} /></label>
                      <div className="line-tax">{line.tax_rate}%</div>
                      <div className="line-total">{money(calculated.total)}</div>
                      <button type="button" className="remove-line" onClick={() => removeLine(line.key)} aria-label="Remove line">×</button>
                    </div>
                  )
                })}
              </div>
            )}
          </section>
        </div>
        <aside className="invoice-summary">
          <div className="summary-label">Preview summary</div>
          <div className="summary-customer">{customer.id ? customer.name : 'Walk-in sale'}<span>{paymentType === 'cash' ? 'Cash sale' : 'Credit sale'}</span></div>
          <div className="summary-rows">
            <div><span>Subtotal</span><strong>{money(totals.subtotal)}</strong></div>
            <div><span>Total Discount</span><strong>{money(totals.discount)}</strong></div>
            <div><span>Taxable</span><strong>{money(totals.taxable)}</strong></div>
            {Object.entries(totals.taxBySlab).sort(([a], [b]) => Number(a) - Number(b)).map(([slab, value]) => (
              <div key={slab}><span>{slab}% GST</span><strong>{money(value)}</strong></div>
            ))}
            <div className="summary-tax"><span>Total tax preview</span><strong>{money(totals.tax)}</strong></div>
          </div>
          <div className="grand-total"><span>Grand total (Est.)</span><strong>{money(totals.total)}</strong></div>
          <button type="button" id="submit-invoice-btn" className="primary-button submit-invoice" onClick={(e) => submit(e, false)} disabled={submitting || !lines.length}>
            {submitting ? 'Saving...' : submitLabel}
          </button>
          {!isEditMode && !isAmendMode && (
            <button type="button" id="save-draft-btn" className="quiet-button submit-invoice" style={{ marginTop: 8 }} onClick={(e) => submit(e, true)} disabled={submitting || !lines.length}>
              Save as draft
            </button>
          )}
          <p className="summary-note">{submitNote}</p>
        </aside>
      </form>
    </section>
  )
}