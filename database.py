import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


DATABASE_PATH = Path(
    os.getenv(
        "DOCSURE_DB_PATH",
        str(Path(__file__).with_name("docsure.db")),
    )
)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    connection = get_connection()

    try:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                name TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                document_type TEXT NOT NULL DEFAULT 'unknown',
                raw_text TEXT NOT NULL,
                extracted_json TEXT NOT NULL DEFAULT '{}',
                confidence REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'uploaded',
                uploaded_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reviews (
                review_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                reviewer_id TEXT NOT NULL,
                decision TEXT NOT NULL,
                corrected_json TEXT NOT NULL DEFAULT '{}',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES documents(document_id)
            );

            CREATE TABLE IF NOT EXISTS audit_events (
                event_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                document_id TEXT,
                details_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )

        demo_users = [
            (
                "USR-100",
                "northstar-health",
                "Asha Analyst",
                "analyst",
            ),
            (
                "USR-101",
                "northstar-health",
                "Ravi Reviewer",
                "reviewer",
            ),
            (
                "USR-102",
                "northstar-health",
                "Mina Compliance Admin",
                "admin",
            ),
            (
                "USR-200",
                "harbor-clinic",
                "Leo Analyst",
                "analyst",
            ),
        ]

        connection.executemany(
            """
            INSERT OR IGNORE INTO users (user_id, tenant_id, name, role)
            VALUES (?, ?, ?, ?)
            """,
            demo_users,
        )

        connection.commit()

    finally:
        connection.close()


def row_to_dict(row):
    return dict(row) if row is not None else None


def get_user(user_id):
    connection = get_connection()

    try:
        row = connection.execute(
            "SELECT * FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row_to_dict(row)

    finally:
        connection.close()


def list_users():
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT user_id, tenant_id, name, role
            FROM users
            ORDER BY tenant_id, role, name
            """
        ).fetchall()
        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


def create_audit_event(
    tenant_id,
    actor_id,
    event_type,
    document_id=None,
    details=None,
):
    event = {
        "event_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "actor_id": actor_id,
        "event_type": event_type,
        "document_id": document_id,
        "details_json": json.dumps(details or {}),
        "created_at": now_utc(),
    }

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO audit_events (
                event_id, tenant_id, actor_id, event_type,
                document_id, details_json, created_at
            )
            VALUES (
                :event_id, :tenant_id, :actor_id, :event_type,
                :document_id, :details_json, :created_at
            )
            """,
            event,
        )
        connection.commit()
        return event

    finally:
        connection.close()


def create_document(
    tenant_id,
    filename,
    raw_text,
    uploaded_by,
):
    document = {
        "document_id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "filename": filename,
        "raw_text": raw_text,
        "uploaded_by": uploaded_by,
        "created_at": now_utc(),
    }

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO documents (
                document_id, tenant_id, filename, raw_text,
                uploaded_by, created_at
            )
            VALUES (
                :document_id, :tenant_id, :filename, :raw_text,
                :uploaded_by, :created_at
            )
            """,
            document,
        )
        connection.commit()

    finally:
        connection.close()

    return document


def get_document(document_id, tenant_id):
    connection = get_connection()

    try:
        row = connection.execute(
            """
            SELECT * FROM documents
            WHERE document_id = ? AND tenant_id = ?
            """,
            (document_id, tenant_id),
        ).fetchone()

        document = row_to_dict(row)

        if document is not None:
            document["extracted_fields"] = json.loads(
                document.pop("extracted_json")
            )

        return document

    finally:
        connection.close()


def list_documents(tenant_id):
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT
                document_id,
                filename,
                document_type,
                confidence,
                status,
                uploaded_by,
                created_at
            FROM documents
            WHERE tenant_id = ?
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        ).fetchall()

        return [row_to_dict(row) for row in rows]

    finally:
        connection.close()


def save_extraction(
    document_id,
    tenant_id,
    document_type,
    extracted_fields,
    confidence,
    status,
):
    connection = get_connection()

    try:
        connection.execute(
            """
            UPDATE documents
            SET
                document_type = ?,
                extracted_json = ?,
                confidence = ?,
                status = ?
            WHERE document_id = ? AND tenant_id = ?
            """,
            (
                document_type,
                json.dumps(extracted_fields),
                confidence,
                status,
                document_id,
                tenant_id,
            ),
        )
        connection.commit()

    finally:
        connection.close()


def save_review(
    document_id,
    reviewer_id,
    decision,
    corrected_fields,
    notes,
):
    review = {
        "review_id": str(uuid.uuid4()),
        "document_id": document_id,
        "reviewer_id": reviewer_id,
        "decision": decision,
        "corrected_json": json.dumps(corrected_fields),
        "notes": notes,
        "created_at": now_utc(),
    }

    connection = get_connection()

    try:
        connection.execute(
            """
            INSERT INTO reviews (
                review_id, document_id, reviewer_id, decision,
                corrected_json, notes, created_at
            )
            VALUES (
                :review_id, :document_id, :reviewer_id, :decision,
                :corrected_json, :notes, :created_at
            )
            """,
            review,
        )

        connection.execute(
            """
            UPDATE documents
            SET
                extracted_json = ?,
                status = ?
            WHERE document_id = ?
            """,
            (
                json.dumps(corrected_fields),
                "review_approved" if decision == "approved" else "needs_changes",
                document_id,
            ),
        )

        connection.commit()

    finally:
        connection.close()

    return review


def list_audit_events(tenant_id):
    connection = get_connection()

    try:
        rows = connection.execute(
            """
            SELECT *
            FROM audit_events
            WHERE tenant_id = ?
            ORDER BY created_at DESC
            """,
            (tenant_id,),
        ).fetchall()

        events = []

        for row in rows:
            event = row_to_dict(row)
            event["details"] = json.loads(event.pop("details_json"))
            events.append(event)

        return events

    finally:
        connection.close()
