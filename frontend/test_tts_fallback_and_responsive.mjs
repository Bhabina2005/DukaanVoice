// Phase 1.4 Stage E: Comprehensive TTS Provider Fallback & Mobile Responsive UI Test Suite
// Executed with Node.js native test runner: node --test frontend/test_tts_fallback_and_responsive.mjs

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { SpeechProviderService } from './src/services/speechService.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Mock helper to set up browser-like environment for Node.js
function setupMockBrowserEnv({
  synthVoices = [
    { name: 'Google Kannada', lang: 'kn-IN' },
    { name: 'Google English', lang: 'en-IN' },
  ],
  isSynthSupported = true,
} = {}) {
  const originalWindow = globalThis.window;
  const originalFetch = globalThis.fetch;
  const originalAudio = globalThis.Audio;
  const originalURL = globalThis.URL;
  const originalSpeechSynthesisUtterance = globalThis.SpeechSynthesisUtterance;

  const revokedUrls = [];
  const createdUrls = [];
  const audioInstances = [];
  const synthSpoken = [];

  class MockAudio {
    constructor(src) {
      this.src = src;
      this.onplay = null;
      this.onended = null;
      this.onerror = null;
      this.paused = true;
      audioInstances.push(this);
    }
    async play() {
      this.paused = false;
      if (this.onplay) this.onplay();
      return Promise.resolve();
    }
    pause() {
      this.paused = true;
    }
  }

  const mockURL = class extends originalURL {
    static createObjectURL(blob) {
      const url = `blob:mock-audio-${Math.random().toString(36).substring(2)}`;
      createdUrls.push({ url, blob });
      return url;
    }
    static revokeObjectURL(url) {
      revokedUrls.push(url);
    }
  };

  class MockUtterance {
    constructor(text) {
      this.text = text;
      this.lang = 'kn-IN';
      this.voice = null;
      this.rate = 1.0;
      this.pitch = 1.0;
      this.onstart = null;
      this.onend = null;
      this.onerror = null;
    }
  }

  const mockSynth = isSynthSupported
    ? {
        speaking: false,
        canceled: false,
        getVoices() {
          return synthVoices;
        },
        speak(utterance) {
          synthSpoken.push(utterance);
          this.speaking = true;
          if (utterance.onstart) utterance.onstart();
          // Simulate speech end asynchronously
          setTimeout(() => {
            this.speaking = false;
            if (utterance.onend) utterance.onend();
          }, 10);
        },
        cancel() {
          this.canceled = true;
          this.speaking = false;
        },
      }
    : null;

  const defaultFetch = async (url) => {
    if (typeof url === 'string' && url.includes('provider-status')) {
      return {
        ok: true,
        status: 200,
        json: async () => ({ is_configured: false }),
      };
    }
    return { ok: false, status: 404, json: async () => ({}) };
  };

  globalThis.Audio = MockAudio;
  globalThis.URL = mockURL;
  globalThis.SpeechSynthesisUtterance = MockUtterance;
  globalThis.fetch = defaultFetch;
  globalThis.window = {
    Audio: MockAudio,
    URL: mockURL,
    speechSynthesis: mockSynth,
    fetch: defaultFetch,
  };

  return {
    cleanup() {
      globalThis.window = originalWindow;
      globalThis.fetch = originalFetch;
      globalThis.Audio = originalAudio;
      globalThis.URL = originalURL;
      globalThis.SpeechSynthesisUtterance = originalSpeechSynthesisUtterance;
    },
    revokedUrls,
    createdUrls,
    audioInstances,
    synthSpoken,
    mockSynth,
  };
}

// ---------------------------------------------------------------------------
// 1. Gnani TTS Success
// ---------------------------------------------------------------------------
test('1. Gnani TTS Success: Synthesizes via Gnani Timbre v3.0 and triggers onProviderUsed without fallback', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;
    service.gnaniProviderInfo = { tts_model: 'timbre-v3.0', tts_voice: 'Shivani' };

    // Mock fetch to return valid audio/wav blob
    const dummyBlob = new Blob([new Uint8Array(500)], { type: 'audio/wav' });
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      blob: async () => dummyBlob,
    });

    let providerReported = null;
    let started = false;

    await service.speak('ರಮೇಶ್ ಅವರಿಗೆ ₹500 ಉದ್ದಾರ', {
      language: 'kn-IN',
      onStart: () => {
        started = true;
      },
      onProviderUsed: (info) => {
        providerReported = info;
      },
    });

    assert.ok(started, 'onStart callback should be triggered');
    assert.ok(providerReported, 'onProviderUsed should be called');
    assert.equal(providerReported.provider, 'Gnani Timbre v3.0');
    assert.equal(providerReported.isFallback, false);
    assert.equal(providerReported.model, 'timbre-v3.0');
    assert.equal(providerReported.voice, 'Shivani');
    assert.equal(env.audioInstances.length, 1, 'HTMLAudioElement should be created');
    assert.equal(env.synthSpoken.length, 0, 'Browser synthesis should not be called');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 2. Browser TTS Fallback on Missing Credentials
