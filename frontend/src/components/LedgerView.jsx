import { useState, useEffect } from 'react';
import { getRecentTransactions } from '../services/api';

export function LedgerView({ onRecordTransaction }) {
  const [transactions, setTransactions] = useState([]);
  const [filterType, setFilterType] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    async function loadData() {
      setIsLoading(true);
      setError(null);
      try {
        const data = await getRecentTransactions(100);
        if (isMounted) setTransactions(data);
      } catch (err) {
        if (isMounted) {
          console.error('Failed to load ledger:', err);
          setError(err.message || 'Failed to load ledger transactions');
        }
      } finally {
        if (isMounted) setIsLoading(false);
      }
    }

    loadData();
    return () => {
      isMounted = false;
    };
  }, []);

  async function loadLedger() {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getRecentTransactions(100);
      setTransactions(data);
    } catch (err) {
      console.error('Failed to load ledger:', err);
      setError(err.message || 'Failed to load ledger transactions');
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

  const filteredTxns = transactions.filter((t) => {
    const matchesType = filterType === 'ALL' || t.transaction_type === filterType;
    const q = searchQuery.toLowerCase().trim();
    const matchesSearch =
      !q ||
      t.customer_name.toLowerCase().includes(q) ||
      (t.customer_phone && t.customer_phone.includes(q)) ||
      (t.description && t.description.toLowerCase().includes(q));
    return matchesType && matchesSearch;
  });

  const totalCreditFiltered = filteredTxns
    .filter((t) => t.transaction_type === 'CREDIT')
    .reduce((sum, t) => sum + t.amount, 0);

  const totalPaymentFiltered = filteredTxns
    .filter((t) => t.transaction_type === 'PAYMENT')
    .reduce((sum, t) => sum + t.amount, 0);

  return (
    <div className="ledger-view">
      <div className="view-header">
        <div>
          <h2 className="view-title">ಖಾತೆ ಪುಸ್ತಕ / Complete Kirana Ledger</h2>
          <p className="view-subtitle">Chronological record of all credit and payments from SQLite</p>
        </div>
        <div className="view-header-actions">
          <button
            type="button"
            className="secondary-btn"
            onClick={loadLedger}
            disabled={isLoading}
          >
            🔄 Refresh
          </button>
          <button
            type="button"
            className="primary-action-btn"
            onClick={() => onRecordTransaction(null, 'CREDIT')}
          >
            ➕ Manual Entry
          </button>
        </div>
      </div>

      {/* Filter and Search Bar */}
      <div className="ledger-controls-row">
        <div className="filter-buttons-group">
          <button
            type="button"
            className={`filter-btn ${filterType === 'ALL' ? 'active' : ''}`}
            onClick={() => setFilterType('ALL')}
          >
            ಎಲ್ಲವೂ / All ({transactions.length})
          </button>
          <button
            type="button"
            className={`filter-btn btn-credit-filter ${filterType === 'CREDIT' ? 'active' : ''}`}
            onClick={() => setFilterType('CREDIT')}
          >
            ಉದ್ದಾರ / Credit
          </button>
          <button
            type="button"
            className={`filter-btn btn-payment-filter ${filterType === 'PAYMENT' ? 'active' : ''}`}
            onClick={() => setFilterType('PAYMENT')}
          >
            ಜಮಾ / Payment
          </button>
        </div>

        <div className="ledger-search-box">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="search-input"
            placeholder="ಹುಡುಕಿ / Search ledger..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Summary Totals of Filtered Selection */}
      <div className="ledger-summary-strip">
        <div className="strip-item">
          <span className="strip-label">Showing Entries:</span>
          <strong>{filteredTxns.length}</strong>
        </div>
        <div className="strip-item">
          <span className="strip-label">Filter Total Credit:</span>
          <strong className="amt-credit">₹ {totalCreditFiltered}</strong>
        </div>
        <div className="strip-item">
          <span className="strip-label">Filter Total Payments:</span>
          <strong className="amt-payment">₹ {totalPaymentFiltered}</strong>
        </div>
        <div className="strip-item">
          <span className="strip-label">Difference:</span>
          <strong>₹ {totalCreditFiltered - totalPaymentFiltered}</strong>
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
        </div>
      )}

      {/* Transactions Table */}
      {isLoading ? (
        <div className="view-loading">Loading ledger transactions...</div>
      ) : filteredTxns.length === 0 ? (
        <div className="view-empty">
          <p className="empty-icon">📖</p>
          <h3>ಯಾವುದೇ ದಾಖಲೆಗಳು ಸಿಗಲಿಲ್ಲ / No Ledger Records</h3>
          <p>
            {searchQuery || filterType !== 'ALL'
              ? 'No transactions match the selected filter or search.'
              : 'Start speaking with the Voice Assistant to create transactions!'}
          </p>
        </div>
      ) : (
        <div className="table-responsive">
          <table className="kirana-table">
            <thead>
              <tr>
                <th>Txn #</th>
                <th>ದಿನಾಂಕ & ಸಮಯ / Date & Time</th>
                <th>ಗ್ರಾಹಕರು / Customer</th>
                <th>ಪ್ರಕಾರ / Type</th>
                <th>ಮೊತ್ತ / Amount</th>
                <th>ವಿವರಣೆ / Description</th>
              </tr>
            </thead>
            <tbody>
              {filteredTxns.map((t) => (
                <tr key={t.id}>
                  <td className="cell-id">#{t.id}</td>
                  <td className="cell-date">{formatDateTime(t.created_at)}</td>
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
                  <td className="cell-desc">{t.description || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
