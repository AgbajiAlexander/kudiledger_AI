"""Disposable, loopback-only product-owner rehearsal using synthetic records."""

import json
import logging
import os
import socket
import tempfile
import threading
import time
from contextlib import ExitStack
from getpass import getpass
from pathlib import Path

import uvicorn
from starlette.responses import JSONResponse, Response

from app.operations.pilot import restore_database
from app.operations.staging import invite, scheduled_backup
from app.services.account_mail import AccountMail
from app.services.telemetry import StagingLedger


EMAIL = "commissioning@example.test"
SECOND_EMAIL = "commissioning-other@example.test"


def simulate_interruption(app, armed):
    @app.middleware("http")
    async def lose_one_acknowledgement(request, call_next):
        response = await call_next(request)
        route = getattr(request.scope.get("route"), "path", None)
        if (not armed.is_set() or request.method != "POST" or response.status_code != 200
                or route != "/api/v1/businesses/{business_id}/recovery/{attempt_id}/submit"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        if armed.is_set() and json.loads(body)["status"] == "saved":
            armed.clear()
            return JSONResponse({"detail": "Synthetic acknowledgement interruption"},
                                status_code=503, headers={"Cache-Control": "no-store"})
        return Response(body, status_code=response.status_code, headers=dict(response.headers))


def serve(stack, listener, application):
    server = uvicorn.Server(uvicorn.Config(application, access_log=False, log_level="warning"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    worker.start()
    stack.callback(worker.join, 10)
    stack.callback(setattr, server, "should_exit", True)
    for _ in range(100):
        if server.started:
            return
        if not worker.is_alive():
            break
        time.sleep(0.05)
    raise RuntimeError("The synthetic loopback demo could not start")


def loopback(stack):
    listener = stack.enter_context(socket.socket())
    listener.bind(("127.0.0.1", 0))
    return listener, f"http://127.0.0.1:{listener.getsockname()[1]}"


def resolve_conflict(ledger):
    reference = input("Synthetic conflicting reference: ").strip()
    token = ledger.login(EMAIL, getpass("Synthetic account password: "))
    business = ledger.list_my_businesses(token)[0]["id"]
    ledger.set_recovery_operator(business, EMAIL, enabled=True)
    try:
        entries = ledger.list_operator_recovery(token, business, reference)
        conflicts = [entry for entry in entries if entry["status"] == "conflict"]
        if len(conflicts) != 1:
            raise ValueError("Use a reference with one unresolved conflict")
        if input("Review the original receipt, then type RELEASE to record the synthetic decision: ") != "RELEASE":
            print("Decision cancelled.")
            return None
        decision = ledger.decide_recovery(
            token, business, conflicts[0]["id"],
            decision="release_failed", evidence_type="ledger_conflict",
            evidence_reference="SYNTHETIC-COMMISSIONING",
            evidence_notes="The operator reviewed the original receipt and confirmed the synthetic reference collision.",
            confirmed=True,
        )
        print("Recorded operator audit ID " + decision["audit_id"])
        return decision["audit_id"]
    finally:
        ledger.set_recovery_operator(business, EMAIL, enabled=False)


def main():
    with tempfile.TemporaryDirectory(prefix="kudiledger-commissioning-") as folder, ExitStack() as stack:
        root = Path(folder)
        database = root / "demo.sqlite"
        mailbox = root / "capture"
        mailbox.mkdir(mode=0o700)
        os.environ.update(KUDILEDGER_DB=str(root / "import-only.sqlite"),
                          KUDILEDGER_MAIL_MODE="off", KUDILEDGER_REQUIRE_HTTPS="0")
        from app.api.main import create_app

        logging.getLogger("kudiledger.operations").setLevel(logging.WARNING)
        listener, origin = loopback(stack)
        mail = AccountMail(mode="capture", origin=origin, directory=mailbox)
        ledger = StagingLedger(database)
        invite(database, EMAIL, "Commissioning Synthetic Market", mail)
        invite(database, SECOND_EMAIL, "Commissioning Other Market", mail)
        armed = threading.Event()
        application = create_app(database, require_https=False, account_mail=mail)
        simulate_interruption(application, armed)
        serve(stack, listener, application)
        print("Synthetic dashboard " + origin + "/app")
        print("Open the private captured invitation JSON in " + str(mailbox))
        print("Use " + EMAIL + " and " + SECOND_EMAIL + " with synthetic passwords.")
        print("Closing the demo deletes the sandbox.")
        audit_id = None
        backup = None
        restored = False
        while True:
            try:
                action = input("\n[L] Lose next save reply  [E] Expire demo sessions  [M] List captures  [O] Resolve conflict  "
                               "[B] Backup  [R] Restore in isolation  [Q] Quit: ").strip().upper()
            except EOFError:
                return
            try:
                if action == "Q":
                    return
                if action == "L":
                    armed.set()
                    print("The next successful financial save will commit and receive a synthetic interruption.")
                elif action == "E":
                    with ledger.connect() as db:
                        db.execute("UPDATE sessions SET expires_at = 0")
                    print("Synthetic sessions expired. Check a protected action and sign in again.")
                elif action == "M":
                    for file in sorted(mailbox.glob("*.json"), key=lambda entry: entry.stat().st_mtime):
                        print(file.name)
                elif action == "O":
                    audit_id = resolve_conflict(ledger) or audit_id
                elif action == "B":
                    backup = scheduled_backup(database, root)
                    print("Verified snapshot " + backup["file"])
                elif action == "R":
                    if not backup or restored:
                        print("Create a backup first. This sandbox supports one isolated restore.")
                        continue
                    replica = root / "restored.sqlite"
                    restore_database(root / backup["file"], replica, backup["sha256"])
                    replica_ledger = StagingLedger(replica)
                    with replica_ledger.connect() as db:
                        audit = db.execute(
                            "SELECT count(*) FROM recovery_operator_audit WHERE id = ?", (audit_id,),
                        ).fetchone()[0]
                    peer, replica_origin = loopback(stack)
                    serve(stack, peer, create_app(replica, require_https=False, account_mail=AccountMail()))
                    restored = True
                    print("Isolated restored dashboard " + replica_origin + "/app")
                    print("Sign in again and compare balances and references.")
                    if audit_id:
                        print("Selected operator audit present in restored database: " + str(bool(audit)))
            except ValueError as error:
                print(str(error))
    # The context managers stop only the servers and remove only the demo's own sandbox.


if __name__ == "__main__":
    main()
