import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'

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

function calculateLine(line, taxMode) {
  const quantity = Number(line.quantity) || 0
  const rate = Number(line.rate_charged) || 0
  const discount = Number(line.discount_amount) || 0
  const taxRate = Number(line.tax_rate) || 0

  const gross = quantity * rate
  const net = gross - discount
  let taxable = net
  let tax = net * taxRate / 100
  if (taxMode === 'inclusive') {
    taxable = net / (1 + taxRate / 100)
    tax = net - taxable
  }
  return { subtotal: gross, discount, taxable, tax, total: taxable + tax }
}

export default function NewInvoicePage() {
  const [customers, setCustomers] = useState([])
  const [customerSearch, setCustomerSearch] = useState('')
  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [customer, setCustomer] = useState(WALK_IN)
  const [paymentType, setPaymentType] = useState('cash')
  const [taxMode, setTaxMode] = useState('exclusive')
  const [placeOfSupply, setPlaceOfSupply] = useState('')

  const [balance, setBalance] = useState(null)
  const [lines, setLines] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState(null)

  useEffect(() => {
    api.get('/customers/')
      .then((customerResponse) => { setCustomers(rows(customerResponse.data)) })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  // Server-side product search: the catalogue is paginated, so never rely on a
  // single preloaded page. Debounced to avoid a request per keystroke.
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
      setPlaceOfSupply('')
      return
    }
    setPlaceOfSupply(customer.state_code || '')
    api.get(`/customers/${customer.id}/report/`)
      .then(({ data }) => setBalance(data.outstanding_balance))
      .catch((err) => setError(apiErrorMessage(err)))
  }, [customer])

  const filteredCustomers = customers.filter((item) => item.name.toLowerCase().includes(customerSearch.toLowerCase())).slice(0, 8)

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
      setLines([...lines, { key: product.id, product: product.id, productData: product, quantity: 1, rate_charged: product.default_price, discount_amount: 0, tax_rate: Number(product.tax_rate) || 0 }])
    }
    setProductSearch('')
  }

  function updateLine(key, field, value) {
    setLines(lines.map((line) => line.key === key ? { ...line, [field]: value } : line))
  }

  function removeLine(key) {
    setLines(lines.filter((line) => line.key !== key))
  }

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (!lines.length) {
      setError('Add at least one product before creating the invoice.')
      return
    }
    setSubmitting(true)
    try {
      const payload = {
        invoice_number: makeInvoiceNumber(),
        customer: customer.id,
        payment_type: customer.id ? paymentType : 'cash',
        tax_mode: taxMode,
        place_of_supply: placeOfSupply,
        line_items: lines.map((line) => ({ product: line.product, quantity: Number(line.quantity), rate_charged: Number(line.rate_charged), discount_amount: Number(line.discount_amount || 0), tax_rate: line.tax_rate })),
      }
      const { data } = await api.post('/invoices/', payload)
      setSuccess(data)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  function startOver() {
    setSuccess(null)
    setLines([])
    setCustomer(WALK_IN)
    setPaymentType('cash')
    setError('')
  }

  if (loading) return <section className="page-section"><div className="empty-state">Loading invoice workspace...</div></section>
  if (success) return <section className="page-section success-page"><p className="eyebrow">Transaction complete</p><div className="success-mark">OK</div><h1>Invoice created</h1><p className="success-number">{success.invoice_number}</p><p className="page-subtitle">The stock movement and ledger entry were saved successfully.</p><div className="success-actions"><Link className="primary-button" to={`/invoices/${success.id}`}>View / print invoice</Link><button className="quiet-button" onClick={startOver}>New invoice</button></div></section>

  return <section className="page-section invoice-page">
    <header className="page-header invoice-header"><div><p className="eyebrow">Billing / new transaction</p><h1>New invoice</h1><p className="page-subtitle">Exact GST splits are computed deterministically when saved.</p></div><Link className="quiet-button" to="/products">Back to products</Link></header>
    <StatusMessage>{error}</StatusMessage>
    <form onSubmit={submit} className="invoice-layout">
      <div className="invoice-workspace">
        <section className="invoice-card customer-card"><div className="section-kicker">01 / Customer</div><div className="customer-picker"><input value={customer.id ? customer.name : customerSearch} onChange={(event) => { setCustomerSearch(event.target.value); if (customer.id) setCustomer(WALK_IN) }} placeholder="Search customer by name..." aria-label="Search customer" />{customerSearch && <div className="suggestion-list">{filteredCustomers.map((item) => <button type="button" key={item.id} onClick={() => chooseCustomer(item)}><strong>{item.name}</strong><span>{item.customer_type}{item.gstin ? ` · ${item.gstin}` : ''}</span></button>)}{!filteredCustomers.length && <div className="suggestion-empty">No matching customer</div>}</div>}</div><button type="button" className={customer.id ? 'walk-in-option' : 'walk-in-option selected'} onClick={() => chooseCustomer(WALK_IN)}>Walk-in (no account)<span>{customer.id ? 'Switch' : 'Selected'}</span></button>{customer.id && <div className="customer-context"><strong>{customer.name}</strong><span>{customer.customer_type} account</span><b>{balance === null ? 'Loading balance...' : `${money(balance)} outstanding`}</b></div>}</section>
        <section className="invoice-card"><div className="section-heading"><div><div className="section-kicker">02 / Configuration</div><h2>Payment & Tax</h2></div><div className="payment-toggle"><button type="button" className={paymentType === 'cash' ? 'selected' : ''} onClick={() => setPaymentType('cash')}>Cash</button><button type="button" className={paymentType === 'credit' ? 'selected' : ''} onClick={() => setPaymentType('credit')} disabled={!customer.id}>Credit</button></div></div>
          {!customer.id && <p className="inline-note" style={{ marginBottom: 10 }}>Walk-in sales are cash only.</p>}
          <div style={{ display: 'flex', gap: '20px', marginTop: '10px' }}>
            <label style={{ flex: 1 }}>Place of supply (State Code)<input value={placeOfSupply} onChange={e => setPlaceOfSupply(e.target.value)} maxLength="2" placeholder="e.g 27" style={{ marginTop: '5px' }} /></label>
            <label style={{ flex: 1 }}>Tax Mode<select value={taxMode} onChange={e => setTaxMode(e.target.value)} style={{ marginTop: '5px', padding: '10px' }}><option value="exclusive">Exclusive</option><option value="inclusive">Inclusive</option></select></label>
          </div>
        </section>

        <section className="invoice-card lines-card"><div className="section-heading"><div><div className="section-kicker">03 / Items</div><h2>What is going out?</h2></div><span className="line-count">{lines.length} line{lines.length === 1 ? '' : 's'}</span></div><div className="product-search"><input value={productSearch} onChange={(event) => setProductSearch(event.target.value)} placeholder="Search products by name to add..." aria-label="Search products" />{productSearch && <div className="suggestion-list product-suggestions">{productBusy && !productResults.length && <div className="suggestion-empty">Searching...</div>}{productResults.map((product) => <button type="button" key={product.id} onClick={() => addProduct(product)}><strong>{product.name}</strong><span>{product.current_stock} {product.unit_type} available · {money(product.default_price)}</span></button>)}{!productBusy && !productResults.length && <div className="suggestion-empty">No matching product</div>}</div>}</div>{!lines.length ? <div className="lines-empty">Start typing above to add the first product.</div> : <div className="invoice-lines">{lines.map((line, index) => { const calculated = calculateLine(line, taxMode); const overStock = Number(line.quantity) > Number(line.productData.current_stock); const fixedUnit = Number(line.productData.unit_conversion_factor) <= 1; return <div className="invoice-line" key={line.key}><div className="line-number">{String(index + 1).padStart(2, '0')}</div><div className="line-product"><strong>{line.productData.name}</strong><span>{line.productData.unit_type} · {line.productData.current_stock} available</span></div><label>Qty<input type="number" min="0.001" step={fixedUnit ? '1' : '0.001'} value={line.quantity} onChange={(event) => updateLine(line.key, 'quantity', event.target.value)} className={overStock ? 'input-warning' : ''} /></label><label>Rate<input type="number" min="0" step="0.01" value={line.rate_charged} onChange={(event) => updateLine(line.key, 'rate_charged', event.target.value)} /></label><label>Discount<input type="number" min="0" step="0.01" value={line.discount_amount} onChange={(event) => updateLine(line.key, 'discount_amount', event.target.value)} /></label><div className="line-tax"><span>GST</span><strong>{line.tax_rate}%</strong></div><div className="line-total"><span>Total</span><strong>{money(calculated.total)}</strong></div><button type="button" className="remove-line" onClick={() => removeLine(line.key)} aria-label={`Remove ${line.productData.name}`}>×</button>{overStock && <div className="stock-warning">Quantity exceeds available stock ({line.productData.current_stock}). The server will reject this invoice.</div>}</div> })}</div>}</section>
      </div>
      <aside className="invoice-summary"><div className="summary-label">Preview summary</div><div className="summary-customer">{customer.id ? customer.name : 'Walk-in sale'}<span>{paymentType === 'cash' ? 'Cash sale' : 'Credit sale'}</span></div><div className="summary-rows"><div><span>Subtotal</span><strong>{money(totals.subtotal)}</strong></div><div><span>Total Discount</span><strong>{money(totals.discount)}</strong></div><div><span>Taxable</span><strong>{money(totals.taxable)}</strong></div>{Object.entries(totals.taxBySlab).sort(([a], [b]) => Number(a) - Number(b)).map(([slab, value]) => <div key={slab}><span>{slab}% GST</span><strong>{money(value)}</strong></div>)}<div className="summary-tax"><span>Total tax preview</span><strong>{money(totals.tax)}</strong></div></div><div className="grand-total"><span>Grand total (Est.)</span><strong>{money(totals.total)}</strong></div><button type="button" className="primary-button submit-invoice" onClick={submit} disabled={submitting || !lines.length}>{submitting ? 'Saving invoice...' : 'Create invoice'}</button><p className="summary-note">Server evaluates taxes with determinism upon submission. Deducts stock immediately.</p></aside>
    </form>
  </section>
}
