import { useEffect, useState } from 'react'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'
import { useAuth } from '../context/AuthContext'

const emptyCustomer = {
  name: '', contact_info: '', customer_type: 'B2C',
  gst_registration_type: 'unregistered', gstin: '',
  billing_address: '', shipping_address: '',
  state: '', state_code: '', pincode: '',
  credit_limit: '0', credit_days: '0', is_regular: false,
}

function rows(data) { return Array.isArray(data) ? data : data?.results || [] }
function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

export default function CustomersPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [customers, setCustomers] = useState([])
  const [form, setForm] = useState(emptyCustomer)
  const [sameAsBilling, setSameAsBilling] = useState(true)
  const [editing, setEditing] = useState(null)
  const [showForm, setShowForm] = useState(false)
  const [busy, setBusy] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  async function loadCustomers() {
    setBusy(true); setError('')
    try { setCustomers(rows((await api.get('/customers/')).data)) }
    catch (err) { setError(apiErrorMessage(err)) }
    finally { setBusy(false) }
  }
  useEffect(() => { loadCustomers() }, [])

  function beginCreate() { setEditing(null); setForm(emptyCustomer); setSameAsBilling(true); setShowForm(true) }
  function beginEdit(customer) {
    setEditing(customer.id)
    setForm({
      name: customer.name || '', contact_info: customer.contact_info || '',
      customer_type: customer.customer_type || 'B2C',
      gst_registration_type: customer.gst_registration_type || 'unregistered',
      gstin: customer.gstin || '',
      billing_address: customer.billing_address || '', shipping_address: customer.shipping_address || '',
      state: customer.state || '', state_code: customer.state_code || '', pincode: customer.pincode || '',
      credit_limit: customer.credit_limit ?? '0', credit_days: customer.credit_days ?? '0',
      is_regular: Boolean(customer.is_regular),
    })
    setSameAsBilling(customer.shipping_address === customer.billing_address)
    setShowForm(true)
  }

  function change(event) {
    const { name, value, type, checked } = event.target
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
  }

  function changeBillingAddress(event) {
    const value = event.target.value
    setForm((current) => ({
      ...current,
      billing_address: value,
      shipping_address: sameAsBilling ? value : current.shipping_address,
    }))
  }

  async function save(event) {
    event.preventDefault(); setSaving(true); setError('')
    const payload = {
      ...form,
      credit_limit: Number(form.credit_limit || 0),
      credit_days: Number(form.credit_days || 0),
      shipping_address: sameAsBilling ? form.billing_address : form.shipping_address,
    }
    try {
      if (editing) await api.patch(`/customers/${editing}/`, payload)
      else await api.post('/customers/', payload)
      setShowForm(false); await loadCustomers()
    } catch (err) { setError(apiErrorMessage(err)) }
    finally { setSaving(false) }
  }

  async function archive(customer) {
    if (!window.confirm(`Archive ${customer.name}? Their history is preserved.`)) return
    try { await api.delete(`/customers/${customer.id}/`); await loadCustomers() }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  async function reactivate(customer) {
    try { await api.patch(`/customers/${customer.id}/`, { is_active: true }); await loadCustomers() }
    catch (err) { setError(apiErrorMessage(err)) }
  }

  return <section className="page-section">
    <header className="page-header">
      <div><p className="eyebrow">Relationships / ledger</p><h1>Customers</h1><p className="page-subtitle">Accounts, tax identity, addresses, and credit terms.</p></div>
      {isAdmin && <button className="primary-button" onClick={beginCreate}>Add customer</button>}
    </header>
    <StatusMessage>{error}</StatusMessage>

    {showForm && isAdmin && <form className="record-form" onSubmit={save}>
      <div className="form-heading"><div><p className="eyebrow">{editing ? 'Edit record' : 'New record'}</p><h2>{editing ? 'Update customer' : 'Add customer'}</h2></div><button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Close</button></div>

      <p className="eyebrow">Basic</p>
      <div className="form-grid">
        <label>Customer name<input name="name" value={form.name} onChange={change} required aria-required="true" /></label>
        <label>Phone<input name="contact_info" value={form.contact_info} onChange={change} /></label>
        <label>Customer type<select name="customer_type" value={form.customer_type} onChange={change}><option value="B2C">B2C</option><option value="B2B">B2B</option></select></label>
        <label className="checkbox-label"><input type="checkbox" name="is_regular" checked={form.is_regular} onChange={change} /> Regular customer account</label>
      </div>

      <p className="eyebrow">GST</p>
      <div className="form-grid">
        <label>GST registration<select name="gst_registration_type" value={form.gst_registration_type} onChange={change}><option value="unregistered">Unregistered</option><option value="registered">Registered</option></select></label>
        <label>GSTIN<input name="gstin" value={form.gstin} onChange={change} placeholder="15-character GSTIN" /></label>
        <label>State<input name="state" value={form.state} onChange={change} /></label>
        <label>State code<input name="state_code" value={form.state_code} onChange={change} placeholder="e.g. 29" /></label>
      </div>

      <p className="eyebrow">Billing address</p>
      <div className="form-grid">
        <label className="full-width">Address<textarea name="billing_address" value={form.billing_address} onChange={changeBillingAddress} rows={2} /></label>
        <label>Pincode<input name="pincode" value={form.pincode} onChange={change} /></label>
      </div>

      <p className="eyebrow">Shipping address</p>
      <div className="form-grid">
        <label className="checkbox-label full-width"><input type="checkbox" checked={sameAsBilling} onChange={(e) => {
          const nowSame = e.target.checked
          setSameAsBilling(nowSame)
          if (nowSame) setForm((current) => ({ ...current, shipping_address: current.billing_address }))
        }} /> Shipping address same as billing</label>
        {!sameAsBilling && <label className="full-width">Shipping address<textarea name="shipping_address" value={form.shipping_address} onChange={change} rows={2} /></label>}
      </div>

      <p className="eyebrow">Credit</p>
      <div className="form-grid">
        <label>Credit limit<input name="credit_limit" type="number" min="0" step="0.01" value={form.credit_limit} onChange={change} /></label>
        <label>Credit days<input name="credit_days" type="number" min="0" step="1" value={form.credit_days} onChange={change} /></label>
      </div>

      <div className="form-actions">
        <button type="button" className="quiet-button" onClick={() => setShowForm(false)}>Cancel</button>
        <button className="primary-button" disabled={saving}>{saving ? 'Saving...' : (editing ? 'Update customer' : 'Save customer')}</button>
      </div>
    </form>}

    <div className="table-frame">
      <div className="table-meta"><span>{customers.length} customers</span><span className="table-note">GST identity and credit terms per account</span></div>
      {busy ? <div className="empty-state">Loading customers...</div> : customers.length === 0 ? <div className="empty-state">No customers yet.</div> : <div className="table-scroll"><table>
        <thead><tr><th>Customer</th><th>Phone</th><th>GSTIN</th><th>State</th><th>Regular</th><th>Status</th>{isAdmin && <th aria-label="Actions" />}</tr></thead>
        <tbody>{customers.map((customer) => <tr key={customer.id} className={customer.is_active ? '' : 'archived-row'}>
          <td><strong>{customer.name}</strong><small>{customer.customer_type}{customer.credit_limit > 0 ? ` · limit ${money(customer.credit_limit)}` : ''}</small></td>
          <td>{customer.contact_info || '-'}</td>
          <td>{customer.gstin || '-'}</td>
          <td>{customer.state || '-'}</td>
          <td>{customer.is_regular ? 'Yes' : 'No'}</td>
          <td>{customer.is_active ? 'Active' : 'Archived'}</td>
          {isAdmin && <td><div className="row-actions">
            <button className="text-button" onClick={() => beginEdit(customer)}>Edit</button>
            {customer.is_active
              ? <button className="text-button danger" onClick={() => archive(customer)}>Archive</button>
              : <button className="text-button" onClick={() => reactivate(customer)}>Reactivate</button>}
          </div></td>}
        </tr>)}</tbody>
      </table></div>}
    </div>
  </section>
}
