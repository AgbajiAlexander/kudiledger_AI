import base64
import hashlib
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.services.login_guard import LoginGuard
from app.services.operators import PilotLedger
from app.services.recovery import RecoveryConflict, RecoveryNotFound


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



class ExpenseRequest(BaseModel):
    reference: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=3, max_length=500)
    amount: str = Field(min_length=1, max_length=40)
    confirmed: bool = False


class RecoverySale(SaleRequest):
    kind: Literal["sale"]
    customer_id: str = Field(min_length=1, max_length=100)
    total: str = Field(min_length=1, max_length=40)
    paid: str = Field(min_length=1, max_length=40)


class RecoveryRepayment(RepaymentRequest):
    kind: Literal["repayment"]
    customer_id: str = Field(min_length=1, max_length=100)
    amount: str = Field(min_length=1, max_length=40)


class RecoveryExpense(ExpenseRequest):
    kind: Literal["expense"]


class RecoveryAcknowledgement(BaseModel):
    transaction_id: str = Field(min_length=1, max_length=100)


class OperatorDecision(BaseModel):
    decision: Literal["retain_uncertain", "confirm_committed", "release_failed"]
    evidence_type: Literal["inconclusive", "ledger_match", "ledger_conflict", "prewrite_failure"]
    evidence_reference: str = Field(min_length=1, max_length=120)
    evidence_notes: str = Field(min_length=24, max_length=1000)
    confirmed: bool = False


RecoveryPayload = Annotated[
    RecoverySale | RecoveryRepayment | RecoveryExpense,
    Field(discriminator="kind"),
]


