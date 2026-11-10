FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY schema.cypher rules.yaml ./
COPY app ./app

# Run as a non-root user.
RUN useradd --create-home fraudmesh && mkdir -p /app/data && chown fraudmesh /app/data
USER fraudmesh

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
