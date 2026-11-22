import re
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from database import get_db
from models import Customer, Transaction
from schemas import CustomerCreate, CustomerResponse, CustomerWithBalance

router = APIRouter()


def normalize_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    cleaned = re.sub(r"[\s\-\(\)]", "", phone.strip())
    if cleaned.startswith("+91"):
        cleaned = cleaned[3:]
    elif cleaned.startswith("91") and len(cleaned) == 12:
        cleaned = cleaned[2:]
    return cleaned if cleaned else None


@router.post("/", response_model=CustomerResponse, status_code=201)
def create_customer(
    customer_data: CustomerCreate,
    db: Session = Depends(get_db)
):
    name = customer_data.name.strip()

    if len(name) < 2:
        raise HTTPException(
            status_code=422,
            detail="Customer name must contain at least 2 characters"
        )

    phone = normalize_phone(customer_data.phone)

    if phone:
        if not re.match(r"^\d{10}$", phone):
            raise HTTPException(
                status_code=422,
                detail="Phone number must be a valid 10-digit number"
            )

        existing = db.scalar(
            select(Customer).where(Customer.phone == phone)
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail="A customer with this phone number already exists"
            )

    customer = Customer(name=name, phone=phone)

    db.add(customer)
    db.commit()
    db.refresh(customer)

    return customer


@router.get("/summary", response_model=list[CustomerWithBalance])
def get_customers_summary(
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db)
):
    statement = select(Customer)

    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Customer.name.ilike(term), Customer.phone.ilike(term))
        )

    statement = statement.order_by(Customer.id.asc())
    customers = db.scalars(statement).all()

    result = []
    for customer in customers:
        credit_total = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .where(
                Transaction.customer_id == customer.id,
                Transaction.transaction_type == "CREDIT"
            )
        ) or 0

        payment_total = db.scalar(
            select(func.coalesce(func.sum(Transaction.amount), 0))
            .where(
                Transaction.customer_id == customer.id,
                Transaction.transaction_type == "PAYMENT"
            )
        ) or 0

        last_txn = db.scalar(
            select(Transaction.created_at)
            .where(Transaction.customer_id == customer.id)
            .order_by(Transaction.id.desc())
            .limit(1)
        )

        result.append(
            CustomerWithBalance(
                id=customer.id,
                name=customer.name,
                phone=customer.phone,
                created_at=customer.created_at,
                total_credit=credit_total,
                total_payments=payment_total,
                outstanding_balance=credit_total - payment_total,
                advance_balance=max(0, payment_total - credit_total),
                last_transaction_at=last_txn
            )
        )

    return result


@router.get("/", response_model=list[CustomerResponse])
def get_customers(
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db)
):
    statement = select(Customer)

    if search and search.strip():
        term = f"%{search.strip()}%"
        statement = statement.where(
            or_(Customer.name.ilike(term), Customer.phone.ilike(term))
        )

    statement = statement.order_by(Customer.id.desc())

    return db.scalars(statement).all()


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db)
):
    customer = db.get(Customer, customer_id)

    if not customer:
        raise HTTPException(
            status_code=404,
            detail="Customer not found"
        )

    return customer
