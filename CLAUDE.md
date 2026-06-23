# CLAUDE.md - SplatTop Blog

This file provides guidance for Claude Code when working with the SplatTop Blog codebase.

## Project Overview

SplatTop Blog is a Wagtail CMS-based blog that serves as the companion blog for the SplatTop competitive Splatoon statistics platform. It follows the SplatTop visual design system (dark purple/fuchsia aesthetic).

## Tech Stack

- **Framework**: Django 5.x + Wagtail CMS
- **Database**: PostgreSQL
- **Deployment**: Kubernetes on DigitalOcean
- **Container**: Docker with Gunicorn

## Project Structure

```
SplatTopBlog/
├── src/                      # Application code
│   ├── blog/                 # Blog app (posts, index)
│   │   ├── models.py         # BlogPage, BlogIndexPage models
│   │   └── templates/blog/   # Blog templates
│   ├── home/                 # Home app
│   │   ├── models.py         # HomePage model
│   │   └── templates/home/   # Home templates
│   ├── splattopblog/         # Project settings
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── templates/            # Base templates
│   │   └── base.html         # Main template with SplatTop styles
│   ├── static/               # Static files
│   ├── media/                # User uploads
│   └── manage.py
├── docs/                     # Documentation
│   └── SplatTop_style_bible.md
├── .github/workflows/        # CI/CD
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── uv.lock
└── Makefile
```

## Code Style

### Python
- Follow PEP 8
- Use type hints where beneficial
- Keep models clean with minimal business logic

### Templates
- Use Wagtail template tags properly
- Maintain semantic HTML
- Keep styles in base.html or separate CSS files

### CSS
- Follow the SplatTop Style Bible (docs/SplatTop_style_bible.md)
- Use CSS custom properties for theming
- Dark backgrounds (#0f172a), purple accents (#ab5ab7)
- Respect `prefers-reduced-motion`

## Key Conventions

1. **StreamField Blocks**: Blog posts use StreamField with markdown, paragraph, heading, image, code, and quote blocks
2. **Image Handling**: Use Wagtail's image tags with appropriate renditions
3. **Security**: Never commit secrets, use environment variables
4. **Accessibility**: Maintain color contrast, support reduced motion

## Common Tasks

### Adding a new block type
1. Define in `src/blog/models.py` in the `body` StreamField
2. Add template handling in `src/blog/templates/blog/blog_page.html`
3. Style in `src/templates/base.html` following style bible

### Running locally
```bash
# Using Make (recommended)
make setup      # First-time setup
make dev        # Run development server

# Using Docker (with PostgreSQL)
docker-compose up
```

### Migrations
```bash
make makemigrations
make migrate
```

## Review Checklist

When reviewing PRs, check for:
- [ ] No hardcoded secrets or credentials
- [ ] Proper use of Wagtail conventions
- [ ] Template inheritance is correct
- [ ] Styles follow the SplatTop Style Bible
- [ ] Accessibility considerations (contrast, motion)
- [ ] No security vulnerabilities (XSS, SQL injection)
- [ ] Migrations are included if models changed

---

# Deployment Infrastructure (GarzAICluster)

This project deploys to Kubernetes via the `GarzAICluster` GitOps repository at `~/dev/GarzAICluster`.

## GarzAICluster Structure

```
GarzAICluster/
├── helm/
│   ├── splattop/          # Main SplatTop app (FastAPI + React)
│   ├── splatvote/         # Voting system
│   ├── splattopblog/      # This blog (to be created)
│   └── vanity-hosts/      # URL redirects
├── argocd/
│   └── applications/      # ArgoCD Application manifests
│       ├── splattop-prod.yaml
│       ├── splatvote-prod.yaml
│       └── splattopblog-prod.yaml  # (to be created)
```

## Helm Chart Pattern

Each service follows this structure:

```
helm/<service>/
├── Chart.yaml              # Chart metadata
├── values.yaml             # Development defaults (minimal, often disabled ingress)
├── values-prod.yaml        # Production overrides (enabled, TLS, resources)
└── templates/
    ├── _helpers.tpl        # Template helpers (fullname, labels, etc.)
    ├── deployment.yaml     # Kubernetes Deployment
    ├── service.yaml        # Kubernetes Service (ClusterIP)
    ├── ingress.yaml        # Ingress with nginx + cert-manager
    ├── certificate.yaml    # Let's Encrypt TLS certificate
    └── pvc.yaml            # PersistentVolumeClaim (if needed)
```

## values.yaml vs values-prod.yaml

**values.yaml** (development defaults):
```yaml
global:
  environment: development

myapp:
  enabled: true
  replicas: 1
  image:
    repository: registry.digitalocean.com/sendouq/myapp
    tag: latest
    pullPolicy: Always
  resources:
    requests:
      cpu: 100m
      memory: 256Mi

ingress:
  enabled: false  # Disabled in dev
```

**values-prod.yaml** (production overrides):
```yaml
global:
  environment: production

myapp:
  replicas: 1
  image:
    pullPolicy: IfNotPresent
  resources:
    requests:
      cpu: 200m
      memory: 512Mi

ingress:
  enabled: true
  className: nginx
  annotations:
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
  hosts:
  - host: myapp.splat.top
    paths:
    - path: /
      pathType: Prefix
      servicePort: 8000
  tls:
    enabled: true
    secretName: myapp-tls-secret
    certificate:
      enabled: true
      dnsNames:
      - myapp.splat.top
```

## ArgoCD Application Pattern

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: myapp-prod
  namespace: argocd
  finalizers:
    - resources-finalizer.argocd.argoproj.io
spec:
  project: splattop
  source:
    repoURL: https://github.com/cesaregarza/GarzAICluster.git
    targetRevision: main
    path: helm/myapp
    helm:
      valueFiles:
        - values.yaml
        - values-prod.yaml
  destination:
    server: https://kubernetes.default.svc
    namespace: myapp-prod
  syncPolicy:
    automated: null  # Manual sync
    syncOptions:
      - CreateNamespace=true
      - PrunePropagationPolicy=foreground
      - PruneLast=true
```

## Ingress & TLS

All services use nginx ingress with:
- TLS via cert-manager (`letsencrypt-prod` ClusterIssuer)
- Subdomains under `*.splat.top`
- SSL redirect enabled

Current routing:
| Domain | Service |
|--------|---------|
| `splat.top` / `comp.splat.top` | SplatTop (FastAPI + React) |
| `vote.splat.top` | SplatVote |
| `blog.splat.top` | SplatTopBlog (this project) |
| `grafana.splat.top` | Monitoring |

## Database Secrets

Services connect to managed PostgreSQL via Kubernetes secrets:
```yaml
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: blog-db-secrets
        key: DATABASE_URL
```

Create before deploying:
```bash
kubectl create secret generic blog-db-secrets \
  --namespace default \
  --from-literal=DATABASE_URL=postgresql://<user>:<password>@<host>:5432/splattopblog \
  --from-literal=DJANGO_SECRET_KEY=<secret>
```

## CI/CD Flow

1. Push to `main` → GitHub Actions builds Docker image → DO Container Registry
2. Action creates PR to GarzAICluster updating image tag
3. Merge PR → ArgoCD detects change → syncs to Kubernetes

## Template Helpers (_helpers.tpl)

Standard helpers every chart should include:
```yaml
{{- define "myapp.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "myapp.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "myapp.labels" -}}
helm.sh/chart: {{ include "myapp.chart" . }}
{{ include "myapp.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "myapp.selectorLabels" -}}
app.kubernetes.io/name: {{ include "myapp.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
```
