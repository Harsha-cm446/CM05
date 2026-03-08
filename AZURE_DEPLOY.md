# Azure Container Apps Deployment Guide

## Architecture Overview

```
GitHub (push to main)
    │
    ▼
GitHub Actions CI/CD
    │
    ├── Build backend Docker image  ──► Azure Container Registry
    ├── Build frontend Docker image ──► Azure Container Registry
    │
    ▼
Azure Container Apps (pay-per-use)
    ├── ai-interview-backend  (FastAPI, port 8000)  — scales to 0
    ├── ai-interview-frontend (Nginx+React, port 80) — scales to 0
    │
    ▼
MongoDB Atlas (free M0 cluster)
```

**Why Container Apps?**
- **Scale to zero** — no charges when idle (perfect for $100 student credit)
- **Per-second billing** — only pay when containers are running
- **Built-in HTTPS** — free TLS certificates
- **Estimated cost**: ~$3-8/month with moderate usage

---

## Prerequisites

1. **Azure Student Account** with $100 credit → [azure.microsoft.com/free/students](https://azure.microsoft.com/en-us/free/students/)
2. **GitHub Account** with your code pushed to a repository
3. **MongoDB Atlas** free cluster → [mongodb.com/atlas](https://www.mongodb.com/atlas) (free M0 tier, no Azure cost)
4. **Azure CLI** installed locally → [Install Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli)

---

## Step-by-Step Deployment

### STEP 1: Create MongoDB Atlas Free Cluster

1. Go to [MongoDB Atlas](https://www.mongodb.com/atlas) → Create free account
2. Create a **Free Shared Cluster (M0)** — choose Azure / Central India region
3. Under **Database Access** → Add a database user (username + password)
4. Under **Network Access** → Add IP Address → **Allow Access from Anywhere** (`0.0.0.0/0`)
5. Click **Connect** → **Drivers** → Copy the connection string:
   ```
   mongodb+srv://<username>:<password>@cluster0.xxxxx.mongodb.net/?retryWrites=true&w=majority
   ```
   Replace `<username>` and `<password>` with your actual credentials.

---

### STEP 2: Create Azure Service Principal (for GitHub Actions)

Open a terminal and run:

```bash
# Login to Azure
az login

# Create a service principal with Contributor role
az ad sp create-for-rbac \
  --name "ai-interview-github-actions" \
  --role contributor \
  --scopes /subscriptions/<YOUR_SUBSCRIPTION_ID> \
  --sdk-auth
```

> **Find your subscription ID**: Run `az account show --query id -o tsv`

This outputs a JSON block — **copy the entire JSON output**. You'll need it in the next step.

---

### STEP 3: Add GitHub Secrets

Go to your GitHub repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these secrets:

| Secret Name | Value |
|---|---|
| `AZURE_CREDENTIALS` | The full JSON from Step 2 |
| `MONGODB_URL` | Your MongoDB Atlas connection string from Step 1 |
| `JWT_SECRET_KEY` | A random string (run `openssl rand -hex 32` to generate) |
| `GEMINI_API_KEY` | Your primary Google Gemini API key |
| `GEMINI_FALLBACK_API_KEYS` | Comma-separated fallback Gemini keys from other accounts |
| `SMTP_HOST` | SMTP server hostname (e.g. `smtp.gmail.com`) |
| `SMTP_PORT` | SMTP port (e.g. `587`) |
| `SMTP_USER` | SMTP username / email address |
| `SMTP_PASSWORD` | SMTP password or app password |
| `EMAIL_FROM` | Sender email (e.g. `noreply@yourdomain.com`) |
| `BACKEND_FQDN` | *(Set after Step 4 — leave empty for now)* |

---

### STEP 4: Run Infrastructure Setup

1. Go to your GitHub repo → **Actions** tabaz --versionaz --versionaz --version
2. Click **"Setup Azure Infrastructure"** workflow on the left
3. Click **"Run workflow"** → **"Run workflow"** (green button)
4. Wait ~3-5 minutes for it to complete
5. Open the workflow run → Expand **"Get Application URLs"** step
6. Note the two URLs:
   ```
   Backend URL:  https://ai-interview-backend.<random>.centralindia.azurecontainerapps.io
   Frontend URL: https://ai-interview-frontend.<random>.centralindia.azurecontainerapps.io
   ```

---

### STEP 5: Configure URLs (Post-Setup)

After infrastructure is created, do these one-time steps:

#### 5a. Add BACKEND_FQDN to GitHub Secrets
Go back to GitHub → Settings → Secrets → Add:
- **Name**: `BACKEND_FQDN`
- **Value**: `ai-interview-backend.<random>.centralindia.azurecontainerapps.io` (without `https://`)

#### 5b. Update Backend Environment Variables
Run in your terminal:

```bash
az login

# Get Frontend URL
FRONTEND_URL=$(az containerapp show \
  --name ai-interview-frontend \
  --resource-group ai-interview-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)

# Update backend with correct frontend URL
az containerapp update \
  --name ai-interview-backend \
  --resource-group ai-interview-rg \
  --set-env-vars \
    FRONTEND_URL=https://$FRONTEND_URL \
    PUBLIC_URL=https://$FRONTEND_URL
```

---

### STEP 6: Deploy Your Application

Now trigger the actual deployments:

1. Go to **Actions** → **"Deploy Backend to Azure Container Apps"** → **Run workflow**
2. Go to **Actions** → **"Deploy Frontend to Azure Container Apps"** → **Run workflow**

Or simply push code changes to the `main` branch — the workflows auto-trigger when:
- Backend files change → backend redeploys
- Frontend files change → frontend redeploys

---

### STEP 7: Verify Deployment

1. Open the **Backend URL** in your browser → Add `/docs` to see the FastAPI Swagger UI:
   ```
   https://ai-interview-backend.<random>.centralindia.azurecontainerapps.io/docs
   ```

2. Open the **Frontend URL**:
   ```
   https://ai-interview-frontend.<random>.centralindia.azurecontainerapps.io
   ```

---

## Cost Breakdown (Student $100 Credit)

| Resource | Cost | Notes |
|---|---|---|
| **Container Apps - Backend** | ~$0/idle, ~$0.05/hr active | Scales to 0 when no traffic |
| **Container Apps - Frontend** | ~$0/idle, ~$0.01/hr active | Scales to 0 when no traffic |
| **Container Registry (Basic)** | ~$5/month | Stores Docker images |
| **MongoDB Atlas M0** | **Free** | 512 MB, hosted on MongoDB's infra |
| **HTTPS / Ingress** | **Free** | Built into Container Apps |
| **GitHub Actions** | **Free** | 2000 min/month for free tier |

**Estimated monthly**: **$5-10** (mostly ACR). Your $100 credit lasts **10-20 months**.

---

## Continuous Deployment Flow

```
Developer pushes to main branch
         │
         ▼
GitHub detects file changes
         │
    ┌────┴────┐
    │         │
backend/**   frontend/**
changed?     changed?
    │         │
    ▼         ▼
Build &     Build &
Push to     Push to
ACR         ACR
    │         │
    ▼         ▼
Update      Update
Container   Container
App         App
    │         │
    ▼         ▼
Live in     Live in
~2 min      ~1 min
```

---

## Useful Commands

```bash
# Check app status
az containerapp show --name ai-interview-backend --resource-group ai-interview-rg --query "properties.runningStatus"

# View logs (live)
az containerapp logs show --name ai-interview-backend --resource-group ai-interview-rg --follow

# Restart app
az containerapp revision restart --name ai-interview-backend --resource-group ai-interview-rg

# Update environment variable
az containerapp update --name ai-interview-backend --resource-group ai-interview-rg --set-env-vars KEY=VALUE

# Scale manually (if needed)
az containerapp update --name ai-interview-backend --resource-group ai-interview-rg --min-replicas 1 --max-replicas 2

# View all container apps
az containerapp list --resource-group ai-interview-rg -o table

# DELETE everything when done (stops all billing!)
az group delete --name ai-interview-rg --yes --no-wait
```

---

## Troubleshooting

### App shows "Quickstart" page
The infrastructure setup uses a placeholder image. Run the deploy workflows (Step 6) to push your actual code.

### Backend can't connect to MongoDB
- Check that `MONGODB_URL` secret is correct (includes username:password)
- In MongoDB Atlas → Network Access → Ensure `0.0.0.0/0` is allowed

### Frontend shows blank page / API errors
- Ensure `BACKEND_FQDN` GitHub secret is set (Step 5a)
- Redeploy frontend after setting the secret

### Container App keeps restarting
- Check logs: `az containerapp logs show --name ai-interview-backend --resource-group ai-interview-rg`
- Common cause: missing environment variables

### Scale-to-zero cold start
- First request after idle may take 20-30 seconds (container starting)
- Set `--min-replicas 1` to keep one instance always running (costs more)

---

## Customization

### Change ACR Name
The ACR name (`aiinterviewacr`) must be globally unique. If it's taken, update the `ACR_NAME` env variable in all three workflow files:
- `.github/workflows/setup-azure.yml`
- `.github/workflows/deploy-backend.yml`
- `.github/workflows/deploy-frontend.yml`

### Change Azure Region
Update `LOCATION` in `setup-azure.yml`. Cheapest options:
- `centralindia` — India
- `eastus` — US East
- `westeurope` — Europe

### Custom Domain
```bash
az containerapp hostname add \
  --name ai-interview-frontend \
  --resource-group ai-interview-rg \
  --hostname your-domain.com
```
