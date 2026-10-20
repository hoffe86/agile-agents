"""Controller-private SQLite admission ledger; no SDK or worker file ingestion.

I/O is limited to local SQLite/path checks, never model/network operations.
The controller must own an isolated directory outside the worker workspace.
POSIX mode/owner and cross-platform reparse/inode checks are defense in depth,
NOT proof that generated tools cannot read/copy the DB (especially on Windows).
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import sqlite3
import stat
from typing import Iterator

from authorization import (
    AdmissionReceipt, Assessment, BatchEnvelope, Decision, Grant, InvalidRecord,
    PlanSubmission, evaluate, expires_at, identifier, timestamp,
)

SCHEMA_VERSION = 1
SCHEMA = (
    "CREATE TABLE metadata (singleton INTEGER PRIMARY KEY CHECK(singleton=1), "
    "ledger_id TEXT NOT NULL, epoch TEXT NOT NULL, controller_id TEXT NOT NULL)",
    "CREATE TABLE batches (batch_id TEXT PRIMARY KEY, envelope TEXT NOT NULL, "
    "digest TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('active','aborted')))",
    "CREATE TABLE attempts (attempt_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL "
    "REFERENCES batches(batch_id), task_id TEXT NOT NULL, state TEXT NOT NULL "
    "CHECK(state IN ('blocked','issued','consumed','revoked')), "
    "tokens INTEGER NOT NULL CHECK(typeof(tokens)='integer' AND tokens>=0), "
    "aiu INTEGER NOT NULL CHECK(typeof(aiu)='integer' AND aiu>=0), "
    "seconds INTEGER NOT NULL CHECK(typeof(seconds)='integer' AND seconds>=0))",
    "CREATE TABLE grants (grant_id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE "
    "REFERENCES attempts(attempt_id), submission_digest TEXT NOT NULL UNIQUE, "
    "record TEXT NOT NULL, assessment TEXT NOT NULL, "
    "state TEXT NOT NULL CHECK(state IN ('issued','consumed','revoked')), "
    "receipt TEXT)",
)


class AdmissionDenied(RuntimeError):
    """Safe bounded denial, including a terminal outcome where appropriate."""

    def __init__(self, reason: str, *, abort: bool = False) -> None:
        self.decision = Decision("abort_batch" if abort else "block_task", (reason,))
        super().__init__(reason)


def _file_identity(path: Path, *, directory: bool = False,
                   private: bool = False) -> tuple[int, int]:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise AdmissionDenied("unsafe_ledger_path", abort=True)
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise AdmissionDenied("unsafe_ledger_path", abort=True)
    if not directory and info.st_nlink != 1:
        raise AdmissionDenied("unsafe_ledger_path", abort=True)
    if private and os.name == "posix":
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise AdmissionDenied("unsafe_ledger_permissions", abort=True)
    return info.st_dev, info.st_ino


class Ledger:
    """Trusted-controller API, never expose as an agent tool.

    Opening an existing DB aborts every unfinished batch and rotates its epoch.
    ``join_existing=True`` is ONLY for extra connections of the same currently
    running controller (including its owned child processes), not recovery.
    Controllers must use fresh instance IDs after restart. Old connections are
    fenced out by epoch checks. Every API is synchronous; no callbacks in a tx.
    """

    def __init__(self, path: Path, *, controller_instance_id: str,
                 join_existing: bool = False) -> None:
        self._failed = False
        self._connection: sqlite3.Connection | None = None
        self._epoch = ""
        self._anchors: dict[Path, tuple[int, int]] = {}
        try:
            self._path = Path(path)
            self._controller_id = identifier(controller_instance_id)
            if (not self._path.is_absolute() or ".." in self._path.parts or
                    str(self._path).startswith(("\\\\", "//")) or
                    self._path.name in ("", ".", "..") or type(join_existing) is not bool):
                raise AdmissionDenied("unsafe_ledger_path", abort=True)
            for parent in self._path.parents:
                self._anchors[parent] = _file_identity(
                    parent, directory=True, private=parent == self._path.parent)
            exists = os.path.lexists(self._path)
            if not exists:
                if join_existing:
                    raise AdmissionDenied("unknown_ledger", abort=True)
                fd = os.open(self._path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            self._anchors[self._path] = _file_identity(self._path, private=True)
            self._check_paths()
            self._connection = sqlite3.connect(str(self._path), isolation_level=None, timeout=5)
            self._connection.execute("PRAGMA foreign_keys=ON")
            self._connection.execute("PRAGMA trusted_schema=OFF")
            self._connection.execute("PRAGMA synchronous=FULL")
            self._connection.execute("BEGIN IMMEDIATE")
            if not exists:
                for statement in SCHEMA:
                    self._connection.execute(statement)
                self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                self._connection.execute("INSERT INTO metadata VALUES (1,?,?,?)",
                                         (secrets.token_hex(24), secrets.token_hex(24),
                                          self._controller_id))
            self._check_schema()
            ledger_id, epoch, controller = self._connection.execute(
                "SELECT ledger_id,epoch,controller_id FROM metadata WHERE singleton=1").fetchone()
            identifier(ledger_id)
            identifier(epoch)
            identifier(controller)
            if join_existing:
                if controller != self._controller_id:
                    raise AdmissionDenied("controller_mismatch", abort=True)
            else:
                self._abort_all()
                epoch = secrets.token_hex(24)
                self._connection.execute("UPDATE metadata SET epoch=?,controller_id=?",
                                         (epoch, self._controller_id))
            self.ledger_id, self._epoch = ledger_id, epoch
            self._check_paths()
            self._connection.commit()
        except (OSError, sqlite3.Error, AdmissionDenied, TypeError, ValueError):
            if self._connection is not None:
                self._connection.close()
            self._failed = True
            raise AdmissionDenied("ledger_initialization_failed", abort=True) from None

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._failed = True

    def __enter__(self) -> Ledger:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _check_paths(self) -> None:
        for path, expected in self._anchors.items():
            actual = _file_identity(path, directory=path != self._path,
                                    private=path in (self._path, self._path.parent))
            if actual != expected:
                raise AdmissionDenied("ledger_path_substituted", abort=True)
        for suffix in ("-journal", "-wal", "-shm"):
            side = Path(str(self._path) + suffix)
            if os.path.lexists(side):
                _file_identity(side, private=True)

    def _check_schema(self) -> None:
        db = self._connection
        if db.execute("PRAGMA user_version").fetchone() != (SCHEMA_VERSION,):
            raise AdmissionDenied("unknown_ledger_schema", abort=True)
        actual = {row[0] for row in db.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")}
        if (actual != set(SCHEMA) or
                db.execute("PRAGMA quick_check").fetchall() != [("ok",)] or
                db.execute("PRAGMA foreign_key_check").fetchall() or
                db.execute("SELECT COUNT(*) FROM metadata").fetchone() != (1,)):
            raise AdmissionDenied("ledger_corrupt", abort=True)

    def _abort_all(self) -> None:
        self._connection.execute("UPDATE batches SET state='aborted'")
        self._connection.execute("UPDATE attempts SET state='revoked' WHERE state='issued'")
        self._connection.execute("UPDATE grants SET state='revoked' WHERE state='issued'")

    def _latch_failure(self) -> None:
        self._failed = True
        # A failed write may prevent persistence. The controller must stop all its
        # connections on abort_batch; subsequent restart also aborts every batch.
        try:
            self._connection.rollback()
            self._check_paths()
            self._connection.execute("BEGIN IMMEDIATE")
            owner = self._connection.execute(
                "SELECT ledger_id,epoch,controller_id FROM metadata WHERE singleton=1").fetchone()
            if owner != (self.ledger_id, self._epoch, self._controller_id):
                # A replacement may acquire ownership between failure and cleanup.
                # Fenced controllers must only latch/close their own connection.
                self._connection.rollback()
                self.close()
                return
            self._abort_all()
            self._connection.commit()
        except (OSError, sqlite3.Error, AdmissionDenied):
            self._rollback()

    def _rollback(self) -> None:
        try:
            self._connection.rollback()
        except sqlite3.Error:
            self._failed = True  # A failed rollback is itself terminal.

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        if self._failed:
            raise AdmissionDenied("ledger_aborted", abort=True)
        try:
            self._check_paths()
            db = self._connection
            db.execute("BEGIN IMMEDIATE")
            self._check_schema()
            owner = db.execute(
                "SELECT ledger_id,epoch,controller_id FROM metadata WHERE singleton=1").fetchone()
            if owner != (self.ledger_id, self._epoch, self._controller_id):
                raise AdmissionDenied("controller_mismatch", abort=True)
            yield db
            self._check_paths()
            db.commit()
        except AdmissionDenied as exc:
            self._rollback()
            if self._failed:
                raise AdmissionDenied("ledger_integrity_failure", abort=True) from None
            if exc.decision.outcome == "abort_batch":
                self._latch_failure()
            raise
        except (OSError, sqlite3.Error, InvalidRecord, TypeError, ValueError):
            self._latch_failure()
            raise AdmissionDenied("ledger_integrity_failure", abort=True) from None

    def register_envelope(self, envelope: BatchEnvelope, *, expected_digest: str,
                          approval_reference: str) -> None:
        """Both expected values MUST come independently from trusted human approval."""
        with self._transaction() as db:
            if (type(envelope) is not BatchEnvelope or envelope.digest != expected_digest or
                    envelope.approval_reference != approval_reference):
                raise AdmissionDenied("approval_mismatch", abort=True)
            if db.execute("SELECT 1 FROM batches WHERE batch_id=?", (envelope.batch_id,)).fetchone():
                raise AdmissionDenied("envelope_already_registered")
            db.execute("INSERT INTO batches VALUES (?,?,?,'active')",
                       (envelope.batch_id, envelope.canonical_bytes().decode("ascii"), expected_digest))

    def _envelope(self, batch_id: str) -> BatchEnvelope:
        row = self._connection.execute(
            "SELECT envelope,digest,state FROM batches WHERE batch_id=?", (batch_id,)).fetchone()
        if row is None:
            raise AdmissionDenied("unknown_batch")
        if row[2] != "active":
            raise AdmissionDenied("batch_aborted")
        envelope = BatchEnvelope.from_json(row[0])
        if envelope.digest != row[1] or envelope.batch_id != batch_id:
            raise AdmissionDenied("ledger_corrupt", abort=True)
        return envelope

    def issue(self, submission: PlanSubmission, assessment: Assessment | None, *,
              now: str) -> Grant | Decision:
        with self._transaction() as db:
            if type(submission) is not PlanSubmission:
                return Decision("block_task", ("invalid_record",))
            submission.__post_init__()
            envelope = self._envelope(submission.batch_id)
            if submission.controller_instance_id != self._controller_id:
                raise AdmissionDenied("controller_mismatch", abort=True)
            if db.execute("SELECT 1 FROM attempts WHERE attempt_id=?",
                          (submission.attempt_id,)).fetchone():
                return Decision("block_task", ("duplicate_attempt",))
            counts = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(task_id=?),0),COALESCE(SUM(tokens),0),"
                "COALESCE(SUM(aiu),0),COALESCE(SUM(seconds),0) FROM attempts WHERE batch_id=?",
                (submission.task_id, submission.batch_id)).fetchone()
            if counts[0] >= envelope.max_attempts or counts[1] >= envelope.max_attempts_per_task:
                return Decision("block_task", ("attempt_limit_exceeded",))
            decision = evaluate(envelope, submission, assessment, now=now)
            if decision.outcome == "abort_batch":
                self._abort_batch(submission.batch_id)
                return decision
            budget = submission.budget
            if any(used + requested > limit for used, requested, limit in zip(
                    counts[2:], (budget.tokens, budget.aiu, budget.seconds),
                    (envelope.budget.tokens, envelope.budget.aiu, envelope.budget.seconds))):
                decision = Decision("block_task", ("budget_exceeded",))
            eligible = decision.outcome == "eligible"
            db.execute("INSERT INTO attempts VALUES (?,?,?,?,?,?,?)",
                       (submission.attempt_id, submission.batch_id, submission.task_id,
                        "issued" if eligible else "blocked",
                        budget.tokens if eligible else 0, budget.aiu if eligible else 0,
                        budget.seconds if eligible else 0))
            if not eligible:
                return decision
            grant = Grant(secrets.token_hex(32), submission, submission.digest, now,
                          expires_at(now, min(envelope.grant_ttl_seconds, budget.seconds),
                                     envelope.valid_until), "issued")
            # The eventual receipt encloses the same submission plus ledger ID.
            # UTC wire timestamps have fixed width, so reserve its encoded size
            # before issuance; failure rolls back the attempt as well as the grant.
            AdmissionReceipt(self.ledger_id, grant.grant_id, submission,
                             submission.digest, now, grant.expires_at)
            db.execute("INSERT INTO grants VALUES (?,?,?,?,?,'issued',NULL)",
                       (grant.grant_id, submission.attempt_id, submission.digest,
                        grant.canonical_bytes().decode("ascii"),
                        assessment.canonical_bytes().decode("ascii")))
            return grant

    def consume(self, grant_id: str, *, current_binding: PlanSubmission,
                now: str) -> AdmissionReceipt:
        with self._transaction() as db:
            identifier(grant_id)
            row = db.execute(
                "SELECT record,state,attempt_id,submission_digest,assessment,receipt "
                "FROM grants WHERE grant_id=?", (grant_id,)).fetchone()
            if row is None:
                raise AdmissionDenied("unknown_grant")
            if row[1] != "issued":
                raise AdmissionDenied("grant_not_issued")
            grant = Grant.from_json(row[0])
            submission = grant.submission
            if (grant.grant_id != grant_id or row[2] != submission.attempt_id or
                    row[3] != submission.digest or row[5] is not None):
                raise AdmissionDenied("ledger_corrupt", abort=True)
            envelope = self._envelope(submission.batch_id)
            if (type(current_binding) is not PlanSubmission or current_binding != submission or
                    current_binding.digest != grant.submission_digest):
                raise AdmissionDenied("current_binding_mismatch", abort=True)
            if submission.controller_instance_id != self._controller_id:
                raise AdmissionDenied("controller_mismatch", abort=True)
            current_time = timestamp(now)
            if not (timestamp(grant.issued_at) <= current_time < timestamp(grant.expires_at) and
                    timestamp(envelope.valid_from) <= current_time < timestamp(envelope.valid_until)):
                raise AdmissionDenied("grant_expired")
            attempt = db.execute(
                "SELECT state,batch_id,task_id,tokens,aiu,seconds FROM attempts WHERE attempt_id=?",
                (submission.attempt_id,)).fetchone()
            if attempt != ("issued", submission.batch_id, submission.task_id,
                           submission.budget.tokens, submission.budget.aiu,
                           submission.budget.seconds):
                raise AdmissionDenied("attempt_binding_mismatch", abort=True)
            assessment = Assessment.from_json(row[4])
            if (evaluate(envelope, submission, assessment, now=now).outcome != "eligible" or
                    grant.expires_at != expires_at(
                        grant.issued_at,
                        min(envelope.grant_ttl_seconds, submission.budget.seconds),
                        envelope.valid_until)):
                raise AdmissionDenied("ledger_corrupt", abort=True)
            receipt = AdmissionReceipt(self.ledger_id, grant_id, submission,
                                       submission.digest, now, grant.expires_at)
            updated = db.execute(
                "UPDATE grants SET state='consumed',receipt=? WHERE grant_id=? AND state='issued'",
                (receipt.canonical_bytes().decode("ascii"), grant_id))
            if updated.rowcount != 1:
                raise AdmissionDenied("grant_not_issued")
            db.execute("UPDATE attempts SET state='consumed' WHERE attempt_id=?",
                       (submission.attempt_id,))
            return receipt  # context manager commits BEFORE the caller sees this.

    def invalidate_attempt(self, attempt_id: str, *, reason: str) -> None:
        with self._transaction() as db:
            identifier(attempt_id)
            identifier(reason)  # Never persist arbitrary exception/diagnostic text.
            if not db.execute("SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone():
                raise AdmissionDenied("unknown_attempt")
            db.execute("UPDATE attempts SET state='revoked' WHERE attempt_id=?", (attempt_id,))
            db.execute("UPDATE grants SET state='revoked' WHERE attempt_id=?", (attempt_id,))

    def _abort_batch(self, batch_id: str) -> None:
        db = self._connection
        db.execute("UPDATE batches SET state='aborted' WHERE batch_id=?", (batch_id,))
        db.execute("UPDATE attempts SET state='revoked' WHERE batch_id=?", (batch_id,))
        db.execute("UPDATE grants SET state='revoked' WHERE attempt_id IN "
                   "(SELECT attempt_id FROM attempts WHERE batch_id=?)", (batch_id,))

    def abort_batch(self, batch_id: str, *, reason: str) -> None:
        with self._transaction() as db:
            identifier(batch_id)
            identifier(reason)
            if not db.execute("SELECT 1 FROM batches WHERE batch_id=?", (batch_id,)).fetchone():
                raise AdmissionDenied("unknown_batch")
            self._abort_batch(batch_id)
