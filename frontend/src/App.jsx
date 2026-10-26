import { Suspense } from "react";
import { Navigate, Routes, Route, useLocation } from "react-router-dom";
import lazyPage from "./lib/lazyPage";
import { ToastProvider } from "./components/Toast";
import { useAuth } from "./context/AuthContext";
import Layout       from "./components/Layout";
const JoinPartner = lazyPage(() => import("./pages/JoinPartner"));
const JoinThrift = lazyPage(() => import("./pages/JoinThrift"));
const Landing = lazyPage(() => import("./pages/Landing"));
import Login        from "./pages/Login";
import Chat         from "./pages/Chat";
const Dashboard = lazyPage(() => import("./pages/Dashboard"));
const Insights = lazyPage(() => import("./pages/Insights"));
const Poultry = lazyPage(() => import("./pages/Poultry"));
const School = lazyPage(() => import("./pages/School"));
const Customers = lazyPage(() => import("./pages/Customers"));
const Transactions = lazyPage(() => import("./pages/Transactions"));
const Inventory = lazyPage(() => import("./pages/Inventory"));
const Suppliers = lazyPage(() => import("./pages/Suppliers"));
const Staff = lazyPage(() => import("./pages/Staff"));
const Partners = lazyPage(() => import("./pages/Partners"));
const Notes = lazyPage(() => import("./pages/Notes"));
const Admin = lazyPage(() => import("./pages/Admin"));
const Reminders = lazyPage(() => import("./pages/Reminders"));
const Automation = lazyPage(() => import("./pages/Automation"));
const Branches = lazyPage(() => import("./pages/Branches"));
const Capture = lazyPage(() => import("./pages/Capture"));
const POS = lazyPage(() => import("./pages/POS"));
const Receipt = lazyPage(() => import("./pages/Receipt"));
const SupplierReceipt = lazyPage(() => import("./pages/SupplierReceipt"));
const Receipts = lazyPage(() => import("./pages/Receipts"));
const NewReceipt = lazyPage(() => import("./pages/NewReceipt"));
const Invoices = lazyPage(() => import("./pages/Invoices"));
const Expenses = lazyPage(() => import("./pages/Expenses"));
const InvoiceEditor = lazyPage(() => import("./pages/InvoiceEditor"));
const InvoiceView = lazyPage(() => import("./pages/InvoiceView"));
const Deliveries = lazyPage(() => import("./pages/Deliveries"));
const WaybillView = lazyPage(() => import("./pages/WaybillView"));
const StockCounts = lazyPage(() => import("./pages/StockCounts"));
const PayPage = lazyPage(() => import("./pages/PayPage"));
const PaymentClaims = lazyPage(() => import("./pages/PaymentClaims"));
const PurchaseOrders = lazyPage(() => import("./pages/PurchaseOrders"));
const PurchaseOrderEditor = lazyPage(() => import("./pages/PurchaseOrderEditor"));
const PurchaseOrderView = lazyPage(() => import("./pages/PurchaseOrderView"));
const StockCount = lazyPage(() => import("./pages/StockCount"));
const Wallet = lazyPage(() => import("./pages/Wallet"));
const Thrift = lazyPage(() => import("./pages/Thrift"));
const FuelStation = lazyPage(() => import("./pages/FuelStation"));
const Opportunities = lazyPage(() => import("./pages/Opportunities"));
const Scorecard = lazyPage(() => import("./pages/Scorecard"));
const Terms = lazyPage(() => import("./pages/Terms"));
const Privacy = lazyPage(() => import("./pages/Privacy"));
const DataDeletion = lazyPage(() => import("./pages/DataDeletion"));
const Upgrade = lazyPage(() => import("./pages/Upgrade"));
const Profile = lazyPage(() => import("./pages/Profile"));
const Settings = lazyPage(() => import("./pages/Settings"));

