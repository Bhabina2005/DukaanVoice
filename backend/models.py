from datetime import datetime
from typing import Any

from sqlalchemy import (
    String, Integer, ForeignKey, DateTime, CheckConstraint, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )

    transactions = relationship(
        "Transaction",
        back_populates="customer",
        cascade="all, delete-orphan"
    )
    pending_transactions = relationship(
        "PendingTransaction",
        back_populates="customer",
        cascade="all, delete-orphan"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_transaction_amount"),
        CheckConstraint(
            "transaction_type IN ('CREDIT', 'PAYMENT')",
            name="valid_transaction_type"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )

    transaction_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )

    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    description: Mapped[str | None] = mapped_column(String(255))

    idempotency_key: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )

    customer = relationship(
        "Customer",
        back_populates="transactions"
    )


class PendingTransaction(Base):
    __tablename__ = "pending_transactions"

    __table_args__ = (
        CheckConstraint("amount > 0", name="positive_pending_amount"),
        CheckConstraint(
            "transaction_type IN ('CREDIT', 'PAYMENT')",
            name="valid_pending_type"
        ),
        CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED')",
            name="valid_pending_status"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUIDv4 pending_id
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", index=True
    )
    confirmed_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("transactions.id"), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    audit_trail: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )

    customer = relationship(
        "Customer",
        back_populates="pending_transactions"
    )
    confirmed_transaction = relationship("Transaction")

    def to_dict(self) -> dict[str, Any]:
        balance_preview = None
        for entry in reversed(self.audit_trail or []):
            if isinstance(entry, dict) and "balance_preview" in entry and entry["balance_preview"] is not None:
                balance_preview = entry["balance_preview"]
                break

        return {
            "pending_id": self.id,
            "session_id": self.session_id,
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "amount": self.amount,
            "transaction_type": self.transaction_type,
            "description": self.description,
            "status": self.status,
            "confirmed_transaction_id": self.confirmed_transaction_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "audit_trail": self.audit_trail or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "balance_preview": balance_preview,
        }
