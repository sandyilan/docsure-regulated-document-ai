# DocSure Helm Scaffold

This chart is a learning scaffold for deploying the DocSure API and Streamlit dashboard to Kubernetes.

Before using it beyond a local cluster, replace the `emptyDir` SQLite storage with a managed database, add persistent storage where appropriate, configure an ingress, set resource limits, use a private image registry, and connect a secured Ollama or approved model service.

Example local render command:

```powershell
helm template docsure .
```

Example installation command after building and publishing an image:

```powershell
helm upgrade --install docsure . --set image.repository=YOUR_IMAGE --set image.tag=YOUR_TAG
```
