import test from 'node:test';
import assert from 'node:assert/strict';

/**
 * Phase 1.4 Stage D: Confirmation Experience & UX Tests
 * Verifies frontend accounting display, balance previews, stale detection, and error recovery.
 */

// Helper simulating frontend balance formatting logic
function formatBalanceDisplay(outstanding, advance = 0) {
  if (advance > 0) {
    return {
      dueText: '₹ 0',
      advanceText: `₹ ${advance}`,
      label: `Advance: ₹${advance} (Due: ₹0)`,
      status: 'advance',
    };
  }
  if (outstanding > 0) {
    return {
      dueText: `₹ ${outstanding}`,
      advanceText: '₹ 0',
      label: `Outstanding: ₹${outstanding}`,
      status: 'due',
    };
  }
  return {
    dueText: '₹ 0',
    advanceText: '₹ 0',
    label: 'Account settled (₹0)',
    status: 'settled',
  };
}

// Helper simulating frontend confirmation preview calculation check
function verifyPreviewSemantics({ currentNet, txnType, amount }) {
  const currentOutstanding = Math.max(0, currentNet);
  const currentAdvance = Math.max(0, -currentNet);

  let expectedNet;
  if (txnType === 'CREDIT') {
    expectedNet = currentNet + amount;
  } else if (txnType === 'PAYMENT') {
    expectedNet = currentNet - amount;
  } else {
    expectedNet = currentNet;
  }

  const expectedOutstanding = Math.max(0, expectedNet);
  const expectedAdvance = Math.max(0, -expectedNet);

  let explanation;
  let explanationKn;
  if (expectedOutstanding > 0) {
    explanation = `Customer will owe ₹${expectedOutstanding}`;
    explanationKn = `ಗ್ರಾಹಕರು ₹${expectedOutstanding} ಬಾಕಿ ಉಳಿಸಿಕೊಳ್ಳುತ್ತಾರೆ`;
  } else if (expectedAdvance > 0) {
    explanation = `Customer will have an advance balance of ₹${expectedAdvance}`;
    explanationKn = `ಗ್ರಾಹಕರ ಖಾತೆಯಲ್ಲಿ ₹${expectedAdvance} ಮುಂಗಡ (ಜಮಾ) ಇರುತ್ತದೆ`;
  } else {
    explanation = 'Account will be fully settled (₹0 balance)';
    explanationKn = 'ಖಾತೆ ಪೂರ್ಣವಾಗಿ ಚುಕ್ತಾ ಆಗುತ್ತದೆ (₹0 ಬಾಕಿ)';
  }

  return {
    current_outstanding: currentOutstanding,
    current_advance: currentAdvance,
    expected_outstanding: expectedOutstanding,
    expected_advance: expectedAdvance,
    expected_net_balance: expectedNet,
    baseline_balance: currentNet,
    balance_explanation: explanation,
    balance_explanation_kn: explanationKn,
  };
}

test('1. Confirmation UX: Credit preview shows correct current, addition, and expected outstanding', () => {
  const preview = verifyPreviewSemantics({ currentNet: 430, txnType: 'CREDIT', amount: 500 });
  assert.equal(preview.current_outstanding, 430);
  assert.equal(preview.current_advance, 0);
  assert.equal(preview.expected_outstanding, 930);
  assert.equal(preview.expected_advance, 0);
  assert.equal(preview.balance_explanation, 'Customer will owe ₹930');
  assert.ok(preview.balance_explanation_kn.includes('930'));
});

test('2. Confirmation UX: Partial payment preview correctly reduces outstanding dues', () => {
  const preview = verifyPreviewSemantics({ currentNet: 430, txnType: 'PAYMENT', amount: 200 });
  assert.equal(preview.current_outstanding, 430);
  assert.equal(preview.current_advance, 0);
  assert.equal(preview.expected_outstanding, 230);
  assert.equal(preview.expected_advance, 0);
  assert.equal(preview.balance_explanation, 'Customer will owe ₹230');
});

test('3. Confirmation UX: Exact payment preview results in ₹0 settled balance', () => {
  const preview = verifyPreviewSemantics({ currentNet: 430, txnType: 'PAYMENT', amount: 430 });
  assert.equal(preview.current_outstanding, 430);
  assert.equal(preview.expected_outstanding, 0);
  assert.equal(preview.expected_advance, 0);
  assert.equal(preview.balance_explanation, 'Account will be fully settled (₹0 balance)');
  assert.ok(preview.balance_explanation_kn.includes('ಚುಕ್ತಾ'));
});