// ---------------------------------------------------------------------------
test('2. Browser TTS Fallback on Missing Credentials: Falls back to SpeechSynthesis gracefully', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = false; // Not configured

    let providerReported = null;
    let ended = false;

    await service.speak('Transaction recorded successfully', {
      language: 'en-IN',
      onProviderUsed: (info) => {
        providerReported = info;
      },
      onEnd: () => {
        ended = true;
      },
    });

    assert.ok(providerReported);
    assert.equal(providerReported.provider, 'Browser SpeechSynthesis');
    assert.equal(providerReported.isFallback, true);
    assert.ok(providerReported.fallbackReason.includes('not configured'));
    assert.equal(env.synthSpoken.length, 1);
    assert.equal(env.synthSpoken[0].text, 'Transaction recorded successfully');
    assert.equal(env.synthSpoken[0].voice?.name, 'Google English');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 3. Browser TTS Fallback on Invalid Credentials (HTTP 401)
// ---------------------------------------------------------------------------
test('3. Browser TTS Fallback on Invalid Credentials (HTTP 401): Activates fallback with reason', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    // Mock fetch returning HTTP 401 Unauthorized
    globalThis.fetch = async () => ({
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'Invalid or expired API Key' }),
    });

    let fallbackNotice = null;
    let providerReported = null;

    await service.speak('ಖಾತೆ ಅಪ್ಡೇಟ್ ಆಗಿದೆ', {
      language: 'kn-IN',
      onFallback: (info) => {
        fallbackNotice = info;
      },
      onProviderUsed: (info) => {
        providerReported = info;
      },
    });

    assert.ok(fallbackNotice, 'onFallback callback should be notified');
    assert.equal(fallbackNotice.fromProvider, 'Gnani Timbre v3.0');
    assert.equal(fallbackNotice.toProvider, 'Browser SpeechSynthesis');
    assert.equal(fallbackNotice.status, 401);

    assert.ok(providerReported);
    assert.equal(providerReported.provider, 'Browser SpeechSynthesis');
    assert.equal(providerReported.isFallback, true);
    assert.equal(env.synthSpoken.length, 1);
    assert.equal(env.synthSpoken[0].text, 'ಖಾತೆ ಅಪ್ಡೇಟ್ ಆಗಿದೆ');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 4. Browser TTS Fallback on Network Timeout (HTTP 504)
// ---------------------------------------------------------------------------
test('4. Browser TTS Fallback on Network Timeout (HTTP 504): Recovers without application crash', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    globalThis.fetch = async () => ({
      ok: false,
      status: 504,
      statusText: 'Gateway Timeout',
      json: async () => ({ detail: 'Gnani Timbre TTS timed out' }),
    });

    let fallbackNotice = null;
    await service.speak('Timeout recovery message', {
      language: 'en-IN',
      onFallback: (info) => {
        fallbackNotice = info;
      },
    });

    assert.ok(fallbackNotice);
    assert.equal(fallbackNotice.status, 504);
    assert.equal(env.synthSpoken.length, 1);
    assert.equal(env.synthSpoken[0].text, 'Timeout recovery message');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 5. Browser TTS Fallback on Provider Failure (HTTP 500 / 502 / 503)
// ---------------------------------------------------------------------------
test('5. Browser TTS Fallback on Provider Failure: Handles 502 Bad Gateway seamlessly', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    globalThis.fetch = async () => ({
      ok: false,
      status: 502,
      statusText: 'Bad Gateway',
      json: async () => ({ detail: 'Gnani service temporarily unreachable' }),
    });

    let fallbackNotice = null;
    await service.speak('Server error recovery', {
      language: 'en-IN',
      onFallback: (info) => {
        fallbackNotice = info;
      },
    });

    assert.ok(fallbackNotice);
    assert.equal(fallbackNotice.status, 502);
    assert.equal(env.synthSpoken.length, 1);
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 6. Empty and Invalid Audio Handling
// ---------------------------------------------------------------------------
test('6. Empty and Invalid Audio Handling: Empty string returns immediately without invoking synthesis', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    let fetchCalled = false;
    globalThis.fetch = async () => {
      fetchCalled = true;
      return { ok: true, blob: async () => new Blob([new Uint8Array(200)]) };
    };

    let endedReason = null;
    await service.speak('', {
      onEnd: ({ reason }) => {
        endedReason = reason;
      },
    });
    await service.speak('   ', {
      onEnd: ({ reason }) => {
        endedReason = reason;
      },
    });

    assert.equal(fetchCalled, false, 'Fetch should not be called for empty string');
    assert.equal(env.synthSpoken.length, 0, 'Browser synthesis should not be called for empty string');
    assert.equal(endedReason, 'empty_text');
  } finally {
    env.cleanup();
  }
});

