import stockbillIcon from '../assets/stockbill-icon.svg'

// StockBill product lockup (branding/BRAND.md): icon tile + live-text
// wordmark in Space Grotesk 600. "Stock" + "Bill" with no space; colours
// depend on the background (tone="light" | "dark").
export default function StockBillLogo({ tone = 'light', iconSize = 28, textSize = 18 }) {
  return (
    <span className={`sb-lockup sb-lockup-${tone}`}>
      <img className="sb-icon" src={stockbillIcon} width={iconSize} height={iconSize} alt="" aria-hidden="true" />
      <span className="sb-wordmark" style={{ fontSize: textSize }}>
        <span className="sb-stock">Stock</span><span className="sb-bill">Bill</span>
      </span>
    </span>
  )
}