function RequireAuth({ children }) {
  const { isAuthed } = useAuth();
  const location = useLocation();
  // Preserve deep links (e.g. a partner invite) through the login round-trip.
  const next = encodeURIComponent(location.pathname + location.search);
  return isAuthed ? children : <Navigate to={`/login?next=${next}`} replace />;
}

export default function App() {
  return (
    <ToastProvider>
      {/* Public pages load on demand too; pages inside the app wait inside
          the menu frame (Layout) so the menu stays on screen. */}
      <Suspense fallback={<div className="page-loading">Loading…</div>}>
      <Routes>
        {/* Public */}
        <Route index element={<Landing />} />
        <Route path="login" element={<Login />} />
        <Route path="terms" element={<Terms />} />
        <Route path="privacy" element={<Privacy />} />
        <Route path="data-deletion" element={<DataDeletion />} />
        {/* A customer's pay page — opened from WhatsApp, no login */}
        <Route path="pay/:token" element={<PayPage />} />

        {/* Authenticated — all inside sidebar Layout */}
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route path="home"         element={<Chat />}         />
          <Route path="dashboard"    element={<Dashboard />}    />
          <Route path="insights"     element={<Insights />}     />
          <Route path="poultry"      element={<Poultry />}      />
          <Route path="school"       element={<School />}       />
          <Route path="capture"      element={<Capture />}      />
          <Route path="pos"          element={<POS />}          />
          <Route path="pos/receipt/:id" element={<Receipt />}   />
          <Route path="suppliers/receipt/:kind/:id" element={<SupplierReceipt />} />
          <Route path="receipts"     element={<Receipts />}     />
          <Route path="receipts/new" element={<NewReceipt />}   />
          <Route path="invoices"     element={<Invoices />}     />
          <Route path="expenses"     element={<Expenses />}     />
          <Route path="invoices/new" element={<InvoiceEditor />} />
          <Route path="invoices/:id" element={<InvoiceView />}  />
          <Route path="invoices/:id/edit" element={<InvoiceEditor />} />
          <Route path="deliveries"   element={<Deliveries />}   />
          <Route path="waybills/:id" element={<WaybillView />}  />
          <Route path="stock-counts"     element={<StockCounts />} />
          <Route path="payment-claims"   element={<PaymentClaims />} />
          <Route path="purchase-orders"          element={<PurchaseOrders />} />
          <Route path="purchase-orders/new"      element={<PurchaseOrderEditor />} />
          <Route path="purchase-orders/:id"      element={<PurchaseOrderView />} />
          <Route path="purchase-orders/:id/edit" element={<PurchaseOrderEditor />} />
          <Route path="stock-counts/:id" element={<StockCount />}  />
          <Route path="customers"    element={<Customers />}    />
          <Route path="transactions" element={<Transactions />} />
          <Route path="inventory"    element={<Inventory />}    />
          <Route path="fuel"         element={<FuelStation />}  />
          <Route path="suppliers"    element={<Suppliers />}    />
          <Route path="staff"        element={<Staff />}        />
          <Route path="partners"     element={<Partners />}     />
          <Route path="partners/join/:token" element={<JoinPartner />} />
          <Route path="notes"        element={<Notes />}        />
          <Route path="reminders"    element={<Reminders />}    />
          <Route path="wallet"       element={<Wallet />}       />
          <Route path="thrift"       element={<Thrift />}       />
          <Route path="thrift/join/:token" element={<JoinThrift />} />
          <Route path="branches"     element={<Branches />}     />
          <Route path="automation"     element={<Automation />}     />
          <Route path="opportunities" element={<Opportunities />} />
          <Route path="scorecard"    element={<Scorecard />}      />
          <Route path="admin"        element={<Admin />}          />
          <Route path="upgrade"      element={<Upgrade />}        />
          <Route path="profile"      element={<Profile />}        />
          <Route path="settings"     element={<Settings />}       />
        </Route>

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
    </ToastProvider>
  );
}
