import os
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.services.reversals import ReversalLedger
from app.services.login_guard import LoginGuard


security = HTTPBearer(auto_error=False)


class LoginRequest(BaseModel):
    email: str
    password: str


class CustomerRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)


class SaleRequest(BaseModel):
    customer_id: str
    reference: str = Field(min_length=1, max_length=100)
    total: str
    paid: str
    confirmed: bool = False


class RepaymentRequest(BaseModel):
    customer_id: str
    reference: str = Field(min_length=1, max_length=100)
    amount: str
    confirmed: bool = False



class AdjustmentRequest(BaseModel):
    customer_id: str = Field(min_length=1)
    reference: str = Field(min_length=1, max_length=100)
    amount: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=10, max_length=500)
    confirmed: bool = False



class SaleReversalRequest(BaseModel):
    sale_id: str = Field(min_length=1, max_length=100)
    reference: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=10, max_length=500)
    confirmed: bool = False


def create_app(database_path=None):
    app = FastAPI(
        title="KudiLedger AI",
        description="Financial record-keeping API for Nigerian SMEs",
        version="0.2.0",
    )

    db_path = database_path or os.environ.get(
        "KUDILEDGER_DB", "kudiledger_api.db"
    )

    ledger = ReversalLedger(db_path)
    login_guard = LoginGuard(ledger)

    def require_token(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(security),
        ],
    ):
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Authentication required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = credentials.credentials

        if not ledger.is_active_session(token):
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return token

    def run_protected(operation):
        try:
            return operation()
        except PermissionError:
            raise HTTPException(
                status_code=403,
                detail="Access denied",
            ) from None
        except ValueError as error:
            raise HTTPException(
                status_code=400,
                detail=str(error),
            ) from None

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "application": "KudiLedger AI",
            "version": "0.2.0",
        }

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest):
        email = payload.email

        if len(email) > 254 or len(payload.password) > 1024:
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            )

        if not login_guard.allowed(email):
            raise HTTPException(
                status_code=429,
                detail="Too many login attempts. Try again later.",
                headers={"Retry-After": "900"},
            )

        try:
            token = ledger.login(email, payload.password)
        except ValueError:
            login_guard.failed(email)
            raise HTTPException(
                status_code=401,
                detail="Invalid credentials",
            ) from None

        login_guard.succeeded(email)

        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 43200,
        }

    @app.post("/api/v1/auth/logout")
    def logout(token: str = Depends(require_token)):
        ledger.logout(token)
        return {"message": "Logged out"}

    @app.post(
        "/api/v1/businesses/{business_id}/customers",
        status_code=201,
    )
    def create_customer(
        business_id: str,
        payload: CustomerRequest,
        token: str = Depends(require_token),
    ):
        customer_id = run_protected(
            lambda: ledger.add_customer(
                token, business_id, payload.name
            )
        )
        return {"id": customer_id, "name": payload.name}

    @app.post(
        "/api/v1/businesses/{business_id}/sales",
        status_code=201,
    )
    def create_sale(
        business_id: str,
        payload: SaleRequest,
        token: str = Depends(require_token),
    ):
        sale_id = run_protected(
            lambda: ledger.add_sale(
                token,
                business_id,
                payload.customer_id,
                payload.reference,
                payload.total,
                payload.paid,
                confirmed=payload.confirmed,
            )
        )
        return {"id": sale_id, "status": "CONFIRMED"}

    @app.post(
        "/api/v1/businesses/{business_id}/repayments",
        status_code=201,
    )
    def create_repayment(
        business_id: str,
        payload: RepaymentRequest,
        token: str = Depends(require_token),
    ):
        repayment_id = run_protected(
            lambda: ledger.add_repayment(
                token,
                business_id,
                payload.customer_id,
                payload.reference,
                payload.amount,
                confirmed=payload.confirmed,
            )
        )
        return {
            "id": repayment_id,
            "status": "CONFIRMED",
        }

    @app.get(
        "/api/v1/businesses/{business_id}/customers/"
        "{customer_id}/balance"
    )
    def get_balance(
        business_id: str,
        customer_id: str,
        token: str = Depends(require_token),
    ):
        amount = run_protected(
            lambda: ledger.get_balance(
                token, business_id, customer_id
            )
        )
        return {
            "customer_id": customer_id,
            "balance_naira": str(amount.quantize(
                Decimal("0.01")
            )),
            "currency": "NGN",
        }

    @app.get(
        "/api/v1/businesses/{business_id}/customers/"
        "{customer_id}/repayments"
    )
    def get_repayments(
        business_id: str,
        customer_id: str,
        token: str = Depends(require_token),
    ):
        records = run_protected(
            lambda: ledger.get_repayments(
                token, business_id, customer_id
            )
        )
        return [
            {
                **item,
                "amount": str(
                    item["amount"].quantize(Decimal("0.01"))
                ),
            }
            for item in records
        ]


    @app.post(
        "/api/v1/businesses/{business_id}/adjustments",
        status_code=201,
    )
    def create_adjustment(
        business_id: str,
        payload: AdjustmentRequest,
        token: str = Depends(require_token),
    ):
        adjustment_id = run_protected(
            lambda: ledger.adjust_customer_balance(
                token,
                business_id,
                payload.customer_id,
                payload.reference,
                payload.amount,
                payload.reason,
                confirmed=payload.confirmed,
            )
        )

        return {
            "id": adjustment_id,
            "status": "CONFIRMED",
        }

    @app.get(
        "/api/v1/businesses/{business_id}/customers/"
        "{customer_id}/adjustments"
    )
    def list_adjustments(
        business_id: str,
        customer_id: str,
        token: str = Depends(require_token),
    ):
        records = run_protected(
            lambda: ledger.get_adjustments(
                token,
                business_id,
                customer_id,
            )
        )

        return [
            {
                **item,
                "amount": str(
                    item["amount"].quantize(Decimal("0.01"))
                ),
            }
            for item in records
        ]


    @app.post(
        "/api/v1/businesses/{business_id}/sale-reversals",
        status_code=201,
    )
    def create_sale_reversal(
        business_id: str,
        payload: SaleReversalRequest,
        token: str = Depends(require_token),
    ):
        reversal_id = run_protected(
            lambda: ledger.reverse_unpaid_sale(
                token,
                business_id,
                payload.sale_id,
                payload.reference,
                payload.reason,
                confirmed=payload.confirmed,
            )
        )

        return {
            "id": reversal_id,
            "sale_id": payload.sale_id,
            "status": "CONFIRMED",
        }

    @app.get(
        "/api/v1/businesses/{business_id}/sale-reversals"
    )
    def get_sale_reversals(
        business_id: str,
        token: str = Depends(require_token),
    ):
        records = run_protected(
            lambda: ledger.list_sale_reversals(
                token, business_id
            )
        )

        return [
            {
                **record,
                "amount": str(
                    record["amount"].quantize(
                        Decimal("0.01")
                    )
                ),
            }
            for record in records
        ]

    return app


app = create_app()
