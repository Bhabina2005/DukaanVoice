import { useState, useEffect, useCallback } from 'react';
import { Navbar } from './components/Navbar';
import { VoiceAssistant } from './components/VoiceAssistant';
import { DashboardView } from './components/DashboardView';
import { CustomersView } from './components/CustomersView';
import { LedgerView } from './components/LedgerView';
import { TransactionModal } from './components/TransactionModal';
import { Toast } from './components/Toast';
import { checkBackendHealth } from './services/api';
import { speechService } from './services/speechService';
import './App.css';

export function App() {
  const [activeTab, setActiveTab] = useState('voice');
  const [backendStatus, setBackendStatus] = useState('checking');
  const speechInfo = speechService.getProviderInfo();
  const [notification, setNotification] = useState(null);

  // Manual Transaction Modal State
  const [isTxnModalOpen, setIsTxnModalOpen] = useState(false);
  const [txnModalCustomer, setTxnModalCustomer] = useState(null);
  const [txnModalType, setTxnModalType] = useState('CREDIT');

  // New Customer Modal State (shared trigger)
  const [newCustomerModalOpen, setNewCustomerModalOpen] = useState(false);

  // Key to trigger reloads across views
  const [dataVersion, setDataVersion] = useState(0);

  const verifyBackend = useCallback(async () => {
    try {
      const res = await checkBackendHealth();
      if (res.status === 'healthy') {
        setBackendStatus('healthy');
      } else {
        setBackendStatus('error');
      }
    } catch {
      setBackendStatus('error');
    }
  }, []);

  useEffect(() => {
    let active = true;
    checkBackendHealth()
      .then((res) => {
        if (active) {
          setBackendStatus(res.status === 'healthy' ? 'healthy' : 'error');
        }
      })
      .catch(() => {
        if (active) {
          setBackendStatus('error');
        }
      });

    const interval = setInterval(verifyBackend, 15000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [verifyBackend]);

  const showNotification = useCallback((notif) => {
    setNotification(notif);
  }, []);

  const handleTransactionSaved = useCallback(() => {
    setDataVersion((v) => v + 1);
  }, []);

  const handleTabChange = useCallback((newTab) => {
    // Stop any ongoing speech or microphone recording when navigating across tabs
    speechService.stopSpeaking();
    speechService.cancelListening();
    setActiveTab(newTab);
  }, []);

  const handleOpenRecordTransaction = (customer = null, type = 'CREDIT') => {
    speechService.stopSpeaking();
    setTxnModalCustomer(customer);
    setTxnModalType(type);
    setIsTxnModalOpen(true);
  };

  const handleOpenNewCustomer = () => {
    handleTabChange('customers');
    setNewCustomerModalOpen(true);
  };

  return (
    <div className="dukaan-app-root">
      <Navbar
        activeTab={activeTab}
        setActiveTab={handleTabChange}
        backendStatus={backendStatus}
        speechInfo={speechInfo}
      />

      <main className="main-content-container">
        {activeTab === 'voice' && (
          <VoiceAssistant
            onTransactionSaved={handleTransactionSaved}
            onNotification={showNotification}
          />
        )}

        {activeTab === 'dashboard' && (
          <DashboardView
            key={`dash-${dataVersion}`}
            onSelectTab={handleTabChange}
            onOpenNewCustomer={handleOpenNewCustomer}
            onRecordTransaction={handleOpenRecordTransaction}
          />
        )}

        {activeTab === 'customers' && (
          <CustomersView
            key={`cust-${dataVersion}`}
            onRecordTransaction={handleOpenRecordTransaction}
            newCustomerModalOpen={newCustomerModalOpen}
            setNewCustomerModalOpen={setNewCustomerModalOpen}
            onNotification={showNotification}
          />
        )}

        {activeTab === 'ledger' && (
          <LedgerView
            key={`ledger-${dataVersion}`}
            onRecordTransaction={handleOpenRecordTransaction}
          />
        )}
      </main>

      {/* Transaction Entry Modal */}
      <TransactionModal
        key={`modal-${isTxnModalOpen}-${txnModalType}-${txnModalCustomer?.id || 0}`}
        isOpen={isTxnModalOpen}
        onClose={() => setIsTxnModalOpen(false)}
        initialCustomer={txnModalCustomer}
        initialType={txnModalType}
        onSuccess={handleTransactionSaved}
        onNotification={showNotification}
      />

      {/* Global Toast Notification */}
      <Toast notification={notification} onClose={() => setNotification(null)} />
    </div>
  );
}

export default App;