test('6b. Empty Audio Blob from Provider: Triggers fallback to Browser SpeechSynthesis', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    // Provider returns empty blob (0 bytes)
    globalThis.fetch = async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob([], { type: 'audio/wav' }),
    });

    let fallbackCalled = false;
    await service.speak('Valid text with empty audio response', {
      language: 'en-IN',
      onFallback: () => {
        fallbackCalled = true;
      },
    });

    assert.ok(fallbackCalled, 'Fallback should trigger when audio blob is empty');
    assert.equal(env.synthSpoken.length, 1, 'Should fall back to browser speech synthesis');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 7. Kannada and English Language Voice Matching
// ---------------------------------------------------------------------------
test('7. Kannada and English Voice Matching: Selects appropriate regional voice', async () => {
  const env = setupMockBrowserEnv({
    synthVoices: [
      { name: 'Google Kannada Voice', lang: 'kn-IN' },
      { name: 'Google English India', lang: 'en-IN' },
    ],
  });
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = false;

    // Test Kannada
    await service.speak('ನಮಸ್ಕಾರ', { language: 'kn-IN' });
    assert.equal(env.synthSpoken[0].voice?.name, 'Google Kannada Voice');

    // Test English
    await service.speak('Hello store owner', { language: 'en-IN' });
    assert.equal(env.synthSpoken[1].voice?.name, 'Google English India');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 8. Stop and Replay Controls State
// ---------------------------------------------------------------------------
test('8. Stop and Replay Controls: stopSpeaking immediately halts audio and clears active state', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    globalThis.fetch = async () => ({
      ok: true,
      blob: async () => new Blob([new Uint8Array(400)], { type: 'audio/wav' }),
    });

    await service.speak('Playing speech that will be stopped');
    assert.equal(service.isSpeaking, true);
    assert.equal(service.activePlaybackProvider, 'Gnani Timbre v3.0');

    // Call stopSpeaking
    service.stopSpeaking();
    assert.equal(service.isSpeaking, false);
    assert.equal(service.activePlaybackProvider, null);
    assert.equal(env.audioInstances[0].paused, true, 'Audio element must be paused');
    assert.equal(env.mockSynth.canceled, true, 'SpeechSynthesis cancel must be called');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 9. Duplicate Playback Prevention (Race Condition)
// ---------------------------------------------------------------------------
test('9. Duplicate Playback Prevention: Superseded in-flight request is discarded when newer speak starts', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    let resolveFirstFetch;
    const firstPromise = new Promise((resolve) => {
      resolveFirstFetch = resolve;
    });

    let fetchCount = 0;
    globalThis.fetch = async (url, opts) => {
      fetchCount++;
      const body = JSON.parse(opts.body);
      if (body.text === 'First request') {
        await firstPromise; // Stalls first request
        return { ok: true, blob: async () => new Blob([new Uint8Array(400)], { type: 'audio/wav' }) };
      }
      return { ok: true, blob: async () => new Blob([new Uint8Array(500)], { type: 'audio/wav' }) };
    };

    // Start first speak (in-flight)
    const p1 = service.speak('First request');

    // Immediately start second speak
    const p2 = service.speak('Second request');

    // Resolve first fetch after second request has started
    resolveFirstFetch();
    await Promise.all([p1, p2]);

    // Only 1 Audio instance should be created and played (the second one)
    assert.equal(env.audioInstances.length, 1, 'Only the active second request should create an Audio player');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 10. Audio Resource Cleanup
// ---------------------------------------------------------------------------
test('10. Audio Resource Cleanup: releaseActiveAudio revokes object URL and detaches handlers', async () => {
  const env = setupMockBrowserEnv();
  try {
    const service = new SpeechProviderService();
    service.isGnaniConfigured = true;

    globalThis.fetch = async () => ({
      ok: true,
      blob: async () => new Blob([new Uint8Array(300)], { type: 'audio/wav' }),
    });

    await service.speak('Cleanup test audio');
    const createdUrl = env.createdUrls[0].url;

    service.releaseActiveAudio();

    assert.ok(env.revokedUrls.includes(createdUrl), 'URL.revokeObjectURL must be called with active URL');
    assert.equal(service.activeAudioElement, null, 'Active audio element reference must be cleared');
    assert.equal(service.activeAudioUrl, null, 'Active URL reference must be cleared');
  } finally {
    env.cleanup();
  }
});

// ---------------------------------------------------------------------------
// 11. Mobile Responsive Layout & Media Query Validation
// ---------------------------------------------------------------------------
test('11. Mobile Responsive Layout: CSS contains verified rules for 320px, 375px, 390px, 430px, 768px, 1024px', () => {
  const cssPath = path.resolve(__dirname, 'src/App.css');
  const cssContent = fs.readFileSync(cssPath, 'utf8');

  // Verify responsive media query breakpoints
  assert.ok(cssContent.includes('@media (max-width: 375px)'), 'Break-point for narrow viewports (320px and 375px) must exist');
  assert.ok(cssContent.includes('@media (max-width: 600px)'), 'Break-point for standard mobile (390px, 430px) must exist');
  assert.ok(cssContent.includes('@media (max-width: 768px)'), 'Break-point for tablets (768px) must exist');
  assert.ok(cssContent.includes('@media (max-width: 992px)'), 'Break-point for medium screens must exist');

  // Verify mobile optimization requirements
  assert.ok(cssContent.includes('-webkit-overflow-scrolling: touch'), 'Touch scrolling on tables/nav must be enabled');
  assert.ok(cssContent.includes('font-size: 16px'), 'Input font-size 16px to prevent iOS Safari zoom');
  assert.ok(cssContent.includes('overflow-wrap: break-word'), 'Kannada text must have word-break to prevent overflow');
  assert.ok(cssContent.includes('min-height: 44px') || cssContent.includes('min-height: 48px'), 'Touch targets minimum 44px/48px');

  // Verify confirmation card preview vertical flow on mobile
  assert.ok(cssContent.includes('.preview-arrow'), 'Preview directional indicator must exist');
  assert.ok(cssContent.includes('transform: rotate(90deg)'), 'Arrow must rotate vertically on mobile viewports');

  // Verify audio controls classes
  assert.ok(cssContent.includes('.chat-audio-controls-row'), 'Audio controls row class must be defined');
  assert.ok(cssContent.includes('.btn-stop-audio'), 'Stop audio button styling must be defined');
  assert.ok(cssContent.includes('.tts-provider-tag'), 'TTS provider badge styling must be defined');
  assert.ok(cssContent.includes('.tag-gnani'), 'Gnani tag styling must be defined');
  assert.ok(cssContent.includes('.tag-browser'), 'Browser tag styling must be defined');
});

// ---------------------------------------------------------------------------
// 12. Component Audio Controls & Provider Tagging Integration
// ---------------------------------------------------------------------------
test('12. Component Audio Controls Integration: VoiceAssistant exports stop/play controls and provider tags', () => {
  const vaPath = path.resolve(__dirname, 'src/components/VoiceAssistant.jsx');
  const vaContent = fs.readFileSync(vaPath, 'utf8');

  assert.ok(vaContent.includes('playingMessageId'), 'VoiceAssistant must track active playing message state');
  assert.ok(vaContent.includes('btn-stop-audio'), 'VoiceAssistant must render stop audio button during playback');
  assert.ok(vaContent.includes('tts-provider-tag'), 'VoiceAssistant must render provider tag (Gnani vs Browser)');
  assert.ok(vaContent.includes('handleReplayAudio'), 'VoiceAssistant must handle stop and replay controls');
  assert.ok(vaContent.includes('speechService.stopSpeaking()'), 'VoiceAssistant must stop speaking on unmount / toggle');
});

// ---------------------------------------------------------------------------
// 13. App Navigation Audio Cleanup
// ---------------------------------------------------------------------------
test('13. App Navigation Audio Cleanup: App.jsx stops audio playback on tab navigation', () => {
  const appPath = path.resolve(__dirname, 'src/App.jsx');
  const appContent = fs.readFileSync(appPath, 'utf8');

  assert.ok(appContent.includes('handleTabChange'), 'App.jsx must use handleTabChange to prevent overlapping audio across tabs');
  assert.ok(appContent.includes('speechService.stopSpeaking()'), 'App.jsx must call stopSpeaking on navigation');
});
