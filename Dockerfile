FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

ENV PATCHDECK_DATA_DIR=/data
EXPOSE 8000

CMD ["uvicorn", "patchdeck.main:app", "--host", "0.0.0.0", "--port", "8000"]

