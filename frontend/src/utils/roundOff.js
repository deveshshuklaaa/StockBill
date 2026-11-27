// Whole-bill round-off preview, matching the server (billing.services
// _apply_round_off): round the invoice total to the nearest rupee, 50 paise
// up (ROUND_HALF_UP). Lines, taxable value and GST are never rounded.
// Works in whole paise so float noise (107.4999...) cannot flip the result.
// The server's posted value is authoritative; this is only a preview.
export function roundOffInvoiceTotal(exactTotal, enabled) {
  const paise = Math.round(Number(exactTotal || 0) * 100)
  if (!enabled) return { roundOff: 0, total: paise / 100 }
  const roundedPaise = paise >= 0
    ? Math.floor((paise + 50) / 100) * 100
    : -Math.floor((-paise + 50) / 100) * 100
  return { roundOff: (roundedPaise - paise) / 100, total: roundedPaise / 100 }
}

// "+0.90" / "−0.10" (true minus sign) / "0.00".
export function formatRoundOff(value) {
  const amount = Number(value || 0)
  const text = Math.abs(amount).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  if (amount > 0) return `+${text}`
  if (amount < 0) return `−${text}`
  return text
}
