from contextlib import contextmanager
from datetime import datetime, timedelta
import threading
from typing import Any
import uuid

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import FlushError
from sqlalchemy.orm import Session

from database import SessionLocal
from models import Customer, Transaction, PendingTransaction


def get_customer_net_balance(db: Session, customer_id: int) -> int:
    credit_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "CREDIT"
        )
    ) or 0
    payment_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "PAYMENT"
        )
    ) or 0
    return int(credit_total - payment_total)


def compute_balance_preview(
    db: Session,
    customer_id: int,
    amount: int,
    transaction_type: str
) -> dict[str, Any]:
    credit_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "CREDIT"
        )
    ) or 0
    payment_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "PAYMENT"
        )
    ) or 0

    current_net = int(credit_total - payment_total)
    current_outstanding = max(0, current_net)
    current_advance = max(0, -current_net)

    if transaction_type == "CREDIT":
        expected_net = current_net + amount
    elif transaction_type == "PAYMENT":
        expected_net = current_net - amount
    else:
        expected_net = current_net

    expected_outstanding = max(0, expected_net)
    expected_advance = max(0, -expected_net)

    if expected_outstanding > 0:
        explanation = f"Customer will owe ₹{expected_outstanding}"
        explanation_kn = f"ಗ್ರಾಹಕರು ₹{expected_outstanding} ಬಾಕಿ ಉಳಿಸಿಕೊಳ್ಳುತ್ತಾರೆ"
    elif expected_advance > 0:
        explanation = f"Customer will have an advance balance of ₹{expected_advance}"
        explanation_kn = f"ಗ್ರಾಹಕರ ಖಾತೆಯಲ್ಲಿ ₹{expected_advance} ಮುಂಗಡ (ಜಮಾ) ಇರುತ್ತದೆ"
    else:
        explanation = "Account will be fully settled (₹0 balance)"
        explanation_kn = "ಖಾತೆ ಪೂರ್ಣವಾಗಿ ಚುಕ್ತಾ ಆಗುತ್ತದೆ (₹0 ಬಾಕಿ)"

    return {
        "current_outstanding": current_outstanding,
        "current_advance": current_advance,
        "expected_outstanding": expected_outstanding,
        "expected_advance": expected_advance,
        "expected_net_balance": expected_net,
        "baseline_balance": current_net,
        "balance_explanation": explanation,
        "balance_explanation_kn": explanation_kn
    }


