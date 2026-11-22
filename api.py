import io
import json
import logging
import os
import re
from typing import Literal

import fitz
import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from database import (
    create_audit_event,
    create_document,
    get_document,
    get_user,
    initialize_database,
    list_audit_events,
    list_documents,
    list_users,
    save_extraction,
    save_review,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("docsure")

app = FastAPI(
    title="DocSure",
    description="Local demo of a regulated-document review platform.",
)

MAX_FILE_SIZE = 5 * 1024 * 1024
REVIEW_THRESHOLD = 0.85


class ExtractedDocument(BaseModel):
    document_type: Literal["invoice", "claim", "medical_record", "other"]
    document_number: str | None = None
    subject_name: str | None = None
    document_date: str | None = None
    amount: str | None = None
    summary: str


class ReviewRequest(BaseModel):
    decision: Literal["approved", "needs_changes"]
    corrected_fields: dict
    notes: str = ""


def require_user(user_id, allowed_roles=None):
    user = get_user(user_id)

    if user is None:
        raise HTTPException(status_code=401, detail="Unknown demo user.")

    if allowed_roles and user["role"] not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail="Your role is not allowed to perform this action.",
        )

    return user


def extract_pdf_text(file_bytes):
    document = fitz.open(stream=file_bytes, filetype="pdf")

    try:
        pages = [page.get_text() for page in document]
        return "\n".join(pages).strip()
    finally:
        document.close()


def fallback_extraction(text):
    """Predictable fallback when the local AI model is unavailable."""
    lower_text = text.lower()

    if "invoice" in lower_text:
        document_type = "invoice"
    elif "claim" in lower_text:
        document_type = "claim"
    elif "patient" in lower_text or "medical" in lower_text:
        document_type = "medical_record"
    else:
        document_type = "other"

    def first_match(patterns):
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)

            if match:
                return match.group(1).strip()

        return None

    document_number = first_match(
        [
            r"(?:invoice|claim|document)\s*(?:number|no\.?|id)?\s*[:#-]\s*([A-Z0-9-]+)",
        ]
    )

    subject_name = first_match(
        [
            r"(?:patient|customer|member|name)\s*[:#-]\s*([A-Za-z .'-]+)",
        ]
    )

    document_date = first_match(
        [
            r"(?:date|issued)\s*[:#-]\s*(\d{4}-\d{2}-\d{2})",
            r"(?:date|issued)\s*[:#-]\s*(\d{1,2}/\d{1,2}/\d{4})",
        ]
    )

    amount = first_match(
        [
            r"(?:total|amount|balance)\s*[:#-]?\s*(\$?\s?\d+(?:\.\d{2})?)",
        ]
    )

    return {
        "document_type": document_type,
        "document_number": document_number,
        "subject_name": subject_name,
        "document_date": document_date,
        "amount": amount,
        "summary": "Fields were extracted using the local fallback rules.",
    }


def call_local_ai(text):
    """Use Ollama for structured extraction. Falls back safely if unavailable."""
    schema = ExtractedDocument.model_json_schema()

    prompt = f"""
Extract structured fields from this document text.

Rules:
- Do not invent missing values. Use null if a value is absent.
- Document date should be YYYY-MM-DD when possible.
- Amount should include the currency symbol when present.
- Keep the summary to one sentence.

Document text:
{text[:12000]}
"""

    try:
        response = requests.post(
            f'{os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/")}/api/chat',
            json={
                "model": os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a careful document extraction assistant. "
                            "Return only structured data that matches the schema."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                "format": schema,
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=60,
        )
        response.raise_for_status()

        content = response.json().get("message", {}).get("content", "")
        extracted = ExtractedDocument.model_validate(json.loads(content))
        return extracted.model_dump(), True

    except (
        requests.RequestException,
        ValueError,
        KeyError,
    ) as error:
        logger.warning(
            "local_extraction_unavailable error_type=%s",
            type(error).__name__,
        )
        return fallback_extraction(text), False


def calculate_confidence(fields, ai_used, raw_text):
    important_fields = [
        "document_number",
        "subject_name",
        "document_date",
        "amount",
    ]

    present_count = sum(bool(fields.get(field)) for field in important_fields)
    confidence = 0.30 + (present_count * 0.15)

    if fields.get("document_type") != "other":
        confidence += 0.05

    if ai_used:
        confidence += 0.05

    # Never let a model-created value bypass an explicit source warning.
    # In production, this would be extended with field-level provenance checks.
    if "pending verification" in raw_text.lower():
        confidence = min(confidence, 0.65)

    return round(min(confidence, 0.95), 2)


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "DocSure",
        "review_threshold": REVIEW_THRESHOLD,
    }


