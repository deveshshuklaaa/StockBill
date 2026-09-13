import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiErrorMessage, apiForbiddenMessage } from '../api/client'
import {
  archiveSupplier,
  fetchSupplier,
  fetchSupplierPurchases,
  reactivateSupplier,
  updateSupplier,
} from '../api/suppliers'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

function money(value) { return `₹${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

const STATE_BADGE = {
  DRAFT: 'type-chip',
  POSTED: 'tax-chip',
  CANCELLED: 'state-cancelled',
}

export default function SupplierDetailPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const [supplier, setSupplier] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const [purchases, setPurchases] = useState([])
  const [purchasePage, setPurchasePage] = useState(1)
  const [purchaseTotal, setPurchaseTotal] = useState(0)
  const [purchaseHasNext, setPurchaseHasNext] = useState(false)
  const [purchaseHasPrevious, setPurchaseHasPrevious] = useState(false)
  const [purchasesBusy, setPurchasesBusy] = useState(true)
  const latestHistoryLoad = useRef(0)

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState({
    name: '', contact_info: '', gstin: '', address: '', state: '', state_code: '',
  })

  useEffect(() => {
    let cancelled = false
    setSupplier(null); setError(''); setShowForm(false); setPurchasePage(1)
    fetchSupplier(id)
      .then((data) => { if (!cancelled) setSupplier(data) })
      .catch((err) => { if (!cancelled) setError(apiErrorMessage(err)) })
    return () => { cancelled = true }
  }, [id])

  // Purchase history is fetched server-scoped: ?supplier=<id> on the
  // existing purchase list endpoint, never filtered client-side.
  useEffect(() => {
    const requestId = ++latestHistoryLoad.current
    setPurchasesBusy(true)
    fetchSupplierPurchases({ supplier: id, page: purchasePage })
      .then((data) => {
        if (requestId !== latestHistoryLoad.current) return
        setPurchases(data.results || [])
        setPurchaseTotal(Number(data.count ?? 0))
        setPurchaseHasNext(Boolean(data.next))
        setPurchaseHasPrevious(Boolean(data.previous))
      })
      .catch((err) => {
        if (requestId !== latestHistoryLoad.current) return
        if (err?.response?.status === 404 && purchasePage > 1) { setPurchasePage(1); return }
        // Purchase history is admin-only; staff still see supplier info.
        if (err?.response?.status === 403) return
        setError(apiErrorMessage(err))
      })
      .finally(() => { if (requestId === latestHistoryLoad.current) setPurchasesBusy(false) })
  }, [id, purchasePage])

  function beginEdit() {
    setForm({
      name: supplier.name || '',
      contact_info: supplier.contact_info || '',
      gstin: supplier.gstin || '',
      address: supplier.address || '',
      state: supplier.state || '',
      state_code: supplier.state_code || '',
    })
    setShowForm(true)
  }

  function change(event) {
    const { name, value } = event.target
    setForm((current) => ({ ...current, [name]: value }))
  }

  async function save(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const updated = await updateSupplier(id, form)
      setSupplier(updated); setShowForm(false)
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setBusy(false) }
  }

  async function archive() {
    if (!window.confirm(`Archive ${supplier.name}? Their purchase history is preserved and stays visible.`)) return
    setBusy(true); setError('')
    try {
      await archiveSupplier(id)
      const refreshed = await fetchSupplier(id)
      setSupplier(refreshed)
    } catch (err) { setError(apiForbiddenMessage(err, 'archive suppliers', 'archiving supplier')) }
    finally { setBusy(false) }
  }

  async function reactivate() {
    setBusy(true); setError('')
    try {
      const refreshed = await reactivateSupplier(id)
      setSupplier(refreshed)
    } catch (err) { setError(apiForbiddenMessage(err, 'reactivate suppliers', 'reactivating supplier')) }
    finally { setBusy(false) }
  }

  if (error && !supplier) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/suppliers">Back to suppliers</Link></section>
  if (!supplier) return <section className="page-section"><div className="empty-state">Loading supplier...</div></section>

  const purchaseTotalPages = Math.max(1, Math.ceil(purchaseTotal / 25))

  return <section className="page-section invoice-detail-page">
    <header className="detail-toolbar">
      <Link className="quiet-button" to="/suppliers">← Suppliers</Link>
      {isAdmin && <div className="detail-actions">
        {!supplier.is_active
          ? <button className="primary-button" onClick={reactivate} disabled={busy}>{busy ? 'Reactivating...' : 'Reactivate supplier'}</button>
          : <button className="quiet-button" style={{ color: 'var(--red)' }} onClick={archive} disabled={busy}>Archive supplier</button>}
      </div>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">Edit record</p><h2>Update {supplier.name}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>
      <div className="form-grid">
        <label>Supplier name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
        <label>Phone / contact<input name="contact_info" value={form.contact_info} onChange={change} /></label>
        <label>GSTIN<input name="gstin" value={form.gstin} onChange={change} placeholder="15-character GSTIN (optional)" /></label>
        <label>State<input name="state" value={form.state} onChange={change} /></label>
        <label>State code<input name="state_code" value={form.state_code} onChange={change} placeholder="e.g. 27" /></label>
        <label className="full-width">Address<textarea name="address" value={form.address} onChange={change} rows={2} /></label>
      </div>
      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button>
        <button className="primary-button" disabled={busy}>{busy ? 'Saving...' : 'Update supplier'}</button>
      </div>
    </form>}

    <div className="print-sheet">
      <div className="invoice-detail-head">
        <div>
          <p className="eyebrow">Divya Enterprises / Supplier</p>
          <h1>{supplier.name}</h1>
          <p>Master record{supplier.created_at ? ` · added ${String(supplier.created_at).slice(0, 10)}` : ''}</p>
        </div>
        <div className="detail-status">
          <span className={supplier.is_active ? 'tax-chip' : 'state-cancelled'}>{supplier.is_active ? 'Active' : 'Archived'}</span>
          {isAdmin && <button className="text-button" style={{ marginTop: 8 }} onClick={beginEdit}>Edit supplier</button>}
        </div>
      </div>

      <div className="detail-parties">
        <div>
          <span>Contact</span>
          <strong>{supplier.contact_info || '—'}</strong>
        </div>
        <div>
          <span>GSTIN</span>
          <strong>{supplier.gstin || 'Unregistered'}</strong>
        </div>
        <div>
          <span>State</span>
          <strong>{supplier.state || '—'}{supplier.state_code ? ` (${supplier.state_code})` : ''}</strong>
        </div>
        <div>
          <span>Registered address</span>
          <strong className="address-cell">{supplier.address || '—'}</strong>
        </div>
      </div>

      <p className="eyebrow" style={{ margin: '26px 0 12px' }}>Purchase history</p>
      {!isAdmin ? <div className="empty-state">Purchase history is available to administrators.</div>
        : purchasesBusy ? <div className="empty-state">Loading purchases...</div>
          : purchases.length === 0 ? <div className="empty-state">No purchases from this supplier yet.</div>
            : <div className="table-scroll"><table>
              <thead><tr><th>Purchase</th><th>Bill no</th><th>Date</th><th>Warehouse</th><th>Total</th><th>Status</th><th aria-label="Actions" /></tr></thead>
              <tbody>{purchases.map((purchase) => <tr key={purchase.id} className={purchase.state === 'CANCELLED' ? 'archived-row' : ''}>
                <td><strong>{purchase.purchase_number || `Draft #${purchase.id}`}</strong></td>
                <td><code>{purchase.supplier_invoice_no || '-'}</code></td>
                <td>{purchase.invoice_date}</td>
                <td>{purchase.warehouse_name}</td>
                <td><strong>{money(purchase.total_amount)}</strong></td>
                <td><span className={STATE_BADGE[purchase.state] || 'type-chip'}>{purchase.state}</span></td>
                <td><Link className="text-button" to={`/purchases/${purchase.id}`}>View Purchase</Link></td>
              </tr>)}</tbody>
            </table></div>}
      {isAdmin && purchases.length > 0 && <div className="table-meta pager" role="navigation" aria-label="Supplier purchase pagination">
        <button className="pager-button" onClick={() => setPurchasePage((c) => Math.max(1, c - 1))} disabled={!purchaseHasPrevious || purchasesBusy}>← Previous</button>
        <span>Page {purchasePage} of {purchaseTotalPages}{purchaseTotal > 0 ? ` · ${purchaseTotal} purchases` : ''}</span>
        <button className="pager-button" onClick={() => setPurchasePage((c) => c + 1)} disabled={!purchaseHasNext || purchasesBusy}>Next →</button>
      </div>}

      <div className="detail-total">
        <span>Purchase history is immutable — supplier master edits never change posted documents.</span>
      </div>
    </div>
  </section>
}
