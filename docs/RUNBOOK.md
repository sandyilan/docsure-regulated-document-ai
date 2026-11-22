# DocSure Operations Runbook

## Start locally

1. Verify Ollama is available:

   ```powershell
   ollama list
   ```

2. Start the FastAPI service:

   ```powershell
   .\.venv\Scripts\python.exe -m uvicorn api:app --reload --port 8002
   ```

3. Start the Streamlit dashboard in another terminal:

   ```powershell
   .\.venv\Scripts\python.exe -m streamlit run dashboard.py --server.port 8503
   ```

4. Verify the API at <http://127.0.0.1:8002/health>.

## Common issues

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Dashboard says API unavailable | API is not running | Start Uvicorn on port 8002. |
| Extraction uses fallback | Ollama is unavailable | Start Ollama and confirm `qwen2.5:1.5b` appears in `ollama list`. |
| PDF has no readable text | File is a scanned image | Use a text PDF for this MVP; OCR is planned future work. |
| Review queue is empty | The document confidence is above threshold | Upload the low-confidence sample file, or inspect document status. |
| Access denied | Wrong demo role | Choose Ravi Reviewer or Mina Compliance Admin for review/audit actions. |

## Operational signals to monitor in production

- Upload success/failure rate.
- Extraction latency and local-model failures.
- Percentage of documents routed to review.
- Reviewer turnaround time.
- Cross-tenant access-denied events.
- Audit-log write failures.
- Database health, backups, and storage growth.

## Incident response outline

1. Stop document ingestion if potentially sensitive data is exposed.
2. Preserve audit events and relevant logs.
3. Identify impacted tenant, documents, and users.
4. Rotate exposed secrets and revoke access if required.
5. Notify the security/compliance owner according to the customer policy.
6. Document root cause and corrective actions.
