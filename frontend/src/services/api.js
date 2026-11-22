const API_BASE_URL =
  (typeof import.meta !== 'undefined' && import.meta?.env?.VITE_API_BASE_URL) ||
  'http://localhost:8000';

export function isTransientError(error) {
  if (!error) return false;
  if (typeof error.status === 'number') {
    // 408 Request Timeout, 502 Bad Gateway, 503 Service Unavailable, 504 Gateway Timeout
    return error.status === 408 || (error.status >= 502 && error.status <= 504);
  }
  const msg = (error.message || '').toLowerCase();
  return (
    msg.includes('failed to fetch') ||
    msg.includes('networkerror') ||
    msg.includes('fetch failed') ||
    msg.includes('network request failed') ||
    msg.includes('econnrefused') ||
    msg.includes('econnreset') ||
    msg.includes('etimedout') ||
    msg.includes('timeout')
  );
}

export async function requestWithRetry(
  requestFn,
  { maxRetries = 2, initialDelayMs = 500, onRetry } = {}
) {
  let attempt = 0;
  while (true) {
    try {
      return await requestFn();
    } catch (error) {
      attempt++;
      // Never retry permanent errors (e.g. 400 bad request, 401 unauthorized, 422 unprocessable)
      if (attempt > maxRetries || !isTransientError(error)) {
        throw error;
      }
      const delay = initialDelayMs * Math.pow(2, attempt - 1);
      if (onRetry) {
        onRetry({ attempt, maxRetries, delay, error });
      }
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }
}

async function request(endpoint, options = {}) {
  const url = `${API_BASE_URL}${endpoint}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  try {
    const response = await fetch(url, config);
    if (!response.ok) {
      let errorData;
      try {
        errorData = await response.json();
      } catch {
        errorData = { detail: `HTTP error ${response.status}: ${response.statusText}` };
      }
      const message = errorData.detail || errorData.message || 'API request failed';
      const err = new Error(typeof message === 'string' ? message : JSON.stringify(message));
      err.status = response.status;
      throw err;
    }
    return await response.json();
  } catch (error) {
    console.error(`API Error on ${endpoint}:`, error);
    throw error;
  }
}

// Dashboard APIs
export async function getDashboardStats() {
  return await request('/api/transactions/stats');
}

export async function getRecentTransactions(limit = 20) {
  return await request(`/api/transactions/recent?limit=${limit}`);
}

// Customers APIs
export async function getCustomers(search = '') {
  const query = search ? `?search=${encodeURIComponent(search)}` : '';
  return await request(`/api/customers/${query}`);
}

export async function getCustomersSummary(search = '') {
  const query = search ? `?search=${encodeURIComponent(search)}` : '';
  return await request(`/api/customers/summary${query}`);
}

export async function getCustomer(id) {
  return await request(`/api/customers/${id}`);
}

export async function getCustomerBalance(id) {
  return await request(`/api/transactions/customer/${id}/balance`);
}

export async function getCustomerTransactions(id) {
  return await request(`/api/transactions/customer/${id}`);
}

export async function createCustomer(customerData) {
  return await request('/api/customers/', {
    method: 'POST',
    body: JSON.stringify(customerData),
  });
}

// Transactions APIs
export async function createTransaction(transactionData) {
  return await request('/api/transactions/', {
    method: 'POST',
    body: JSON.stringify(transactionData),
  });
}

// Voice Assistant APIs
export async function processVoiceCommand(
  transcript,
  sessionId = 'default',
  retryOptions = {}
) {
  return await requestWithRetry(
    () =>
      request('/api/voice/process', {
        method: 'POST',
        body: JSON.stringify({
          transcript,
          session_id: sessionId,
        }),
      }),
    retryOptions
  );
}

export async function confirmVoiceTransaction(pendingId, sessionId = 'default', expectedBaseline = null) {
  const body = {
    pending_id: pendingId,
    session_id: sessionId,
  };
  if (expectedBaseline !== null && expectedBaseline !== undefined) {
    body.expected_baseline = expectedBaseline;
  }
  return await request('/api/voice/confirm', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function cancelVoiceTransaction(pendingId, sessionId = 'default') {
  return await request('/api/voice/cancel', {
    method: 'POST',
    body: JSON.stringify({
      pending_id: pendingId,
      session_id: sessionId,
    }),
  });
}

export async function correctVoiceTransaction(pendingId, correctionData, sessionId = 'default') {
  return await request('/api/voice/correct', {
    method: 'POST',
    body: JSON.stringify({
      pending_id: pendingId,
      session_id: sessionId,
      ...correctionData,
    }),
  });
}

export async function getPendingVoiceStatus(sessionId = 'default') {
  return await request(`/api/voice/pending?session_id=${encodeURIComponent(sessionId)}`);
}

export async function checkBackendHealth() {
  return await request('/health');
}

// Gnani Voice AI (Prisma v3.0 STT & Timbre v3.0 TTS) APIs
export async function getSpeechProviderStatus() {
  return await request('/api/voice/provider-status');
}

export async function transcribeAudio(
  audioBase64,
  format = 'webm',
  language = 'kn-IN',
  retryOptions = {}
) {
  return await requestWithRetry(
    () =>
      request('/api/voice/transcribe', {
        method: 'POST',
        body: JSON.stringify({
          audio_base64: audioBase64,
          format,
          language,
        }),
      }),
    retryOptions
  );
}

export async function synthesizeSpeech(text, language = 'kn-IN') {
  const url = `${API_BASE_URL}/api/voice/tts`;
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text, language }),
  });
  if (!response.ok) {
    let errorDetail = '';
    try {
      const errJson = await response.json();
      errorDetail = errJson.detail || '';
    } catch {
      // response body is not JSON
    }
    const err = new Error(errorDetail || `TTS synthesis failed with status ${response.status}`);
    err.status = response.status;
    err.statusText = response.statusText;
    throw err;
  }
  return await response.blob();
}

export async function sendAudioVoiceCommand(audioBase64, sessionId = 'default', format = 'webm', language = 'kn-IN') {
  return await request('/api/voice/audio-command', {
    method: 'POST',
    body: JSON.stringify({
      audio_base64: audioBase64,
      session_id: sessionId,
      format,
      language,
    }),
  });
}
