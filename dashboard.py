import json
import os

import requests
import streamlit as st


API_URL = os.getenv("DOCSURE_API_URL", "http://127.0.0.1:8002")


def api_get(path, params=None):
    response = requests.get(
        f"{API_URL}{path}",
        params=params,
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


def api_post(path, payload=None, params=None, files=None):
    response = requests.post(
        f"{API_URL}{path}",
        json=payload,
        params=params,
        files=files,
        timeout=90,
    )
    response.raise_for_status()
    return response.json()


st.set_page_config(page_title="DocSure", page_icon="📄", layout="wide")

st.title("DocSure")
st.caption(
    "Regulated document extraction with tenant isolation, human review, "
    "and audit logging."
)

try:
    health = api_get("/health")
    st.success(
        f'Backend connected: {health["service"]} '
        f'(review threshold: {health["review_threshold"]:.0%})'
    )
except requests.RequestException:
    st.error(
        "The DocSure API is unavailable. Start it on port 8002 before "
        "opening this dashboard."
    )
    st.stop()

try:
    users = api_get("/users")["items"]
except requests.RequestException as error:
    st.error(f"Could not load demo users: {error}")
    st.stop()

user_labels = {
    user["user_id"]: (
        f'{user["name"]} — {user["role"]} '
        f'({user["tenant_id"]})'
    )
    for user in users
}

selected_user_id = st.selectbox(
    "Demo identity",
    options=list(user_labels),
    format_func=lambda user_id: user_labels[user_id],
)

active_user = next(
    user for user in users if user["user_id"] == selected_user_id
)

metric_one, metric_two, metric_three = st.columns(3)

with metric_one:
    st.metric("Tenant", active_user["tenant_id"])

with metric_two:
    st.metric("Role", active_user["role"].title())

with metric_three:
    st.metric("Access", "Review allowed" if active_user["role"] in {"reviewer", "admin"} else "Upload and view")

upload_tab, documents_tab, review_tab, audit_tab = st.tabs(
    [
        "Upload document",
        "My tenant documents",
        "Review queue",
        "Audit log",
    ]
)

with upload_tab:
    st.subheader("1. Upload a regulated document")
    st.write(
        "Use synthetic PDF or TXT documents only. This local MVP supports "
        "text PDFs; scanned-image OCR is a planned improvement."
    )

    uploaded_file = st.file_uploader(
        "Choose a PDF or TXT document",
        type=["pdf", "txt"],
    )

    if uploaded_file is not None:
        st.caption(
            f"Selected: {uploaded_file.name} "
            f"({uploaded_file.size:,} bytes)"
        )

        if st.button("Extract fields and calculate confidence", type="primary"):
            files = {
                "file": (
                    uploaded_file.name,
                    uploaded_file.getvalue(),
                    uploaded_file.type,
                )
            }

            with st.spinner(
                "Extracting fields with local AI and applying review rules..."
            ):
                try:
                    result = api_post(
                        "/documents/upload",
                        params={"user_id": selected_user_id},
                        files=files,
                    )

                    document = result["document"]
                    st.success(result["message"])

                    if result["requires_review"]:
                        st.warning(
                            f'Confidence is {document["confidence"]:.0%}. '
                            "This document requires reviewer approval."
                        )
                    else:
                        st.success(
                            f'Confidence is {document["confidence"]:.0%}. '
                            "The extracted document passed the confidence threshold."
                        )

                    st.markdown("#### Extracted fields")
                    st.json(document["extracted_fields"])
                    st.caption(
                        "Local AI used"
                        if result["ai_used"]
                        else "Fallback extraction rules used"
                    )

                except requests.RequestException as error:
                    st.error(f"Upload failed: {error}")

with documents_tab:
    st.subheader("2. Documents for this tenant")

    try:
        documents = api_get(
            "/documents",
            params={"user_id": selected_user_id},
        )["items"]

        if not documents:
            st.info("No documents have been uploaded for this tenant yet.")
        else:
            st.dataframe(documents, width="stretch", hide_index=True)

            document_ids = [document["document_id"] for document in documents]
            selected_document_id = st.selectbox(
                "Inspect a document",
                options=document_ids,
                format_func=lambda document_id: next(
                    (
                        f'{document["filename"]} — {document["status"]}'
                        for document in documents
                        if document["document_id"] == document_id
                    ),
                    document_id,
                ),
            )

            details = api_get(
                f"/documents/{selected_document_id}",
                params={"user_id": selected_user_id},
            )

            st.markdown("#### Extracted fields")
            st.json(details["extracted_fields"])

            with st.expander("View extracted source text"):
                st.text(details["raw_text"])

    except requests.RequestException as error:
        st.error(f"Could not load documents: {error}")

with review_tab:
    st.subheader("3. Human review queue")

    if active_user["role"] not in {"reviewer", "admin"}:
        st.info(
            "Select Ravi Reviewer or Mina Compliance Admin to review "
            "low-confidence documents for the same tenant."
        )
    else:
        try:
            review_documents = api_get(
                "/review-queue",
                params={"user_id": selected_user_id},
            )["items"]

            if not review_documents:
                st.success("No documents currently need review.")
            else:
                review_ids = [
                    document["document_id"]
                    for document in review_documents
                ]

                review_document_id = st.selectbox(
                    "Document waiting for review",
                    options=review_ids,
                    format_func=lambda document_id: next(
                        (
                            f'{document["filename"]} '
                            f'({document["confidence"]:.0%} confidence)'
                            for document in review_documents
                            if document["document_id"] == document_id
                        ),
                        document_id,
                    ),
                )

                review_details = api_get(
                    f"/documents/{review_document_id}",
                    params={"user_id": selected_user_id},
                )

                st.markdown("#### AI-extracted values")
                st.json(review_details["extracted_fields"])

                corrected_json = st.text_area(
                    "Corrected fields (JSON)",
                    value=json.dumps(
                        review_details["extracted_fields"],
                        indent=2,
                    ),
                    height=240,
                )

                decision = st.radio(
                    "Review decision",
                    options=["approved", "needs_changes"],
                    horizontal=True,
                )

                review_notes = st.text_input(
                    "Reviewer notes",
                    value="Reviewed in the DocSure dashboard.",
                )

                if st.button("Save review decision", type="primary"):
                    try:
                        corrected_fields = json.loads(corrected_json)

                        if not isinstance(corrected_fields, dict):
                            raise ValueError(
                                "Corrected fields must be a JSON object."
                            )

                        result = api_post(
                            f"/documents/{review_document_id}/review",
                            payload={
                                "decision": decision,
                                "corrected_fields": corrected_fields,
                                "notes": review_notes,
                            },
                            params={"user_id": selected_user_id},
                        )

                        st.success(result["message"])
                        st.json(result["review"])
                        st.rerun()

                    except json.JSONDecodeError:
                        st.error(
                            "The corrected fields are not valid JSON. "
                            "Keep the opening and closing braces."
                        )
                    except ValueError as error:
                        st.error(str(error))
                    except requests.RequestException as error:
                        st.error(f"Could not save review: {error}")

        except requests.RequestException as error:
            st.error(f"Could not load review queue: {error}")

with audit_tab:
    st.subheader("4. Audit log")

    if active_user["role"] not in {"reviewer", "admin"}:
        st.info(
            "Audit-log access is restricted to reviewer and admin roles "
            "in this MVP."
        )
    else:
        try:
            audit_events = api_get(
                "/audit-log",
                params={"user_id": selected_user_id},
            )["items"]

            if audit_events:
                st.dataframe(
                    audit_events,
                    width="stretch",
                    hide_index=True,
                )
            else:
                st.info(
                    "No events yet. Upload a document to create an audit trail."
                )

        except requests.RequestException as error:
            st.error(f"Could not load audit events: {error}")
