FROM python:3.11-slim

WORKDIR /app

# Instala as dependências do projeto (declaradas em pyproject.toml).
COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

EXPOSE 8000

# Render/Cloud injeta $PORT; localmente cai para 8000. Shell form para expandir a env.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
