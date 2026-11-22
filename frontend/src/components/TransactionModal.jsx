import { useState, useEffect } from 'react';
import { createTransaction, getCustomers } from '../services/api';

export function TransactionModal({
  isOpen,
  onClose,
  initialCustomer,
  initialType = 'CREDIT',
  onSuccess,
  onNotification,
}) {
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState('');
  const [transactionType, setTransactionType] = useState(initialType || 'CREDIT');
  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);

  useEffect(() => {
    let isMounted = true;
    if (!isOpen) return;

    getCustomers()
      .then((data) => {
        if (!isMounted) return;
        setCustomers(data);
        if (initialCustomer) {
          setCustomerId(initialCustomer.id.toString());
        } else if (data.length > 0) {
          setCustomerId(data[0].id.toString());
        }
      })
      .catch((err) => {
        console.warn('Failed to fetch customers list:', err);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, initialCustomer]);

  async function handleSubmit(e) {
    e.preventDefault();
    setFormError(null);

    const cId = parseInt(customerId, 10);
    const amt = parseInt(amount, 10);

    if (isNaN(cId) || cId <= 0) {
      setFormError('Please select a valid customer.');
      return;
    }

    if (isNaN(amt) || amt <= 0) {
      setFormError('Amount must be a positive number greater than zero.');
      return;
    }

    setIsSubmitting(true);
    try {
      const res = await createTransaction({
        customer_id: cId,
        transaction_type: transactionType,
        amount: amt,
        description: description.trim() || `Manual ${transactionType.toLowerCase()}`,
      });

      onNotification({
        type: 'success',
        message: `Successfully recorded ${transactionType} of ₹${amt} (Txn #${res.id})`,
      });

      if (onSuccess) onSuccess();
      onClose();
    } catch (err) {
      setFormError(err.message || 'Failed to save transaction');
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop">
      <div className="modal-container">
        <div className="modal-header">
          <h3 className="modal-title">
            {transactionType === 'CREDIT'
              ? '➕ ಉದ್ದಾರ ದಾಖಲಿಸಿ / Record Credit'
              : '📥 ಜಮಾ ದಾಖಲಿಸಿ / Record Payment'}
          </h3>
          <button type="button" className="modal-close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <form onSubmit={handleSubmit} className="modal-form">
          {formError && (
            <div className="form-error-alert">
              <span>⚠️ {formError}</span>
            </div>
          )}

          <div className="form-group">
            <label htmlFor="tx-customer-select">
              ಗ್ರಾಹಕರು / Customer <span className="required-star">*</span>
            </label>
            <select
              id="tx-customer-select"
              className="form-input"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              required
            >
              <option value="">-- ಗ್ರಾಹಕರನ್ನು ಆಯ್ಕೆ ಮಾಡಿ / Select Customer --</option>
              {customers.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} {c.phone ? `(${c.phone})` : ''} - #{c.id}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label>ಪ್ರಕಾರ / Transaction Type</label>
            <div className="txn-type-selector">
              <button
                type="button"
                className={`type-option-btn ${
                  transactionType === 'CREDIT' ? 'active-credit' : ''
                }`}
                onClick={() => setTransactionType('CREDIT')}
              >
                🔴 ಉದ್ದಾರ / Credit (+ Due)
              </button>
              <button
                type="button"
                className={`type-option-btn ${
                  transactionType === 'PAYMENT' ? 'active-payment' : ''
                }`}
                onClick={() => setTransactionType('PAYMENT')}
              >
                🟢 ಜಮಾ / Payment (- Due)
              </button>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="tx-amount-input">
              ಮೊತ್ತ / Amount (₹) <span className="required-star">*</span>
            </label>
            <div className="amount-input-group">
              <span className="rupee-symbol">₹</span>
              <input
                id="tx-amount-input"
                type="number"
                className="form-input amount-field"
                placeholder="0"
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                min="1"
                step="1"
                required
                autoFocus
              />
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="tx-desc-input">ವಿವರಣೆ / Description (ಐಚ್ಛಿಕ / Optional)</label>
            <input
              id="tx-desc-input"
              type="text"
              className="form-input"
              placeholder="ಉದಾ: ಅಕ್ಕಿ, ಎಣ್ಣೆ, ದಿನಸಿ..."
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              maxLength={255}
            />
          </div>

          <div className="modal-footer">
            <button
              type="button"
              className="secondary-btn"
              onClick={onClose}
              disabled={isSubmitting}
            >
              ರದ್ದು / Cancel
            </button>
            <button
              type="submit"
              className={`primary-btn ${
                transactionType === 'CREDIT' ? 'btn-save-credit' : 'btn-save-payment'
              }`}
              disabled={isSubmitting || !amount || !customerId}
            >
              {isSubmitting ? 'ದಾಖಲಾಗುತ್ತಿದೆ...' : 'ದಾಖಲಿಸಿ / Save to Ledger'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
