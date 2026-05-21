# ====================================================================
# SOLEV — Dockerfile para deploy em Railway / Cloud
# ====================================================================
# Usa imagem oficial do Playwright (já vem com Chromium + Linux + libs)
# Tamanho final: ~1.5GB (mas só na build, não pesa em runtime)
# ====================================================================
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

# Dependências do sistema (caso falte algo)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Instala dependências Python primeiro (cache de layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o restante do código
COPY . .

# Porta exposta (Railway atribui via $PORT, mas usamos 8080 como default)
ENV PORT=8080
EXPOSE 8080

# Healthcheck simples
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/ping || exit 1

# Start: gunicorn com 2 workers, timeout maior pra geração de PDF
CMD gunicorn --workers 2 --bind 0.0.0.0:${PORT} --timeout 120 --access-logfile - app:app
