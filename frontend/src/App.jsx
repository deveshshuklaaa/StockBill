import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import EnvironmentBanner from './components/EnvironmentBanner'
import ProtectedRoute from './components/ProtectedRoute'
import { AuthProvider } from './context/AuthContext'
import './App.css'

// Lazy loaded page components
const LoginPage = lazy(() => import('./pages/LoginPage'))
const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const ProductsPage = lazy(() => import('./pages/ProductsPage'))
const EditProductPage = lazy(() => import('./pages/EditProductPage'))
const CataloguePage = lazy(() => import('./pages/CataloguePage'))
const CustomersPage = lazy(() => import('./pages/CustomersPage'))
const CustomerDetailPage = lazy(() => import('./pages/CustomerDetailPage'))
const InventoryPage = lazy(() => import('./pages/InventoryPage'))
const ProductStockDetailPage = lazy(() => import('./pages/ProductStockDetailPage'))
const StockAdjustmentsPage = lazy(() => import('./pages/StockAdjustmentsPage'))
const NewStockAdjustmentPage = lazy(() => import('./pages/NewStockAdjustmentPage'))
const StockAdjustmentDetailPage = lazy(() => import('./pages/StockAdjustmentDetailPage'))
const OpeningStockListPage = lazy(() => import('./pages/OpeningStockListPage'))
const NewOpeningStockPage = lazy(() => import('./pages/NewOpeningStockPage'))
const OpeningStockDetailPage = lazy(() => import('./pages/OpeningStockDetailPage'))
const WarehouseTransfersPage = lazy(() => import('./pages/WarehouseTransfersPage'))
const NewWarehouseTransferPage = lazy(() => import('./pages/NewWarehouseTransferPage'))
const WarehouseTransferDetailPage = lazy(() => import('./pages/WarehouseTransferDetailPage'))
const StockLedgerPage = lazy(() => import('./pages/StockLedgerPage'))
const PurchasesPage = lazy(() => import('./pages/PurchasesPage'))
const NewPurchasePage = lazy(() => import('./pages/NewPurchasePage'))
const PurchaseDetailPage = lazy(() => import('./pages/PurchaseDetailPage'))
const SuppliersPage = lazy(() => import('./pages/SuppliersPage'))
const SupplierDetailPage = lazy(() => import('./pages/SupplierDetailPage'))
const SupplierLedgerPage = lazy(() => import('./pages/SupplierLedgerPage'))
const WarehousesPage = lazy(() => import('./pages/WarehousesPage'))
const BusinessProfilePage = lazy(() => import('./pages/BusinessProfilePage'))
const TaxConfigurationPage = lazy(() => import('./pages/TaxConfigurationPage'))
const AuditLogsPage = lazy(() => import('./pages/AuditLogsPage'))
const InvoicesPage = lazy(() => import('./pages/InvoicesPage'))
const NewInvoicePage = lazy(() => import('./pages/NewInvoicePage'))
const InvoiceDetailPage = lazy(() => import('./pages/InvoiceDetailPage'))

// Reports
const SalesReportPage = lazy(() => import('./pages/reports/SalesReportPage'))
const SalesGstReportPage = lazy(() => import('./pages/reports/SalesGstReportPage'))
const PurchaseReportPage = lazy(() => import('./pages/reports/PurchaseReportPage'))
const InventoryReportPage = lazy(() => import('./pages/reports/InventoryReportPage'))
const StockMovementReportPage = lazy(() => import('./pages/reports/StockMovementReportPage'))
const ProductSalesReportPage = lazy(() => import('./pages/reports/ProductSalesReportPage'))
const CustomerSalesReportPage = lazy(() => import('./pages/reports/CustomerSalesReportPage'))
const TaxReportPage = lazy(() => import('./pages/reports/TaxReportPage'))
const ProfitReportPage = lazy(() => import('./pages/reports/ProfitReportPage'))
const TopProductsReportPage = lazy(() => import('./pages/reports/TopProductsReportPage'))

function App() {
  return (
    <AuthProvider>
      <EnvironmentBanner />
      <BrowserRouter>
        <Routes>
          <Route
            path="/login"
            element={
              <Suspense fallback={<div className="loading-screen">Loading...</div>}>
                <LoginPage />
              </Suspense>
            }
          />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route path="/" element={<Navigate to="/dashboard" replace />} />
              <Route path="/dashboard" element={<DashboardPage />} />
              <Route path="/reports/sales" element={<SalesReportPage />} />
              <Route path="/reports/sales-gst" element={<SalesGstReportPage />} />
              <Route path="/reports/purchases" element={<PurchaseReportPage />} />
              <Route path="/reports/inventory" element={<InventoryReportPage />} />
              <Route path="/reports/stock-movement" element={<StockMovementReportPage />} />
              <Route path="/reports/products" element={<ProductSalesReportPage />} />
              <Route path="/reports/customers" element={<CustomerSalesReportPage />} />
              <Route path="/reports/tax" element={<TaxReportPage />} />
              <Route path="/reports/profit" element={<ProfitReportPage />} />
              <Route path="/reports/top-products" element={<TopProductsReportPage />} />
              <Route path="/products" element={<ProductsPage />} />
              <Route path="/products/:id/edit" element={<EditProductPage />} />
              <Route path="/catalogue" element={<CataloguePage />} />
              <Route path="/customers" element={<CustomersPage />} />
              <Route path="/customers/:id" element={<CustomerDetailPage />} />
              <Route path="/inventory" element={<InventoryPage />} />
              <Route path="/inventory/:productId" element={<ProductStockDetailPage />} />
              <Route path="/inventory/adjustments" element={<StockAdjustmentsPage />} />
              <Route path="/inventory/adjustments/new" element={<NewStockAdjustmentPage />} />
              <Route path="/inventory/adjustments/:id" element={<StockAdjustmentDetailPage />} />
              <Route path="/inventory/opening-stock" element={<OpeningStockListPage />} />
              <Route path="/inventory/opening-stock/new" element={<NewOpeningStockPage />} />
              <Route path="/inventory/opening-stock/:id" element={<OpeningStockDetailPage />} />
              <Route path="/inventory/transfers" element={<WarehouseTransfersPage />} />
              <Route path="/inventory/transfers/new" element={<NewWarehouseTransferPage />} />
              <Route path="/inventory/transfers/:id" element={<WarehouseTransferDetailPage />} />
              <Route path="/stock-ledger" element={<StockLedgerPage />} />
              <Route path="/purchases" element={<PurchasesPage />} />
              <Route path="/purchases/new" element={<NewPurchasePage />} />
              <Route path="/purchases/:id" element={<PurchaseDetailPage />} />
              <Route path="/suppliers" element={<SuppliersPage />} />
              <Route path="/suppliers/:id" element={<SupplierDetailPage />} />
              <Route path="/suppliers/:id/ledger" element={<SupplierLedgerPage />} />
              <Route path="/warehouses" element={<WarehousesPage />} />
              <Route path="/settings/business" element={<BusinessProfilePage />} />
              <Route path="/settings/taxes" element={<TaxConfigurationPage />} />
              <Route path="/audit-logs" element={<AuditLogsPage />} />
              <Route path="/invoices" element={<InvoicesPage />} />
              <Route path="/invoices/new" element={<NewInvoicePage />} />
              <Route path="/invoices/:id" element={<InvoiceDetailPage />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Route>
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}

export default App