class PendingTransactionManager:
    """
    Durable, database-backed pending transaction repository.
    Replaces in-memory storage to survive restarts and support multi-worker processes.
    Provides atomic confirmation, database-enforced idempotency, and 15-minute TTL.
    """

    def __init__(self, session_factory=None):
        self._session_factory = session_factory or SessionLocal
        self._lock = threading.Lock()

    @contextmanager
    def _get_session(self, db: Session | None = None):
        """
        Yields the provided active session, or safely opens and closes a new session.
        """
        if db is not None:
            yield db
        else:
            session = self._session_factory()
            try:
                yield session
            finally:
                session.close()

    def create_pending(
        self,
        session_id: str,
        customer_id: int,
        customer_name: str,
        customer_phone: str | None,
        amount: int,
        transaction_type: str,
        description: str | None = None,
        db: Session | None = None
    ) -> dict[str, Any]:
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")
        if amount > 10_000_000:
            raise ValueError("Amount exceeds maximum limit of ₹10,000,000")
        if transaction_type not in ("CREDIT", "PAYMENT"):
            raise ValueError("Transaction type must be CREDIT or PAYMENT")

        with self._get_session(db) as s:
            # Validate customer exists in database
            customer = s.get(Customer, customer_id)
            if not customer:
                raise ValueError(f"Customer with ID {customer_id} does not exist")

            # Clean up / supersede any existing active pending transaction for this session
            existing_active = s.scalars(
                select(PendingTransaction).where(
                    PendingTransaction.session_id == session_id,
                    PendingTransaction.status == "PENDING"
                )
            ).all()

            now = datetime.now()
            now_iso = now.isoformat()

            for old in existing_active:
                old.status = "CANCELLED"
                old.updated_at = now
                old.audit_trail = list(old.audit_trail or []) + [{
                    "timestamp": now_iso,
                    "action": "SUPERSEDED",
                    "details": "Superseded by a new voice transaction instruction"
                }]

            pending_id = str(uuid.uuid4())
            expires_at = now + timedelta(minutes=15)
            preview = compute_balance_preview(s, customer.id, amount, transaction_type)
            audit_trail = [{
                "timestamp": now_iso,
                "action": "CREATED",
                "details": f"Initiated {transaction_type} of ₹{amount} for {customer.name}",
                "balance_preview": preview
            }]

            record = PendingTransaction(
                id=pending_id,
                session_id=session_id,
                customer_id=customer.id,
                customer_name=customer.name,
                customer_phone=customer.phone,
                amount=amount,
                transaction_type=transaction_type,
                description=description or f"Voice {transaction_type.lower()} transaction",
                status="PENDING",
                confirmed_transaction_id=None,
                expires_at=expires_at,
                audit_trail=audit_trail,
                created_at=now,
                updated_at=now
            )
            s.add(record)
            s.commit()
            s.refresh(record)
            return record.to_dict()

    def get_pending(self, pending_id: str, db: Session | None = None) -> dict[str, Any] | None:
        with self._get_session(db) as s:
            record = s.get(PendingTransaction, pending_id)
            if not record:
                return None

            # Handle 15-minute expiration
            if record.status == "PENDING" and record.expires_at < datetime.now():
                now = datetime.now()
                record.status = "EXPIRED"
                record.updated_at = now
                record.audit_trail = list(record.audit_trail or []) + [{
                    "timestamp": now.isoformat(),
                    "action": "EXPIRED",
                    "details": "Pending transaction expired after 15 minutes"
                }]
                s.commit()
                s.refresh(record)

            return record.to_dict()

    def get_active_for_session(self, session_id: str, db: Session | None = None) -> dict[str, Any] | None:
        with self._get_session(db) as s:
            records = s.scalars(
                select(PendingTransaction).where(
                    PendingTransaction.session_id == session_id,
                    PendingTransaction.status == "PENDING"
                ).order_by(PendingTransaction.created_at.desc())
            ).all()

            now = datetime.now()
            for record in records:
                if record.expires_at < now:
                    record.status = "EXPIRED"
                    record.updated_at = now
                    record.audit_trail = list(record.audit_trail or []) + [{
                        "timestamp": now.isoformat(),
                        "action": "EXPIRED",
                        "details": "Pending transaction expired after 15 minutes"
                    }]
                    s.commit()
                else:
                    return record.to_dict()

            return None

    def correct_pending(
        self,
        pending_id: str,
        amount: int | None = None,
        customer_id: int | None = None,
        customer_name: str | None = None,
        customer_phone: str | None = None,
        transaction_type: str | None = None,
        db: Session | None = None
    ) -> dict[str, Any]:
        with self._get_session(db) as s:
            record = s.get(PendingTransaction, pending_id)
            if not record:
                raise ValueError("Pending transaction not found")

            # Check expiration
            now = datetime.now()
            if record.status == "PENDING" and record.expires_at < now:
                record.status = "EXPIRED"
                record.updated_at = now
                s.commit()
                raise ValueError("Transaction has expired and cannot be corrected")

            if record.status != "PENDING":
                raise ValueError(f"Cannot correct transaction with status {record.status}")

            now_iso = now.isoformat()
            changes = []

            if amount is not None:
                if amount <= 0:
                    raise ValueError("Amount must be greater than zero")
                if amount > 10_000_000:
                    raise ValueError("Amount exceeds maximum limit of ₹10,000,000")
                if amount != record.amount:
                    old_amt = record.amount
                    record.amount = amount
                    changes.append(f"Amount corrected from ₹{old_amt} to ₹{amount}")

            if customer_id is not None and customer_id != record.customer_id:
                cust = s.get(Customer, customer_id)
                if not cust:
                    raise ValueError(f"Customer with ID {customer_id} does not exist")
                old_cust = record.customer_name
                record.customer_id = customer_id
                record.customer_name = cust.name
                record.customer_phone = cust.phone
                changes.append(f"Customer changed from {old_cust} to {cust.name}")

            if transaction_type and transaction_type in ("CREDIT", "PAYMENT") and transaction_type != record.transaction_type:
                old_type = record.transaction_type
                record.transaction_type = transaction_type
                changes.append(f"Transaction type changed from {old_type} to {transaction_type}")

            if changes:
                record.updated_at = now
                # Active correction extends the TTL by 15 minutes
                record.expires_at = now + timedelta(minutes=15)
                preview = compute_balance_preview(s, record.customer_id, record.amount, record.transaction_type)
                record.audit_trail = list(record.audit_trail or []) + [{
                    "timestamp": now_iso,
                    "action": "CORRECTED",
                    "details": "; ".join(changes),
                    "balance_preview": preview
                }]
                s.commit()
                s.refresh(record)

            return record.to_dict()

    def confirm_pending(
        self,
        pending_id: str,
        db: Session,
        expected_baseline: int | None = None
    ) -> tuple[dict[str, Any], Transaction | None]:
        with self._lock:
            record = db.get(PendingTransaction, pending_id)
            if not record:
                raise ValueError("Pending transaction not found")

            # 1. Idempotency Check: Already confirmed in record
            if record.status == "CONFIRMED":
                txn_id = record.confirmed_transaction_id
                existing_txn = db.get(Transaction, txn_id) if txn_id else None
                if not existing_txn:
                    existing_txn = db.scalar(
                        select(Transaction).where(Transaction.idempotency_key == pending_id)
                    )
                return record.to_dict(), existing_txn

            # 2. Check for invalid or terminal status
            if record.status == "CANCELLED":
                raise ValueError("Cannot confirm a cancelled transaction")

            now = datetime.now()
            if record.status == "EXPIRED" or record.expires_at < now:
                if record.status != "EXPIRED":
                    record.status = "EXPIRED"
                    record.updated_at = now
                    record.audit_trail = list(record.audit_trail or []) + [{
                        "timestamp": now.isoformat(),
                        "action": "EXPIRED",
                        "details": "Expired prior to confirmation attempt"
                    }]
                    db.commit()
                raise ValueError("Transaction has expired and cannot be confirmed")

            # 3. Idempotency Check: Check if Transaction with idempotency_key already committed
            existing_txn = db.scalar(
                select(Transaction).where(Transaction.idempotency_key == pending_id)
            )
            if existing_txn:
                record.status = "CONFIRMED"
                record.confirmed_transaction_id = existing_txn.id
                db.commit()
                return record.to_dict(), existing_txn

            # 4. Validate customer exists
            customer = db.get(Customer, record.customer_id)
            if not customer:
                raise ValueError("Customer no longer exists in database")

            if record.amount <= 0:
                raise ValueError("Amount must be greater than zero")

            # 4.5. Stale Balance Preview Protection
            # Inspect the latest baseline balance recorded when preview was prepared
            latest_preview = None
            for entry in reversed(record.audit_trail or []):
                if isinstance(entry, dict) and "balance_preview" in entry and entry["balance_preview"] is not None:
                    latest_preview = entry["balance_preview"]
                    break

            recorded_baseline = None
            if latest_preview and "baseline_balance" in latest_preview:
                recorded_baseline = latest_preview["baseline_balance"]
            elif expected_baseline is not None:
                recorded_baseline = expected_baseline

            if recorded_baseline is not None:
                current_net = get_customer_net_balance(db, record.customer_id)
                if current_net != recorded_baseline:
                    # Stale preview detected! Update preview to reflect current reality before raising
                    updated_preview = compute_balance_preview(
                        db, record.customer_id, record.amount, record.transaction_type
                    )
                    record.audit_trail = list(record.audit_trail or []) + [{
                        "timestamp": now.isoformat(),
                        "action": "STALE_PREVIEW_DETECTED",
                        "details": (
                            f"Customer balance changed from ₹{recorded_baseline} to ₹{current_net} "
                            f"before confirmation"
                        ),
                        "balance_preview": updated_preview
                    }]
                    record.updated_at = now
                    db.commit()
                    db.refresh(record)
                    raise ValueError(
                        f"Customer balance has changed since preview was generated "
                        f"(previous balance: ₹{recorded_baseline}, current balance: ₹{current_net}). "
                        f"Please review the updated balance before confirming."
                    )

            # 5. ATOMIC COMMIT: Insert ledger transaction and update pending status in one transaction
            try:
                db_txn = Transaction(
                    customer_id=record.customer_id,
                    transaction_type=record.transaction_type,
                    amount=record.amount,
                    description=record.description,
                    idempotency_key=pending_id
                )
                db.add(db_txn)
                db.flush()  # Flushes and assigns db_txn.id, will raise IntegrityError/FlushError if duplicate

                record.status = "CONFIRMED"
                record.confirmed_transaction_id = db_txn.id
                record.updated_at = now
                record.audit_trail = list(record.audit_trail or []) + [{
                    "timestamp": now.isoformat(),
                    "action": "CONFIRMED",
                    "details": f"Confirmed by shopkeeper. Ledger record created (Transaction #{db_txn.id}, ₹{db_txn.amount})"
                }]

                db.commit()
                db.refresh(db_txn)
                db.refresh(record)
                return record.to_dict(), db_txn

            except (IntegrityError, FlushError):
                db.rollback()
                # Concurrent confirmation caught by unique idempotency_key constraint
                existing_txn = db.scalar(
                    select(Transaction).where(Transaction.idempotency_key == pending_id)
                )
                if existing_txn:
                    refreshed_p = db.get(PendingTransaction, pending_id)
                    if refreshed_p and refreshed_p.status != "CONFIRMED":
                        refreshed_p.status = "CONFIRMED"
                        refreshed_p.confirmed_transaction_id = existing_txn.id
                        db.commit()
                    return (refreshed_p.to_dict() if refreshed_p else record.to_dict()), existing_txn
                raise ValueError("Database integrity error during transaction confirmation")

            except Exception:
                db.rollback()
                raise

    def cancel_pending(
        self,
        pending_id: str,
        db: Session | None = None
    ) -> dict[str, Any]:
        with self._get_session(db) as s:
            record = s.get(PendingTransaction, pending_id)
            if not record:
                raise ValueError("Pending transaction not found")

            if record.status == "CONFIRMED":
                raise ValueError("Cannot cancel an already confirmed transaction")

            if record.status == "CANCELLED":
                return record.to_dict()

            now = datetime.now()
            record.status = "CANCELLED"
            record.updated_at = now
            record.audit_trail = list(record.audit_trail or []) + [{
                "timestamp": now.isoformat(),
                "action": "CANCELLED",
                "details": "Cancelled by shopkeeper. No ledger record was created."
            }]
            s.commit()
            s.refresh(record)
            return record.to_dict()


# Global singleton instance
pending_manager = PendingTransactionManager()
