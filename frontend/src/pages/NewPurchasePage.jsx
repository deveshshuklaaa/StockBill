import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import api, { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import { fetchNextPurchaseNumber, fetchWarehouses, searchPurchaseProducts } from '../api/purchases'
import { fetchActiveSuppliers, fetchSupplierPricing } from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { formatNetWeight, formatStockWithBoxes, masterBoxSize } from '../utils/format'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

function today() { return new Date().toISOString().slice(0, 10) }

// Variant identity line: weight + MRP distinguish same-name products.
function variantSummary(product) {
  const parts = []
  const weight = formatNetWeight(product?.attributes?.net_weight)
  if (weight) parts.push(weight)
  if (product.mrp != null) parts.push(`MRP: ₹${Number(product.mrp).toFixed(2)}`)
  if (product.sku) parts.push(`SKU: ${product.sku}`)
  if (product.category_name) parts.push(product.category_name)
  if (product.base_unit && product.base_unit !== 'piece') parts.push(product.base_unit)
  return parts.join(' · ')
}

function calculateLine(line, taxMode) {
  const quantity = Number(line.quantity) || 0
  const factor = Number(line.conversionFactor ?? line.conversion_factor) || 1
  const baseQty = quantity * factor
  const rate = Number(line.rate) || 0
  const discount = Number(line.discountAmount ?? line.discount_amount) || 0
  const taxRate = Number(line.taxRate ?? line.tax_rate) || 0

  const gross = baseQty * rate
  const net = Math.max(0, gross - discount)
  let taxable = net
  let tax = net * taxRate / 100
  if (taxMode === 'inclusive') {
    taxable = net / (1 + taxRate / 100)
    tax = net - taxable
  }
  const unitCost = baseQty > 0 ? taxable / baseQty : 0
  return { gross, discount, taxable, tax, total: taxable + tax, baseQty, unitCost, taxRate }
}

export default function NewPurchasePage() {
  const navigate = useNavigate()
  const [warehouses, setWarehouses] = useState([])
  const [supplier, setSupplier] = useState(null)
  const [supplierSearch, setSupplierSearch] = useState('')
  const [supplierResults, setSupplierResults] = useState([])
  const [supplierBusy, setSupplierBusy] = useState(false)
  const [supplierPricingMap, setSupplierPricingMap] = useState({})
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
    fetchWarehouses({ is_active: 'true' })
      .then((warehouseRows) => {
        setWarehouses(warehouseRows)
        if (warehouseRows.length === 1) setWarehouseId(String(warehouseRows[0].id))
      })
      .catch((err) => setError(apiErrorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  // Server-side supplier search, debounced; only active suppliers are
  // offered because the backend rejects inactive ones for new purchases.
  useEffect(() => {
    const query = supplierSearch.trim()
    if (!query || supplier?.id) { setSupplierResults([]); setSupplierBusy(false); return undefined }
    let cancelled = false
    setSupplierBusy(true)
    const timer = setTimeout(() => {
      fetchActiveSuppliers(query)
        .then((results) => { if (!cancelled) setSupplierResults(results.slice(0, 8)) })
        .catch(() => { if (!cancelled) setSupplierResults([]) })
        .finally(() => { if (!cancelled) setSupplierBusy(false) })
    }, 300)
    return () => { cancelled = true; clearTimeout(timer); setSupplierBusy(false) }
  }, [supplierSearch, supplier])

  // Fetch supplier-wise purchase rates whenever supplier changes.
  // Auto-fills configured rates for products that have not been manually overridden.
  useEffect(() => {
    if (!supplier?.id) {
      setSupplierPricingMap({})
      return undefined
    }
    let cancelled = false
    fetchSupplierPricing(supplier.id, { isActive: 'true' })
      .then((data) => {
        if (cancelled) return
        const map = {}
        ;(data?.pricing || []).forEach((p) => {
          if (p.is_active && p.mrp != null) {
            map[Number(p.mrp).toFixed(2)] = Number(p.rate_per_piece)
          }
        })
        setSupplierPricingMap(map)
        // Refresh rates for lines that haven't been manually overridden
        setLines((currentLines) =>
          currentLines.map((line) => {
            if (line.isManualRate) return line
            const lineMrp = line.productData?.mrp != null ? Number(line.productData.mrp).toFixed(2) : null
            if (lineMrp && map[lineMrp] !== undefined) {
              return {
                ...line,
                rate: map[lineMrp],
                hasSupplierPrice: true,
              }
            }
            return {
              ...line,
              rate: '',
              hasSupplierPrice: false,
            }
          })
        )
      })
      .catch(() => {
        if (!cancelled) setSupplierPricingMap({})
      })
    return () => {
      cancelled = true
    }
  }, [supplier])

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
    const existing = lines.find((line) => line.product === product.id)
    if (existing) {
      updateLine(existing.key, 'quantity', Number(existing.quantity || 0) + 1)
    } else {
      const productMrp = product.mrp != null ? Number(product.mrp).toFixed(2) : null
      const supplierRate =
        supplier?.id && productMrp && supplierPricingMap[productMrp] !== undefined
          ? supplierPricingMap[productMrp]
          : null
      const hasSupplierPrice = supplierRate !== null

      setLines((current) => [...current, {
        key: product.id,
        product: product.id,
        productData: product,
        quantity: 1,
        purchaseUnit: 'piece',
        conversionFactor: 1,
        rate: hasSupplierPrice ? supplierRate : '',
        hasSupplierPrice,
        isManualRate: false,
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
      if (field === 'rate') {
        next.isManualRate = true
      }
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
      setError(
        apiForbiddenMessage(
          err,
          post ? 'post purchases' : 'save purchase drafts',
          post ? 'posting purchase' : 'saving purchase draft',
        ),
      )
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
            <input value={supplier?.id ? supplier.name : supplierSearch} onChange={(event) => { setSupplierSearch(event.target.value); if (supplier?.id) setSupplier(null) }} placeholder="Search active suppliers by name, GSTIN, or phone..." aria-label="Search supplier" />
            {supplierSearch && !supplier?.id && <div className="suggestion-list">
              {supplierBusy && !supplierResults.length && <div className="suggestion-empty">Searching...</div>}
              {supplierResults.map((item) => <button type="button" key={item.id} onClick={() => chooseSupplier(item)}>
                <strong>{item.name}</strong>
                <span>{item.gstin || 'Unregistered'}{item.state ? ` · ${item.state}` : ''}{item.contact_info ? ` · ${item.contact_info}` : ''}</span>
              </button>)}
              {!supplierBusy && !supplierResults.length && <div className="suggestion-empty">No active supplier matches. Archived suppliers cannot receive purchases.</div>}
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
            <label className="purchase-inline-field"><span>Tax Mode</span><select value={taxMode} onChange={(e) => setTaxMode(e.target.value)}><option value="exclusive">Exclusive</option><option value="inclusive">Inclusive</option></select></label>
          </div>
          <label className="purchase-inline-field" style={{ marginTop: 14 }}><span>Notes</span><textarea className="form-input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional reference notes" /></label>
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
                const summary = variantSummary(product)
                return <button type="button" key={product.id} onClick={() => addProduct(product)}>
                  <strong>{product.name}</strong>
                  {summary && <span className="variant-line">{summary}</span>}
                  <span>{box ? `M.Box ${box} · ` : ''}{formatStockWithBoxes(product.current_stock, product)}</span>
                </button>
              })}
              {!productBusy && !productResults.length && <div className="suggestion-empty">No matching product</div>}
            </div>}
          </div>

          {!lines.length ? <div className="lines-empty">Start typing above to add the first product.</div> : <div className="invoice-lines">
            {lines.map((line) => {
              const calculated = calculateLine(line, taxMode)
              const box = masterBoxSize(line.productData)
              const isMasterBox = line.purchaseUnit === 'master box'
              return <div className="invoice-line new-purchase-line" key={line.key}>
                <div className="line-product">
                  <span className="line-field-title">Product</span>
                  <strong className="line-product-name">{line.productData.name}</strong>
                  <span className="variant-line">{variantSummary(line.productData) || line.productData.base_unit}</span>
                  <span className="line-conversion-badge">
                    {isMasterBox && box
                      ? `Conversion: ${line.quantity || 0} × ${box} = ${calculated.baseQty} Pieces`
                      : `${calculated.baseQty} ${line.productData.base_unit || 'Pieces'}`}
                    {' · '}Effective cost: {money(calculated.unitCost)} / pc
                  </span>
                </div>
                <label className="line-field line-field-unit">
                  <span className="line-field-title">Unit</span>
                  <select value={line.purchaseUnit} onChange={(e) => updateLine(line.key, 'purchaseUnit', e.target.value)} aria-label={`Unit for ${line.productData.name}`}>
                    <option value="piece">Pieces</option>
                    {box && <option value="master box">Master Box ({box} pcs)</option>}
                  </select>
                </label>
                <label className="line-field line-field-qty">
                  <span className="line-field-title">Qty</span>
                  <input
                    type="number"
                    min="0.001"
                    step={isMasterBox ? '1' : '0.001'}
                    value={line.quantity}
                    onChange={(e) => updateLine(line.key, 'quantity', e.target.value)}
                    placeholder={isMasterBox ? 'Boxes' : 'Pieces'}
                    aria-label={`Quantity in ${isMasterBox ? 'master boxes' : 'pieces'} for ${line.productData.name}`}
                  />
                </label>
                <label className="line-field line-field-mrp">
                  <span className="line-field-title">MRP</span>
                  <input
                    type="text"
                    readOnly
                    tabIndex={-1}
                    value={line.productData?.mrp != null ? `₹${Number(line.productData.mrp).toFixed(2)}` : '—'}
                    className="line-mrp-input"
                    aria-label={`MRP for ${line.productData.name}`}
                  />
                </label>
                <label className="line-field line-field-rate">
                  <span className="line-field-title">Purchase Rate</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={line.rate}
                    onChange={(e) => updateLine(line.key, 'rate', e.target.value)}
                    placeholder="₹ / pc"
                    className="line-rate-input"
                    aria-label={`Purchase rate per piece for ${line.productData.name}`}
                  />
                  {line.hasSupplierPrice && !line.isManualRate && (
                    <span
                      className="line-rate-hint rate-supplier supplier-rate-badge"
                      title={`Supplier rate${line.productData?.mrp != null ? ` (MRP ₹${Number(line.productData.mrp).toFixed(2)})` : ''}: ₹${Number(line.rate).toFixed(2)}/pc`}
                    >
                      Supplier rate{line.productData?.mrp != null ? ` (MRP ₹${Number(line.productData.mrp).toFixed(2)})` : ''}: ₹{Number(line.rate).toFixed(2)}/pc
                    </span>
                  )}
                  {line.isManualRate && line.hasSupplierPrice && (
                    <span className="line-rate-hint rate-manual manual-override-badge">
                      Manually overridden
                    </span>
                  )}
                </label>
                <label className="line-field line-field-disc">
                  <span className="line-field-title">Disc.</span>
                  <div className="disc-input-wrap">
                    <input
                      type="number"
                      min="0"
                      step="0.01"
                      value={line.discountAmount}
                      onChange={(e) => updateLine(line.key, 'discountAmount', e.target.value)}
                      placeholder="0.00"
                      className="line-disc-input"
                      aria-label={`Discount amount for ${line.productData.name}`}
                    />
                    <span className="disc-symbol">%</span>
                  </div>
                </label>
                <div className="line-field line-field-tax">
                  <span className="line-field-title">GST</span>
                  <div className="line-val-display">{calculated.taxRate}%</div>
                </div>
                <div className="line-field line-field-taxable">
                  <span className="line-field-title">Taxable</span>
                  <div className="line-val-display line-val-taxable">
                    <span className="sr-only">{`Taxable: ${money(calculated.taxable)}`}</span>
                    <span aria-hidden="true">{money(calculated.taxable)}</span>
                  </div>
                </div>
                <div className="line-field line-field-total">
                  <span className="line-field-title">Total</span>
                  <div className="line-val-display line-val-total">
                    <strong>{money(calculated.total)}</strong>
                  </div>
                </div>
                <div className="line-field line-field-remove">
                  <span className="line-field-title">&nbsp;</span>
                  <button type="button" className="remove-line" onClick={() => removeLine(line.key)} aria-label="Remove line" title="Remove line">×</button>
                </div>
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
