from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from database import get_db
from models import Customer, Transaction
from schemas import (
    TransactionCreate,
    TransactionResponse,
    TransactionWithCustomer,
    DashboardStats
)

router = APIRouter()


@router.post("/", response_model=TransactionResponse, status_code=201)
def create_transaction(
    transaction_data: TransactionCreate,
    db: Session = Depends(get_db)
):
    if transaction_data.amount <= 0:
        raise HTTPException(
            status_code=422,
            detail="Transaction amount must be greater than zero"
        )

    if transaction_data.transaction_type not in ("CREDIT", "PAYMENT"):
        raise HTTPException(
            status_code=422,
            detail="Invalid transaction type. Must be CREDIT or PAYMENT"
        )

    customer = db.get(Customer, transaction_data.customer_id)

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    transaction = Transaction(
        customer_id=transaction_data.customer_id,
        transaction_type=transaction_data.transaction_type,
        amount=transaction_data.amount,
        description=transaction_data.description
    )

    db.add(transaction)
    db.commit()
    db.refresh(transaction)

    return transaction


@router.get("/stats", response_model=DashboardStats)
def get_dashboard_stats(
    db: Session = Depends(get_db)
):
    total_credit = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.transaction_type == "CREDIT")
    ) or 0

    total_payments = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(Transaction.transaction_type == "PAYMENT")
    ) or 0

    customer_count = db.scalar(
        select(func.count(Customer.id))
    ) or 0

    transaction_count = db.scalar(
        select(func.count(Transaction.id))
    ) or 0

    return DashboardStats(
        total_credit=total_credit,
        total_payments=total_payments,
        outstanding_balance=total_credit - total_payments,
        customer_count=customer_count,
        transaction_count=transaction_count
    )


@router.get("/recent", response_model=list[TransactionWithCustomer])
def get_recent_transactions(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    statement = (
        select(
            Transaction.id,
            Transaction.customer_id,
            Customer.name.label("customer_name"),
            Customer.phone.label("customer_phone"),
            Transaction.transaction_type,
            Transaction.amount,
            Transaction.description,
            Transaction.created_at
        )
        .join(Customer, Transaction.customer_id == Customer.id)
        .order_by(Transaction.id.desc())
        .limit(limit)
    )

    rows = db.execute(statement).all()

    return [
        TransactionWithCustomer(
            id=row.id,
            customer_id=row.customer_id,
            customer_name=row.customer_name,
            customer_phone=row.customer_phone,
            transaction_type=row.transaction_type,
            amount=row.amount,
            description=row.description,
            created_at=row.created_at
        )
        for row in rows
    ]


@router.get("/customer/{customer_id}/balance")
def get_customer_balance(
    customer_id: int,
    db: Session = Depends(get_db)
):
    customer = db.get(Customer, customer_id)

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

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

    return {
        "customer_id": customer.id,
        "customer_name": customer.name,
        "total_credit": credit_total,
        "total_payments": payment_total,
        "outstanding_balance": credit_total - payment_total,
        "display_outstanding": max(0, credit_total - payment_total),
        "advance_balance": max(0, payment_total - credit_total),
    }


@router.get("/customer/{customer_id}", response_model=list[TransactionResponse])
def get_customer_transactions(
    customer_id: int,
    db: Session = Depends(get_db)
):
    customer = db.get(Customer, customer_id)

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    statement = (
        select(Transaction)
        .where(Transaction.customer_id == customer_id)
        .order_by(Transaction.id.desc())
    )

    return db.scalars(statement).all()