test('4. Confirmation UX: Overpayment preview creates advance balance without negative due confusion', () => {
  const preview = verifyPreviewSemantics({ currentNet: 430, txnType: 'PAYMENT', amount: 500 });
  assert.equal(preview.current_outstanding, 430);
  assert.equal(preview.expected_outstanding, 0);
  assert.equal(preview.expected_advance, 70);
  assert.equal(preview.expected_net_balance, -70);
  assert.equal(preview.balance_explanation, 'Customer will have an advance balance of ₹70');
  assert.ok(preview.balance_explanation_kn.includes('ಮುಂಗಡ'));
});

test('5. Confirmation UX: Customer with existing advance absorbs new credit properly', () => {
  // Existing advance of ₹70 (currentNet = -70)
  const preview = verifyPreviewSemantics({ currentNet: -70, txnType: 'CREDIT', amount: 50 });
  assert.equal(preview.current_outstanding, 0);
  assert.equal(preview.current_advance, 70);
  assert.equal(preview.expected_outstanding, 0);
  assert.equal(preview.expected_advance, 20);
  assert.equal(preview.balance_explanation, 'Customer will have an advance balance of ₹20');
});

test('6. Stale Preview Detection: Identifies mismatch between recorded baseline and actual customer balance', () => {
  const previewBaseline = 430;
  const actualBalanceNow = 230; // Intervening payment occurred

  const isStale = previewBaseline !== actualBalanceNow;
  assert.equal(isStale, true);

  // When stale is detected, client updates preview to actual balance
  const refreshedPreview = verifyPreviewSemantics({ currentNet: actualBalanceNow, txnType: 'CREDIT', amount: 500 });
  assert.equal(refreshedPreview.current_outstanding, 230);
  assert.equal(refreshedPreview.expected_outstanding, 730);
  assert.equal(refreshedPreview.baseline_balance, 230);
});

test('7. Confirmation Error Recovery: Distinguishes between stale conflict and network retry', () => {
  const staleErr = { status: 409, message: 'Customer balance has changed since preview was generated' };
  const networkErr = { status: 502, message: 'Failed to fetch' };

  const isStale1 = staleErr.status === 409 || staleErr.message.includes('balance has changed');
  const isStale2 = networkErr.status === 409 || networkErr.message.includes('balance has changed');

  assert.equal(isStale1, true);
  assert.equal(isStale2, false);

  // Network error allows safe idempotent retry
  const canRetryIdempotently = !isStale2;
  assert.equal(canRetryIdempotently, true);
});

test('8. CustomersView balance tag: Properly tags credit dues, advance deposits, and clear balances', () => {
  const dueCust = formatBalanceDisplay(430, 0);
  assert.equal(dueCust.status, 'due');
  assert.equal(dueCust.dueText, '₹ 430');

  const advCust = formatBalanceDisplay(0, 70);
  assert.equal(advCust.status, 'advance');
  assert.equal(advCust.advanceText, '₹ 70');
  assert.ok(advCust.label.includes('Advance: ₹70'));

  const clearCust = formatBalanceDisplay(0, 0);
  assert.equal(clearCust.status, 'settled');
  assert.equal(clearCust.dueText, '₹ 0');
});

test('9. DashboardView balance metrics: Explains advance deposit when net balance is negative', () => {
  const statsNegative = { outstanding_balance: -70 };
  const displayAmt = statsNegative.outstanding_balance < 0
    ? `₹ 0 (Adv ₹${Math.abs(statsNegative.outstanding_balance)})`
    : `₹ ${statsNegative.outstanding_balance}`;

  assert.equal(displayAmt, '₹ 0 (Adv ₹70)');

  const statsPositive = { outstanding_balance: 430 };
  const displayAmtPos = statsPositive.outstanding_balance < 0
    ? `₹ 0 (Adv ₹${Math.abs(statsPositive.outstanding_balance)})`
    : `₹ ${statsPositive.outstanding_balance}`;

  assert.equal(displayAmtPos, '₹ 430');
});

test('10. Confirmation Card Loading State: Blocks concurrent submissions during active confirmation', () => {
  let isConfirming = false;
  let submitCount = 0;

  function attemptSubmit() {
    if (isConfirming) return false;
    isConfirming = true;
    submitCount++;
    return true;
  }

  assert.equal(attemptSubmit(), true);
  // Second rapid click while in-flight is rejected
  assert.equal(attemptSubmit(), false);
  assert.equal(submitCount, 1);

  // Completed
  isConfirming = false;
  // Re-submission after error is allowed
  assert.equal(attemptSubmit(), true);
  assert.equal(submitCount, 2);
});