@app.get("/users")
def users():
    """
    Demo-only identity list for the dashboard.
    A production platform would use SSO instead.
    """
    return {"items": list_users()}


@app.post("/documents/upload")
async def upload_document(
    user_id: str,
    file: UploadFile = File(...),
):
    user = require_user(user_id, ["analyst", "reviewer", "admin"])

    filename = file.filename or "unnamed-document"
    extension = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""

    if extension not in {"pdf", "txt"}:
        raise HTTPException(
            status_code=400,
            detail="Only PDF and TXT files are supported in this demo.",
        )

    file_bytes = await file.read()

    if len(file_bytes) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=400,
            detail="File is larger than the 5 MB demo limit.",
        )

    try:
        if extension == "pdf":
            raw_text = extract_pdf_text(file_bytes)
        else:
            raw_text = file_bytes.decode("utf-8-sig").strip()
    except (UnicodeDecodeError, fitz.FileDataError) as error:
        raise HTTPException(
            status_code=400,
            detail="The document could not be read.",
        ) from error

    if not raw_text:
        raise HTTPException(
            status_code=400,
            detail=(
                "No readable text was found. This MVP supports text PDFs; "
                "scanned-image OCR is a future improvement."
            ),
        )

    document = create_document(
        tenant_id=user["tenant_id"],
        filename=filename,
        raw_text=raw_text,
        uploaded_by=user["user_id"],
    )

    create_audit_event(
        tenant_id=user["tenant_id"],
        actor_id=user["user_id"],
        event_type="document_uploaded",
        document_id=document["document_id"],
        details={"filename": filename},
    )

    extracted_fields, ai_used = call_local_ai(raw_text)
    confidence = calculate_confidence(extracted_fields, ai_used, raw_text)
    status = (
        "requires_review"
        if confidence < REVIEW_THRESHOLD
        else "extracted"
    )

    save_extraction(
        document_id=document["document_id"],
        tenant_id=user["tenant_id"],
        document_type=extracted_fields["document_type"],
        extracted_fields=extracted_fields,
        confidence=confidence,
        status=status,
    )

    create_audit_event(
        tenant_id=user["tenant_id"],
        actor_id=user["user_id"],
        event_type="fields_extracted",
        document_id=document["document_id"],
        details={
            "ai_used": ai_used,
            "confidence": confidence,
            "requires_review": status == "requires_review",
        },
    )

    saved_document = get_document(
        document["document_id"],
        user["tenant_id"],
    )

    return {
        "message": "Document uploaded and processed.",
        "document": saved_document,
        "ai_used": ai_used,
        "requires_review": status == "requires_review",
    }


@app.get("/documents")
def documents(user_id: str):
    user = require_user(user_id)
    return {
        "items": list_documents(user["tenant_id"]),
        "tenant_id": user["tenant_id"],
    }


@app.get("/review-queue")
def review_queue(user_id: str):
    user = require_user(user_id, ["reviewer", "admin"])

    documents_needing_review = [
        document
        for document in list_documents(user["tenant_id"])
        if document["status"] == "requires_review"
    ]

    return {"items": documents_needing_review}


@app.get("/documents/{document_id}")
def document_details(document_id: str, user_id: str):
    user = require_user(user_id)
    document = get_document(document_id, user["tenant_id"])

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found for this tenant.",
        )

    return document


@app.post("/documents/{document_id}/review")
def review_document(
    document_id: str,
    request: ReviewRequest,
    user_id: str,
):
    user = require_user(user_id, ["reviewer", "admin"])
    document = get_document(document_id, user["tenant_id"])

    if document is None:
        raise HTTPException(
            status_code=404,
            detail="Document not found for this tenant.",
        )

    review = save_review(
        document_id=document_id,
        reviewer_id=user["user_id"],
        decision=request.decision,
        corrected_fields=request.corrected_fields,
        notes=request.notes,
    )

    create_audit_event(
        tenant_id=user["tenant_id"],
        actor_id=user["user_id"],
        event_type="document_reviewed",
        document_id=document_id,
        details={
            "decision": request.decision,
            "notes": request.notes,
        },
    )

    return {
        "message": "Review decision saved.",
        "review": review,
        "document": get_document(document_id, user["tenant_id"]),
    }


@app.get("/audit-log")
def audit_log(user_id: str):
    user = require_user(user_id, ["reviewer", "admin"])

    return {
        "tenant_id": user["tenant_id"],
        "items": list_audit_events(user["tenant_id"]),
    }
