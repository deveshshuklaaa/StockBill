import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import { fetchNextPurchaseNumber, fetchSuppliers, fetchWarehouses, searchPurchaseProducts } from '../api/purchases'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

function today() { return new Date().toISOString().slice(0, 10) }

function masterBoxSize(product) {
  const box = Number(product?.attributes?.units_per_master_box)
  return Number.isInteger(box) && box > 0 ? box : null
}

function calculateLine(line, taxMode) {
  const quantity = Number(line.quantity) || 0
  const rate = Number(line.rate) || 0
  const discount = Number(line.discount_amount) || 0
  const factor = Number(line.conversion_factor) || 1
  const taxRate = Number(line.taxRate) || 0

  const gross = quantity * rate
  const net = gross - discount
  let taxable = net
  let tax = net * taxRate / 100
  if (taxMode === 'inclusive') {
    taxable = net / (1 + taxRate / 100)
    tax = net - taxable
  }
  const baseQty = quantity * factor
  const unitCost = baseQty > 0 ? taxable / baseQty : 0
  return { gross, discount, taxable, tax, total: taxable + tax, baseQty, unitCost }
}

export default function NewPurchasePage() {
  const navigate = useNavigate()
  const [suppliers, setSuppliers] = useState([])
  const [warehouses, setWarehouses] = useState([])
  const [supplier, setSupplier] = useState(null)
  const [supplierSearch, setSupplierSearch] = useState('')
  const [invoiceDate, setInvoiceDate] = useState(today())
  const [supplierInvoiceNo, setSupplierInvoiceNo] = useState('')
  const [warehouseId, setWarehouseId] = useState('')
  const [taxMode, setTaxMode] = useState('exclusive')
  const [notes, setNotes] = useState('')
  const [nextNumber, setNextNumber] = useState('')

  const [productSearch, setProductSearch] = useState('')
  const [productResults, setProductResults] = useState([])
  const [productBusy, setProductBusy] = useState(false)
  const [lines, setLines] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [posting, setPosting] = useState(false)

  useEffect(() => {
    Promise.all([fetchSuppliers(), fetchWarehouses()])
      .then(([supplierRows, warehouseRows]) => {
        setSuppliers(supplierRows)
        setWarehouses(warehouseRows)
        if (warehouseRows.length === 1) setWarehouseId(String(warehouseRows[0].id))
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    fetchNextPurchaseNumber(invoiceDate)
      .then((number) => { if (!cancelled) setNextNumber(number) })
      .catch(() => {})
    return () => { cancelled = true }
  }, [invoiceDate])

  useEffect(() => {
    const query = productSearch.trim()
    if (!query) { setProductResults([]); setProductBusy(false); return undefined }
    let cancelled = false
    setProductBusy(true)
    const timer = setTimeout(() => {
      searchPurchaseProducts(query)
        .then(({ data }) => { if (!cancelled) setProductResults((data.results || []).slice(0, 8)) })
        .catch(() => { if (!cancelled) setProductResults([]) })
        .finally(() => { if (!cancelled) setProductBusy(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer); setProductBusy(false) }
  }, [productSearch])

  const filteredSuppliers = suppliers.filter((item) => item.name.toLowerCase().includes(supplierSearch.toLowerCase())).slice(0, 8)

  const totals = useMemo(() => lines.reduce((result, line) => {
    const calculated = calculateLine(line, taxMode)
    result.subtotal += calculated.gross
    result.discount += calculated.discount
    result.taxable += calculated.taxable
    result.tax += calculated.tax
    result.total += calculated.total
    return result
  }, { subtotal: 0, discount: 0, taxable: 0, tax: 0, total: 0 }), [lines, taxMode])

  function addProduct(product) {
    const box = masterBoxSize(product)
    const existing = lines.find((line) => line.product === product.id)
    if (existing) {
      updateLine(existing.key, 'quantity', Number(existing.quantity || 0) + 1)
    } else {
      setLines((current) => [...current, {
        key: product.id,
        product: product.id,
        productData: product,
        quantity: 1,
        purchaseUnit: 'piece',
        conversionFactor: 1,
        rate: '',
        discountAmount: '',
        taxRate: Number(product.tax_rate) || 0,
      }])
    }
    setProductSearch('')
  }

  function updateLine(key, field, value) {
    setLines((current) => current.map((line) => {
      if (line.key !== key) return line
      const next = { ...line, [field]: value }
      if (field === 'purchaseUnit') {
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
    setLines((current) => current.filter((line) => line.key !== key))
  }

  function chooseSupplier(value) {
    setSupplier(value)
    setSupplierSearch('')
  }

  function validate() {
    if (!supplier?.id) return 'Select a supplier before saving.'
    if (!warehouseId) return 'Select a receiving warehouse.'
    if (!lines.length) return 'Add at least one product line.'
    for (const line of lines) {
      if (!(Number(line.quantity) > 0)) return `Quantity for ${line.productData.name} must be positive.`
      if (!(Number(line.rate) >= 0) || line.rate === '') return `Enter the purchase rate for ${line.productData.name}.`
    }
    return ''
  }

  async function submit(post) {
    const problem = validate()
    if (problem) { setError(problem); return }
    if (post) { setPosting(true) } else { setSaving(true) }
    setError('')
    try {
      const payload = {
        supplier: supplier.id,
        warehouse: Number(warehouseId),
        supplier_invoice_no: supplierInvoiceNo.trim(),
        invoice_date: invoiceDate,
        tax_mode: taxMode,
        notes,
        post,
        line_items: lines.map((line) => ({
          product: line.product,
          quantity: Number(line.quantity),
          purchase_unit_name: line.purchaseUnit,
          conversion_factor: Number(line.conversionFactor),
          rate: Number(line.rate),
          discount_amount: Number(line.discount_amount || line.discountAmount || 0),
        })),
      }
      const idempotencyKey = `purchase-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
      const { data } = await api.post('/purchase-invoices/', payload, {
        headers: { 'Idempotency-Key': idempotencyKey },
      })
      navigate(`/purchases/${data.id}`)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setSaving(false); setPosting(false)
    }
  }

  if (loading) return <section className="page-section"><div className="empty-state">Loading purchase workspace...</div></section>

  return <section className="page-section invoice-page">
    <header className="page-header invoice-header">
      <div><p className="eyebrow">Purchasing / goods inward</p><h1>New purchase</h1><p className="page-subtitle">Next number on posting: <strong>{nextNumber || '—'}</strong></p></div>
      <Link className="quiet-button" to="/purchases">Back to purchases</Link>
    </header>
    <StatusMessage>{error}</StatusMessage>

    <div className="invoice-layout">
      <div className="invoice-workspace">
        <section className="invoice-card customer-card">
          <div className="section-kicker">01 / Supplier</div>
          <div className="customer-picker">
            <input value={supplier?.id ? supplier.name : supplierSearch} onChange={(event) => { setSupplierSearch(event.target.value); if (supplier?.id) setSupplier(null) }} placeholder="Search supplier by name..." aria-label="Search supplier" />
            {supplierSearch && !supplier?.id && <div className="suggestion-list">
              {filteredSuppliers.map((item) => <button type="button" key={item.id} onClick={() => chooseSupplier(item)}><strong>{item.name}</strong><span>{item.state || 'State not set'}{item.gstin ? ` · ${item.gstin}` : ''}</span></button>)}
              {!filteredSuppliers.length && <div className="suggestion-empty">No matching supplier</div>}
            </div>}
          </div>
          {supplier?.id && <div className="customer-context">
            <strong>{supplier.name}</strong>
            <span>{supplier.gstin || 'Unregistered'}</span>
            <b>{supplier.state ? `${supplier.state} (${supplier.state_code || '?'})` : 'State not set'}</b>
          </div>}
        </section>

        <section className="invoice-card">
          <div className="section-heading">
            <div><div className="section-kicker">02 / Document</div><h2>Bill details</h2></div>
          </div>
          <div className="form-grid" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
            <label>Purchase date<input type="date" value={invoiceDate} onChange={(e) => setInvoiceDate(e.target.value)} required /></label>
            <label>Supplier bill no<input value={supplierInvoiceNo} onChange={(e) => setSupplierInvoiceNo(e.target.value)} placeholder="As printed on the bill" /></label>
            <label>Receiving warehouse<select value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} required><option value="">Select warehouse</option>{warehouses.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></label>
            <label>Tax mode<select value={taxMode} onChange={(e) => setTaxMode(e.target.value)}><option value="exclusive">Exclusive</option><option value="inclusive">Inclusive</option></select></label>
          </div>
          <label className="filter-field" style={{ marginTop: 14, display: 'block' }}>Notes<textarea style={{ display: 'block', width: '100%', marginTop: 6, border: '1px solid #cbd5cd', padding: '10px 11px', fontFamily: 'inherit', resize: 'vertical' }} rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional reference notes" /></label>
        </section>

        <section className="invoice-card lines-card">
          <div className="section-heading">
            <div><div className="section-kicker">03 / Items</div><h2>What is coming in?</h2></div>
            <span className="line-count">{lines.length} line{lines.length === 1 ? '' : 's'}</span>
          </div>
          <div className="product-search">
            <input value={productSearch} onChange={(event) => setProductSearch(event.target.value)} placeholder="Search products by name to add..." aria-label="Search products" />
            {productSearch && <div className="suggestion-list product-suggestions">
              {productBusy && !productResults.length && <div className="suggestion-empty">Searching...</div>}
              {productResults.map((product) => {
                const box = masterBoxSize(product)
                return <button type="button" key={product.id} onClick={() => addProduct(product)}>
                  <strong>{product.name}</strong>
                  <span>{box ? `M.Box ${box} · ` : ''}{product.current_stock} in stock</span>
                </button>
              })}
              {!productBusy && !productResults.length && <div className="suggestion-empty">No matching product</div>}
            </div>}
          </div>

          {!lines.length ? <div className="lines-empty">Start typing above to add the first product.</div> : <div className="invoice-lines">
            {lines.map((line) => {
              const calculated = calculateLine(line, taxMode)
              const box = masterBoxSize(line.productData)
              return <div className="invoice-line" key={line.key}>
                <div className="line-product">
                  <strong>{line.productData.name}</strong>
                  <span>
                    {line.purchaseUnit === 'master box' && box
                      ? `${line.quantity || 0} × ${box} = ${calculated.baseQty} pieces`
                      : `${calculated.baseQty} pieces`}
                    {' · '}cost {money(calculated.unitCost)}/pc
                  </span>
                </div>
                <label>Unit<select value={line.purchaseUnit} onChange={(e) => updateLine(line.key, 'purchaseUnit', e.target.value)}>
                  <option value="piece">Pieces</option>
                  {box && <option value="master box">Master box ({box})</option>}
                </select></label>
                <label>Qty<input type="number" min="0.001" step={line.purchaseUnit === 'piece' ? '1' : '0.001'} value={line.quantity} onChange={(e) => updateLine(line.key, 'quantity', e.target.value)} /></label>
                <label>Rate<input type="number" min="0" step="0.01" value={line.rate} onChange={(e) => updateLine(line.key, 'rate', e.target.value)} placeholder={line.purchaseUnit === 'master box' ? 'Per box' : 'Per piece'} /></label>
                <label>Disc<input type="number" min="0" step="0.01" value={line.discountAmount} onChange={(e) => updateLine(line.key, 'discountAmount', e.target.value)} /></label>
                <div className="line-tax">{calculated.taxRate}%</div>
                <div className="line-total">{money(calculated.total)}</div>
                <button type="button" className="remove-line" onClick={() => removeLine(line.key)} aria-label="Remove line">×</button>
              </div>
            })}
          </div>}
        </section>
      </div>

      <aside className="invoice-summary">
        <div className="summary-label">Preview summary</div>
        <div className="summary-customer">{supplier?.name || 'No supplier selected'}<span>{taxMode === 'inclusive' ? 'Tax-inclusive bill' : 'Tax-exclusive bill'}</span></div>
        <div className="summary-rows">
          <div><span>Subtotal</span><strong>{money(totals.subtotal)}</strong></div>
          <div><span>Discount</span><strong>{money(totals.discount)}</strong></div>
          <div><span>Taxable</span><strong>{money(totals.taxable)}</strong></div>
          <div className="summary-tax"><span>GST</span><strong>{money(totals.tax)}</strong></div>
        </div>
        <div className="grand-total"><span>Bill total (est.)</span><strong>{money(totals.total)}</strong></div>
        <button type="button" className="quiet-button submit-invoice" onClick={() => submit(false)} disabled={saving || posting}>{saving ? 'Saving draft...' : 'Save draft'}</button>
        <button type="button" className="primary-button submit-invoice" onClick={() => submit(true)} disabled={saving || posting}>{posting ? 'Receiving stock...' : 'Post & receive stock'}</button>
        <p className="summary-note">Posting receives stock, updates the weighted-average cost, and writes the stock ledger. Drafts affect nothing until posted.</p>
      </aside>
    </div>
  </section>
}
