import { useState, useEffect, useCallback } from 'react';
import {
  getCustomersSummary,
  createCustomer,
  getCustomerTransactions,
  getCustomerBalance,
} from '../services/api';

export function CustomersView({
  onRecordTransaction,
  newCustomerModalOpen,
  setNewCustomerModalOpen,
  onNotification,
}) {
  const [customers, setCustomers] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // New Customer Form State
  const [newName, setNewName] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [formError, setFormError] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Selected Customer Details Modal
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [customerTxns, setCustomerTxns] = useState([]);
  const [customerBalance, setCustomerBalance] = useState(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);

  const loadCustomers = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getCustomersSummary(searchQuery);
      setCustomers(data);
    } catch (err) {
      console.error('Failed to load customers:', err);
      setError(err.message || 'Failed to load customer list');
    } finally {
      setIsLoading(false);
    }
  }, [searchQuery]);

  useEffect(() => {
    let isMounted = true;
    getCustomersSummary(searchQuery)
      .then((data) => {
        if (isMounted) {
          setCustomers(data);
          setIsLoading(false);
        }
      })
      .catch((err) => {
        if (isMounted) {
          setError(err.message || 'Failed to load customer list');
          setIsLoading(false);
        }
      });

    return () => {
      isMounted = false;
    };
  }, [searchQuery]);

  async function handleCreateCustomer(e) {
    e.preventDefault();
    setFormError(null);

    const nameTrimmed = newName.trim();
    const phoneTrimmed = newPhone.trim();

    if (nameTrimmed.length < 2) {
      setFormError('Customer name must contain at least 2 characters.');
      return;
    }

    if (phoneTrimmed && !/^\d{10}$/.test(phoneTrimmed)) {
      setFormError('Phone number must be exactly 10 digits (e.g. 9876543210).');
      return;
    }

    setIsSubmitting(true);
    try {
      const created = await createCustomer({
        name: nameTrimmed,
        phone: phoneTrimmed || null,
      });

      onNotification({
        type: 'success',
        message: `Customer '${created.name}' added successfully!`,
      });

      setNewName('');
      setNewPhone('');
      setNewCustomerModalOpen(false);
      await loadCustomers();
    } catch (err) {
      setFormError(err.message || 'Failed to create customer');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleOpenCustomerDetails(customer) {
    setSelectedCustomer(customer);
    setIsLoadingDetails(true);
    try {
      const [txns, bal] = await Promise.all([
        getCustomerTransactions(customer.id),
        getCustomerBalance(customer.id),
      ]);
      setCustomerTxns(txns);
      setCustomerBalance(bal);
    } catch (err) {
      onNotification({
        type: 'error',
        message: `Could not load details for ${customer.name}: ${err.message}`,
      });
    } finally {
      setIsLoadingDetails(false);
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
    <div className="customers-view">
      {/* View Header with Search & Add Customer */}
      <div className="view-header">
        <div>
          <h2 className="view-title">ಗ್ರಾಹಕರ ಪಟ್ಟಿ / Customers</h2>
          <p className="view-subtitle">Manage customer ledger accounts and balances</p>
        </div>

        <button
          type="button"
          className="primary-action-btn"
          onClick={() => {
            setFormError(null);
            setNewCustomerModalOpen(true);
          }}
        >
          ➕ ಹೊಸ ಗ್ರಾಹಕ / Add Customer
        </button>
      </div>

      {/* Search Input */}
      <div className="search-bar-row">
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            type="text"
            className="search-input"
            placeholder="ಗ್ರಾಹಕರ ಹೆಸರು ಅಥವಾ ಫೋನ್ ನಂಬರ್ ಹುಡುಕಿ / Search by name or 10-digit phone..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              className="clear-search-btn"
              onClick={() => setSearchQuery('')}
            >
              ✕
            </button>
          )}
        </div>
        <span className="count-badge">{customers.length} ಗ್ರಾಹಕರು / Customers</span>
      </div>

      {error && (
        <div className="error-banner">
          <span>⚠️ {error}</span>
        </div>
      )}

      {/* Customers Table / Grid */}
      {isLoading ? (
        <div className="view-loading">Loading customers...</div>
      ) : customers.length === 0 ? (
        <div className="view-empty">
          <p className="empty-icon">👥</p>
          <h3>ಯಾವುದೇ ಗ್ರಾಹಕರು ಸಿಗಲಿಲ್ಲ / No Customers Found</h3>
          <p>
            {searchQuery
              ? `No customer matches '${searchQuery}'`
              : 'Add your first customer to get started with DukaanVoice.'}
          </p>
          <button
            type="button"
            className="primary-action-btn"
            onClick={() => setNewCustomerModalOpen(true)}
          >
            ➕ Add Customer
          </button>
        </div>
      ) : (
        <div className="table-responsive">
          <table className="kirana-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>ಹೆಸರು / Customer Name</th>
                <th>ಫೋನ್ / Phone</th>
                <th>ಒಟ್ಟು ಉದ್ದಾರ / Total Credit</th>
                <th>ಒಟ್ಟು ಜಮಾ / Total Payments</th>
                <th>ಬಾಕಿ / Outstanding Balance</th>
                <th>ಕ್ರಮಗಳು / Actions</th>
              </tr>
            </thead>
            <tbody>
              {customers.map((c) => (
                <tr key={c.id}>
                  <td className="cell-id">#{c.id}</td>
                  <td className="cell-name">
                    <span className="cust-avatar">👤</span>
                    <div>
                      <strong>{c.name}</strong>
                    </div>
                  </td>
                  <td className="cell-phone">{c.phone ? `📞 ${c.phone}` : '-'}</td>
                  <td className="cell-number">₹ {c.total_credit}</td>
                  <td className="cell-number">₹ {c.total_payments}</td>
                  <td className="cell-balance">
                    <strong
                      className={`balance-tag ${
                        c.outstanding_balance > 0
                          ? 'tag-due'
                          : c.outstanding_balance < 0
                          ? 'tag-advance'
                          : 'tag-clear'
                      }`}
                    >
                      {c.outstanding_balance > 0
                        ? `₹ ${c.outstanding_balance}`
                        : c.outstanding_balance < 0
                        ? `₹ 0 (Adv ₹${Math.abs(c.outstanding_balance)})`
                        : '₹ 0'}
                    </strong>
                  </td>
                  <td className="cell-actions">
                    <button
                      type="button"
                      className="table-action-btn btn-view"
                      onClick={() => handleOpenCustomerDetails(c)}
                      title="View full customer history"
                    >
                      ವಿವರ / History
                    </button>
                    <button
                      type="button"
                      className="table-action-btn btn-credit"
                      onClick={() => onRecordTransaction(c, 'CREDIT')}
                      title="Record credit transaction"
                    >
                      + ಉದ್ದಾರ
                    </button>
                    <button
                      type="button"
                      className="table-action-btn btn-payment"
                      onClick={() => onRecordTransaction(c, 'PAYMENT')}
                      title="Record payment transaction"
                    >
                      - ಜಮಾ
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* New Customer Modal */}
      {newCustomerModalOpen && (
        <div className="modal-backdrop">
          <div className="modal-container">
            <div className="modal-header">
              <h3 className="modal-title">ಹೊಸ ಗ್ರಾಹಕರನ್ನು ಸೇರಿಸಿ / Add New Customer</h3>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setNewCustomerModalOpen(false)}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateCustomer} className="modal-form">
              {formError && (
                <div className="form-error-alert">
                  <span>⚠️ {formError}</span>
                </div>
              )}

              <div className="form-group">
                <label htmlFor="customer-name-input">
                  ಗ್ರಾಹಕರ ಹೆಸರು / Customer Name <span className="required-star">*</span>
                </label>
                <input
                  id="customer-name-input"
                  type="text"
                  className="form-input"
                  placeholder="ಉದಾ: Ramesh, Suresh, Raju..."
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  minLength={2}
                  maxLength={100}
                  required
                  autoFocus
                />
              </div>

              <div className="form-group">
                <label htmlFor="customer-phone-input">
                  ಫೋನ್ ಸಂಖ್ಯೆ / Mobile Number (10 digits)
                </label>
                <input
                  id="customer-phone-input"
                  type="tel"
                  className="form-input"
                  placeholder="ಉದಾ: 9876543210"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  maxLength={10}
                />
                <span className="input-hint">Unique 10-digit mobile number for credit records</span>
              </div>

              <div className="modal-footer">
                <button
                  type="button"
                  className="secondary-btn"
                  onClick={() => setNewCustomerModalOpen(false)}
                  disabled={isSubmitting}
                >
                  ರದ್ದು / Cancel
                </button>
                <button
                  type="submit"
                  className="primary-btn"
                  disabled={isSubmitting || !newName.trim()}
                >
                  {isSubmitting ? 'ಉಳಿಸಲಾಗುತ್ತಿದೆ...' : 'ಸೇರಿಸಿ / Save Customer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Customer Details & History Modal */}
      {selectedCustomer && (
        <div className="modal-backdrop">
          <div className="modal-container modal-wide">
            <div className="modal-header">
              <div className="customer-modal-header-info">
                <span className="customer-avatar-large">👤</span>
                <div>
                  <h3 className="modal-title">{selectedCustomer.name}</h3>
                  <span className="modal-sub">
                    {selectedCustomer.phone ? `📞 ${selectedCustomer.phone}` : 'No phone recorded'} • ID #{selectedCustomer.id}
                  </span>
                </div>
              </div>
              <button
                type="button"
                className="modal-close-btn"
                onClick={() => setSelectedCustomer(null)}
              >
                ✕
              </button>
            </div>

            <div className="customer-modal-body">
              {/* Balance Summary Bar */}
              {customerBalance && (
                <div className="customer-balance-banner">
                  <div className="bal-item">
                    <span className="bal-lbl">ಒಟ್ಟು ಉದ್ದಾರ / Total Credit</span>
                    <strong className="bal-val amt-credit">₹ {customerBalance.total_credit}</strong>
                  </div>
                  <div className="bal-divider">-</div>
                  <div className="bal-item">
                    <span className="bal-lbl">ಒಟ್ಟು ಜಮಾ / Total Payments</span>
                    <strong className="bal-val amt-payment">₹ {customerBalance.total_payments}</strong>
                  </div>
                  <div className="bal-divider">=</div>
                  <div className="bal-item">
                    <span className="bal-lbl">
                      {customerBalance.outstanding_balance < 0
                        ? 'ಮುಂಗಡ / Advance Balance'
                        : 'ನಿವ್ವಳ ಬಾಕಿ / Outstanding Due'}
                    </span>
                    <strong
                      className={`bal-val ${
                        customerBalance.outstanding_balance > 0
                          ? 'amt-credit'
                          : customerBalance.outstanding_balance < 0
                          ? 'amt-advance'
                          : 'amt-payment'
                      }`}
                    >
                      {customerBalance.outstanding_balance < 0
                        ? `₹ ${Math.abs(customerBalance.outstanding_balance)} Advance`
                        : `₹ ${customerBalance.outstanding_balance}`}
                    </strong>
                  </div>
                </div>
              )}

              {/* Action buttons inside customer details */}
              <div className="customer-details-actions">
                <button
                  type="button"
                  className="primary-action-btn btn-credit"
                  onClick={() => {
                    onRecordTransaction(selectedCustomer, 'CREDIT');
                  }}
                >
                  + ಉದ್ದಾರ ದಾಖಲಿಸಿ / Record Credit
                </button>
                <button
                  type="button"
                  className="primary-action-btn btn-payment"
                  onClick={() => {
                    onRecordTransaction(selectedCustomer, 'PAYMENT');
                  }}
                >
                  - ಜಮಾ ದಾಖಲಿಸಿ / Record Payment
                </button>
              </div>

              {/* Full Customer Transaction History */}
              <h4 className="sub-title">ವಹಿವಾಟು ಇತಿಹಾಸ / Transaction History</h4>

              {isLoadingDetails ? (
                <div className="view-loading">Loading transactions...</div>
              ) : customerTxns.length === 0 ? (
                <div className="view-empty">No transactions found for this customer.</div>
              ) : (
                <div className="table-responsive">
                  <table className="kirana-table">
                    <thead>
                      <tr>
                        <th>Txn ID</th>
                        <th>ಪ್ರಕಾರ / Type</th>
                        <th>ಮೊತ್ತ / Amount</th>
                        <th>ವಿವರಣೆ / Description</th>
                        <th>ದಿನಾಂಕ / Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {customerTxns.map((t) => (
                        <tr key={t.id}>
                          <td>#{t.id}</td>
                          <td>
                            <span
                              className={`badge-pill ${
                                t.transaction_type === 'CREDIT' ? 'badge-credit' : 'badge-payment'
                              }`}
                            >
                              {t.transaction_type === 'CREDIT' ? 'ಉದ್ದಾರ' : 'ಜಮಾ'}
                            </span>
                          </td>
                          <td>
                            <strong
                              className={
                                t.transaction_type === 'CREDIT' ? 'amt-credit' : 'amt-payment'
                              }
                            >
                              {t.transaction_type === 'CREDIT' ? '+' : '-'} ₹ {t.amount}
                            </strong>
                          </td>
                          <td>{t.description || '-'}</td>
                          <td>{formatDateTime(t.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="modal-footer">
              <button
                type="button"
                className="secondary-btn"
                onClick={() => setSelectedCustomer(null)}
              >
                ಮುಚ್ಚಿ / Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
