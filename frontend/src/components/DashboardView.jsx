import { useState, useEffect } from 'react';
import { getDashboardStats, getRecentTransactions, getCustomersSummary } from '../services/api';

export function DashboardView({ onSelectTab, onOpenNewCustomer, onRecordTransaction }) {
  const [stats, setStats] = useState({
    total_credit: 0,
    total_payments: 0,
    outstanding_balance: 0,
    customer_count: 0,
    transaction_count: 0,
  });
  const [recentTxns, setRecentTxns] = useState([]);
  const [topCustomers, setTopCustomers] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    async function loadData() {
      setIsLoading(true);
      setError(null);
      try {
        const [statsData, txnsData, customersData] = await Promise.all([
          getDashboardStats(),
          getRecentTransactions(10),
          getCustomersSummary(),
        ]);
        if (!isMounted) return;
        setStats(statsData);
        setRecentTxns(txnsData);

        const sorted = [...customersData]
          .filter((c) => c.outstanding_balance > 0)
          .sort((a, b) => b.outstanding_balance - a.outstanding_balance)
          .slice(0, 5);
        setTopCustomers(sorted);
      } catch (err) {
        if (!isMounted) return;
        console.error('Failed to load dashboard:', err);
        setError(err.message || 'Failed to load dashboard data');
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, []);

  async function refreshDashboard() {
    setIsLoading(true);
    setError(null);
    try {
      const [statsData, txnsData, customersData] = await Promise.all([
        getDashboardStats(),
        getRecentTransactions(10),
        getCustomersSummary(),
      ]);
      setStats(statsData);
      setRecentTxns(txnsData);

      const sorted = [...customersData]
        .filter((c) => c.outstanding_balance > 0)
        .sort((a, b) => b.outstanding_balance - a.outstanding_balance)
        .slice(0, 5);
      setTopCustomers(sorted);
    } catch (err) {
      console.error('Failed to load dashboard:', err);
      setError(err.message || 'Failed to load dashboard data');
    } finally {
      setIsLoading(false);
    }
  }

  function formatDateTime(isoString) {
    if (!isoString) return '-';
    try {
      const d = new Date(isoString);
      return d.toLocaleString('en-IN', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  }

  return (
    <div className="dashboard-view">
      <div className="view-header">
        <div>
          <h2 className="view-title">ಡ್ಯಾಶ್‌ಬೋರ್ಡ್ / Kirana Dashboard</h2>
          <p className="view-subtitle">Live store overview calculated directly from SQLite ledger</p>
        </div>
        <button
          type="button"
          className="refresh-btn"
          onClick={refreshDashboard}
          disabled={isLoading}
        >
          🔄 {isLoading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
        </div>
      )}

      {/* 4 Core Metric Cards */}
      <div className="metrics-grid">
        <div className="metric-card card-credit">
          <div className="metric-icon-wrap icon-credit">₹</div>
          <div className="metric-content">
            <span className="metric-title">ಒಟ್ಟು ಉದ್ದಾರ / Total Credit Given</span>
            <span className="metric-amount">₹ {stats.total_credit.toLocaleString('en-IN')}</span>
            <span className="metric-note">All customer purchases on credit</span>
          </div>
        </div>

        <div className="metric-card card-payment">
          <div className="metric-icon-wrap icon-payment">📥</div>
          <div className="metric-content">
            <span className="metric-title">ಒಟ್ಟು ಜಮಾ / Total Payments Received</span>
            <span className="metric-amount">₹ {stats.total_payments.toLocaleString('en-IN')}</span>
            <span className="metric-note">Cash & payments received</span>
          </div>
        </div>

        <div className="metric-card card-balance">
          <div className="metric-icon-wrap icon-balance">⚖️</div>
          <div className="metric-content">
            <span className="metric-title">ನಿವ್ವಳ ಬಾಕಿ / Net Outstanding</span>
            <span className="metric-amount">
              {stats.outstanding_balance < 0
                ? `₹ 0 (Adv ₹${Math.abs(stats.outstanding_balance).toLocaleString('en-IN')})`
                : `₹ ${stats.outstanding_balance.toLocaleString('en-IN')}`}
            </span>
            <span className="metric-note">
              {stats.outstanding_balance < 0
                ? 'Store holds customer advance deposits'
                : 'Credit minus Payments'}
            </span>
          </div>
        </div>

        <div className="metric-card card-customers">
          <div className="metric-icon-wrap icon-customers">👥</div>
          <div className="metric-content">
            <span className="metric-title">ಗ್ರಾಹಕರು / Total Customers</span>
            <span className="metric-amount">{stats.customer_count}</span>
            <span className="metric-note">{stats.transaction_count} total ledger transactions</span>
          </div>
        </div>
      </div>

      {/* Quick Actions Row */}
      <div className="quick-actions-bar">
        <div className="quick-action-text">
          <strong>ವೇಗದ ಕ್ರಮಗಳು / Quick Actions:</strong>
        </div>
        <button
          type="button"
          className="action-pill-btn btn-voice"
          onClick={() => onSelectTab('voice')}
        >
          🎙️ ಧ್ವನಿ ಸಹಾಯಕ / Open Voice Assistant
        </button>
        <button
          type="button"
          className="action-pill-btn btn-customer"
          onClick={onOpenNewCustomer}
        >
          ➕ ಹೊಸ ಗ್ರಾಹಕ / New Customer
        </button>
        <button
          type="button"
          className="action-pill-btn btn-record"
          onClick={() => onRecordTransaction(null, 'CREDIT')}
        >
          📝 ಉದ್ದಾರ ದಾಖಲಿಸಿ / Record Credit
        </button>
      </div>

      {/* Two Column Section: Recent Transactions + Top Outstanding */}
      <div className="dashboard-columns-grid">
        {/* Recent Transactions */}
        <div className="dashboard-panel panel-txns">
          <div className="panel-header">
            <h3 className="panel-title">ಇತ್ತೀಚಿನ ವಹಿವಾಟುಗಳು / Recent Transactions</h3>
            <button
              type="button"
              className="panel-link-btn"
              onClick={() => onSelectTab('ledger')}
            >
              See All ➔
            </button>
          </div>

          {isLoading ? (
            <div className="panel-loading">Loading transactions...</div>
          ) : recentTxns.length === 0 ? (
            <div className="panel-empty">No transactions recorded yet.</div>
          ) : (
            <div className="table-responsive">
              <table className="kirana-table">
                <thead>
                  <tr>
                    <th>ಗ್ರಾಹಕರು / Customer</th>
                    <th>ಪ್ರಕಾರ / Type</th>
                    <th>ಮೊತ್ತ / Amount</th>
                    <th>ದಿನಾಂಕ / Date</th>
                  </tr>
                </thead>
                <tbody>
                  {recentTxns.map((t) => (
                    <tr key={t.id}>
                      <td className="cell-customer">
                        <span className="cust-avatar">👤</span>
                        <div>
                          <strong>{t.customer_name}</strong>
                          {t.customer_phone && <span className="cell-sub">{t.customer_phone}</span>}
                        </div>
                      </td>
                      <td>
                        <span
                          className={`badge-pill ${
                            t.transaction_type === 'CREDIT' ? 'badge-credit' : 'badge-payment'
                          }`}
                        >
                          {t.transaction_type === 'CREDIT' ? 'ಉದ್ದಾರ' : 'ಜಮಾ'}
                        </span>
                      </td>
                      <td className="cell-amount">
                        <strong
                          className={t.transaction_type === 'CREDIT' ? 'amt-credit' : 'amt-payment'}
                        >
                          {t.transaction_type === 'CREDIT' ? '+' : '-'} ₹ {t.amount}
                        </strong>
                      </td>
                      <td className="cell-date">{formatDateTime(t.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Top Credit Customers */}
        <div className="dashboard-panel panel-customers">
          <div className="panel-header">
            <h3 className="panel-title">ಹೆಚ್ಚು ಬಾಕಿ ಇರುವವರು / Top Outstanding</h3>
            <button
              type="button"
              className="panel-link-btn"
              onClick={() => onSelectTab('customers')}
            >
              View All ➔
            </button>
          </div>

          {isLoading ? (
            <div className="panel-loading">Loading balances...</div>
          ) : topCustomers.length === 0 ? (
            <div className="panel-empty">No pending dues from customers! 🎉</div>
          ) : (
            <div className="top-customers-list">
              {topCustomers.map((c) => (
                <div key={c.id} className="top-customer-item">
                  <div className="top-cust-info">
                    <strong>{c.name}</strong>
                    <span className="top-cust-phone">📞 {c.phone || 'No phone'}</span>
                  </div>
                  <div className="top-cust-balance">
                    <span className="due-label">ಬಾಕಿ / Due:</span>
                    <strong className="due-amount">₹ {c.outstanding_balance}</strong>
                  </div>
                  <button
                    type="button"
                    className="quick-pay-btn"
                    onClick={() => onRecordTransaction(c, 'PAYMENT')}
                    title="Record payment from this customer"
                  >
                    ಜಮಾ / Pay
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
