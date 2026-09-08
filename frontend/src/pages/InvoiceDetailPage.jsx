import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api, { apiErrorMessage } from '../api/client'
import StatusMessage from '../components/StatusMessage'

function money(value) { return `Rs ${Number(value || 0).toLocaleString('en-IN', { minimumFractionDigits: 2 })}` }

export default function InvoiceDetailPage() {
  const { id } = useParams()
  const [invoice, setInvoice] = useState(null)
  const [error, setError] = useState('')
  const [downloading, setDownloading] = useState(false)

  useEffect(() => {
    api.get(`/invoices/${id}/`)
      .then(({ data }) => setInvoice(data))
      .catch((err) => setError(apiErrorMessage(err)))
  }, [id])

  async function downloadPdf() {
    setDownloading(true)
    setError('')
    try {
      const response = await api.get(`/invoices/${id}/pdf/`, { responseType: 'blob' })
      const url = URL.createObjectURL(response.data)
      const link = document.createElement('a')
      link.href = url
      link.download = `invoice-${invoice.invoice_number}.pdf`
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(apiErrorMessage(err))
    } finally {
      setDownloading(false)
    }
  }

  if (error) return <section className="page-section"><StatusMessage>{error}</StatusMessage><Link className="quiet-button" to="/invoices/new">Back to new invoice</Link></section>
  if (!invoice) return <section className="page-section"><div className="empty-state">Loading invoice...</div></section>

  return <section className="page-section invoice-detail-page"><header className="detail-toolbar"><Link className="quiet-button" to="/invoices/new">← New invoice</Link><div className="detail-actions"><button className="quiet-button" onClick={() => window.print()}>Print</button><button className="primary-button" onClick={downloadPdf} disabled={downloading}>{downloading ? 'Preparing PDF...' : 'Download PDF'}</button></div></header><div className="print-sheet"><div className="invoice-detail-head"><div><p className="eyebrow">Divya Enterprises / Invoice</p><h1>{invoice.invoice_number}</h1><p>{invoice.invoice_date}</p></div><div className="detail-status"><span>{invoice.payment_status}</span><strong>{invoice.payment_type} sale ({invoice.tax_mode})</strong><br /><span>Supply: {invoice.place_of_supply}</span></div></div><div className="detail-parties"><div><span>Bill to</span><strong>{invoice.customer_name || 'Walk-in customer'}</strong><span>{invoice.customer_gstin_snapshot}</span></div><div><span>Notes</span><strong>{invoice.notes || '—'}</strong></div></div><table className="detail-table"><thead><tr><th>Item</th><th>Qty</th><th>Rate</th><th>Discount</th><th>Taxable</th><th>GST</th><th>Total</th></tr></thead><tbody>{(invoice.line_items || []).map((line) => <tr key={line.id}><td>{line.product_name}<br /><small>HSN: {line.hsn_sac_snapshot || '-'}</small></td><td>{line.quantity}</td><td>{money(line.rate_charged)}</td><td>{money(line.discount_amount)}</td><td>{money(line.taxable_value_snapshot)}</td><td>{line.tax_rate}%<br /><small>C:{money(line.cgst_amount)} S:{money(line.sgst_amount)} I:{money(line.igst_amount)}</small></td><td>{money(line.line_total)}</td></tr>)}</tbody></table><div className="detail-total"><span>Total</span><strong>{money(invoice.total_amount)}</strong></div></div></section>
}
