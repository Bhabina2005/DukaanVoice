export function Navbar({ activeTab, setActiveTab, backendStatus, speechInfo }) {
  return (
    <header className="app-header">
      <div className="header-container">
        <div className="brand-section">
          <div className="brand-logo">
            <span className="logo-icon">🏪</span>
            <div className="brand-text">
              <div className="brand-title-row">
                <h1 className="brand-title">DukaanVoice</h1>
                <span className="kannada-subtitle">ದೂಕಾನ್ ವಾಯ್ಸ್</span>
              </div>
              <p className="brand-tagline">Kirana Store Voice Credit & Payment Ledger</p>
            </div>
          </div>

          <div className="header-status-badges">
            <span
              className={`status-pill ${
                backendStatus === 'healthy' ? 'status-online' : 'status-offline'
              }`}
              title="FastAPI + SQLite backend connectivity"
            >
              <span className="status-dot"></span>
              {backendStatus === 'healthy' ? 'FastAPI Connected' : 'Connecting to Backend...'}
            </span>

            <span className="status-pill speech-provider-pill" title={speechInfo.gnaniStatusNote}>
              <span className="mic-icon">🎙️</span>
              <span className="pill-text">
                {speechInfo.providerName}
              </span>
            </span>
          </div>
        </div>

        <nav className="nav-tabs" aria-label="Main Navigation">
          <button
            type="button"
            className={`nav-tab-btn ${activeTab === 'voice' ? 'active' : ''}`}
            onClick={() => setActiveTab('voice')}
          >
            <span className="tab-icon">🎙️</span>
            <span className="tab-title">ಧ್ವನಿ ಸಹಾಯಕ / Voice</span>
          </button>

          <button
            type="button"
            className={`nav-tab-btn ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <span className="tab-icon">📊</span>
            <span className="tab-title">ಡ್ಯಾಶ್‌ಬೋರ್ಡ್ / Dashboard</span>
          </button>

          <button
            type="button"
            className={`nav-tab-btn ${activeTab === 'customers' ? 'active' : ''}`}
            onClick={() => setActiveTab('customers')}
          >
            <span className="tab-icon">👥</span>
            <span className="tab-title">ಗ್ರಾಹಕರು / Customers</span>
          </button>

          <button
            type="button"
            className={`nav-tab-btn ${activeTab === 'ledger' ? 'active' : ''}`}
            onClick={() => setActiveTab('ledger')}
          >
            <span className="tab-icon">📖</span>
            <span className="tab-title">ಲೆಡ್ಜರ್ / Ledger</span>
          </button>
        </nav>
      </div>
    </header>
  );
}