def create_app(database_path=None, *, require_https=None):
    app = FastAPI(
        title="KudiLedger AI",
        description="Financial record-keeping API for Nigerian SMEs",
        version="0.2.0",
    )

    db_path = database_path or os.environ.get(
        "KUDILEDGER_DB", "kudiledger_api.db"
    )

    if require_https is None:
        configured = os.environ.get("KUDILEDGER_REQUIRE_HTTPS", "0")
        if configured not in ("0", "1"):
            raise ValueError("KUDILEDGER_REQUIRE_HTTPS must be 0 or 1")
        require_https = configured == "1"

    ledger = PilotLedger(db_path)
    login_guard = LoginGuard(ledger)

    @app.middleware("http")
    async def response_safeguards(request, call_next):
        secure = request.url.scheme == "https"
        if require_https and not secure:
            response = JSONResponse({"detail": "HTTPS is required"}, status_code=400)
        else:
            response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        if require_https and secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path.startswith("/api/v1/") or request.url.path == "/app":
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error):
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: item[key] for key in ("loc", "msg", "type")}
                    for item in error.errors()
                ],
            },
        )

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
        except RecoveryNotFound as error:
            raise HTTPException(status_code=404, detail=str(error)) from None
        except RecoveryConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
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


    @app.get(
        "/api/v1/businesses/{business_id}/customers/"
        "{customer_id}/statement"
    )
    def get_customer_statement(
        business_id: str,
        customer_id: str,
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.customer_statement(
                token, business_id, customer_id
            )
        )


    @app.get("/api/v1/businesses/{business_id}/customers")
    def list_business_customers(
        business_id: str,
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.list_business_customers(
                token, business_id
            )
        )


    @app.post(
        "/api/v1/businesses/{business_id}/expenses",
        status_code=201,
    )
    def create_expense(
        business_id: str,
        payload: ExpenseRequest,
        token: str = Depends(require_token),
    ):
        expense_id = run_protected(
            lambda: ledger.record_expense(
                token,
                business_id,
                payload.reference,
                payload.category,
                payload.description,
                payload.amount,
                confirmed=payload.confirmed,
            )
        )

        return {
            "id": expense_id,
            "status": "CONFIRMED",
        }

    @app.get("/api/v1/businesses/{business_id}/expenses")
    def list_business_expenses(
        business_id: str,
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.list_expenses(
                token, business_id
            )
        )

    @app.get("/api/v1/businesses/{business_id}/expenses/summary")
    def get_expense_summary(
        business_id: str,
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.expense_summary(
                token, business_id
            )
        )


    @app.get(
        "/api/v1/businesses/{business_id}/reports/daily"
    )
    def get_daily_business_report(
        business_id: str,
        report_date: str,
        token: str = Depends(require_token),
    ):
        """Return activity for an Africa/Lagos date and current outstanding debt."""
        if len(report_date) > 32:
            raise HTTPException(
                status_code=400,
                detail="Invalid report date",
            )

        return run_protected(
            lambda: ledger.daily_summary(
                token,
                business_id,
                report_date,
            )
        )


    @app.get("/app", include_in_schema=False)
    def trader_dashboard():
        source = (
            Path(__file__).resolve().parents[1]
            / "web" / "index.html"
        ).read_text(encoding="utf-8")
        policy = ["default-src 'none'", "connect-src 'self'", "frame-ancestors 'none'",
                  "base-uri 'none'", "form-action 'self'"]
        for tag in ("script", "style"):
            blocks = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", source, re.DOTALL)
            digests = [
                "'sha256-" + base64.b64encode(hashlib.sha256(block.encode()).digest()).decode() + "'"
                for block in blocks
            ]
            policy.append(f"{tag}-src " + (" ".join(digests) or "'none'"))
        return HTMLResponse(source, headers={"Content-Security-Policy": "; ".join(policy)})


    @app.get("/api/v1/auth/businesses")
    def get_my_businesses(
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.list_my_businesses(token)
        )


    @app.get(
        "/api/v1/businesses/{business_id}/transactions/lookup"
    )
    def lookup_existing_transaction(
        business_id: str,
        kind: str,
        reference: str,
        token: str = Depends(require_token),
    ):
        return run_protected(
            lambda: ledger.lookup_transaction(
                token,
                business_id,
                kind,
                reference,
            )
        )

    @app.get("/api/v1/businesses/{business_id}/receipts")
    def get_transaction_receipt(
        business_id: str,
        kind: str,
        response: Response,
        transaction_id: str | None = None,
        reference: str | None = None,
        token: str = Depends(require_token),
    ):
        """Read a committed receipt by kind and either transaction ID or reference."""
        receipt = run_protected(
            lambda: ledger.transaction_receipt(
                token, business_id, kind, transaction_id, reference
            )
        )
        if receipt is None:
            raise HTTPException(status_code=404, detail="Receipt not found")
        response.headers["Cache-Control"] = "no-store"
        return receipt

    recovery_path = "/api/v1/businesses/{business_id}/recovery"

    @app.get(recovery_path)
    def list_recovery(business_id: str, response: Response, token: str = Depends(require_token)):
        response.headers["Cache-Control"] = "no-store"
        return run_protected(lambda: ledger.list_recovery(token, business_id))

    @app.post(recovery_path, status_code=201)
    def prepare_recovery(
        business_id: str, payload: RecoveryPayload, response: Response,
        token: str = Depends(require_token),
    ):
        response.headers["Cache-Control"] = "no-store"
        return run_protected(lambda: ledger.prepare_recovery(
            token, business_id, payload.kind, payload.model_dump(exclude={"kind"}),
        ))

    @app.post(recovery_path + "/{attempt_id}/submit")
    def submit_recovery(
        business_id: str, attempt_id: str, response: Response,
        token: str = Depends(require_token),
    ):
        response.headers["Cache-Control"] = "no-store"
        return run_protected(lambda: ledger.submit_recovery(token, business_id, attempt_id))

    @app.post(recovery_path + "/{attempt_id}/check")
    def check_recovery(
        business_id: str, attempt_id: str, response: Response,
        token: str = Depends(require_token),
    ):
        response.headers["Cache-Control"] = "no-store"
        return run_protected(lambda: ledger.check_recovery(token, business_id, attempt_id))

    @app.post(recovery_path + "/{attempt_id}/acknowledge")
    def acknowledge_recovery(
        business_id: str, attempt_id: str, payload: RecoveryAcknowledgement,
        response: Response, token: str = Depends(require_token),
    ):
        response.headers["Cache-Control"] = "no-store"
        return run_protected(lambda: ledger.acknowledge_recovery(
            token, business_id, attempt_id, payload.transaction_id,
        ))

    @app.delete(recovery_path + "/{attempt_id}")
    def clear_recovery(
        business_id: str, attempt_id: str, response: Response,
        action: Literal["cancel", "dismiss"],
        token: str = Depends(require_token),
    ):
        response.headers["Cache-Control"] = "no-store"
        run_protected(lambda: ledger.clear_recovery(
            token, business_id, attempt_id, cancel=action == "cancel",
        ))
        return {"status": "cleared"}

    operator_path = "/api/v1/businesses/{business_id}/operator/recovery"

    @app.get(operator_path)
    def list_operator_recovery(
        business_id: str, reference: Annotated[str | None, Query(max_length=100)] = None,
        token: str = Depends(require_token),
    ):
        return run_protected(lambda: ledger.list_operator_recovery(
            token, business_id, reference.strip() if reference else None,
        ))

    @app.post(operator_path + "/{attempt_id}/decisions", status_code=201)
    def decide_operator_recovery(
        business_id: str, attempt_id: str, payload: OperatorDecision,
        token: str = Depends(require_token),
    ):
        return run_protected(lambda: ledger.decide_recovery(
            token, business_id, attempt_id, **payload.model_dump(),
        ))

    @app.get(operator_path + "/{attempt_id}/audit")
    def get_operator_recovery_audit(
        business_id: str, attempt_id: str, token: str = Depends(require_token),
    ):
        return run_protected(lambda: ledger.operator_recovery_audit(token, business_id, attempt_id))

    return app


app = create_app()
