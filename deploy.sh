#!/usr/bin/env bash
# deploy.sh — Build e push para Azure Container Registry (ACR)
# Uso: ./deploy.sh [tag]  (padrão: latest)
#
# Pré-requisitos:
#   - az login + az acr login --name hvacbemolregistry
#   - docker buildx com suporte a linux/amd64 (máquina ARM64 → emulação)
#
# IMPORTANTE: build do frontend é nativo (fora do Docker) para evitar
# problemas de emulação ARM64→AMD64 no npm install.

set -euo pipefail

ACR="hvacbemolregistry.azurecr.io"
RG="RGDIROPERACIONAL"
BACKEND_APP="hvac-bemol-monitor"
FRONTEND_APP="hvac-bemol-frontend"
TAG="${1:-latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════════╗"
echo "║  HVAC Monitor — Deploy → ACR  (tag: ${TAG})  "
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Login ACR ───────────────────────────────────────────────────────────────
echo "▶ [1/5] ACR login..."
az acr login --name hvacbemolregistry

# ── 2. Frontend: build nativo ──────────────────────────────────────────────────
echo "▶ [2/5] Frontend: npm ci + build (nativo)..."
cd "${SCRIPT_DIR}/frontend"
npm ci --silent
npm run build
echo "    dist gerado: $(du -sh dist | cut -f1)"

# ── 3. Frontend: Docker push ───────────────────────────────────────────────────
echo "▶ [3/5] Frontend: docker buildx push (linux/amd64)..."
docker buildx build \
  --platform linux/amd64 \
  --tag "${ACR}/hvac-frontend:${TAG}" \
  --tag "${ACR}/hvac-frontend:$(date +%Y%m%d)" \
  --push \
  .

# ── 4. Backend: Docker push ────────────────────────────────────────────────────
echo "▶ [4/5] Backend: docker buildx push (linux/amd64)..."
cd "${SCRIPT_DIR}/backend"
docker buildx build \
  --platform linux/amd64 \
  --tag "${ACR}/hvac-backend:${TAG}" \
  --tag "${ACR}/hvac-backend:$(date +%Y%m%d)" \
  --push \
  .

# ── 5. Atualizar Azure App Services ───────────────────────────────────────────
echo "▶ [5/5] Atualizando Azure App Services..."
az webapp config container set \
  --resource-group "${RG}" \
  --name "${BACKEND_APP}" \
  --docker-custom-image-name "${ACR}/hvac-backend:${TAG}" \
  --docker-registry-server-url "https://${ACR}"

az webapp config container set \
  --resource-group "${RG}" \
  --name "${FRONTEND_APP}" \
  --docker-custom-image-name "${ACR}/hvac-frontend:${TAG}" \
  --docker-registry-server-url "https://${ACR}"

# Reiniciar para aplicar nova imagem
az webapp restart --resource-group "${RG}" --name "${BACKEND_APP}"
az webapp restart --resource-group "${RG}" --name "${FRONTEND_APP}"

echo ""
echo "✓ Deploy concluído — tag: ${TAG}"
echo ""
echo "Imagens publicadas:"
echo "  ${ACR}/hvac-backend:${TAG}"
echo "  ${ACR}/hvac-frontend:${TAG}"
echo ""
echo "URLs:"
echo "  Backend:  https://${BACKEND_APP}.azurewebsites.net/api/v1/health"
echo "  Frontend: https://${FRONTEND_APP}.azurewebsites.net"
