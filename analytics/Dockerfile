# kora-analytics — its own image, its own dependencies.
#
# Nothing from ../backend or ../frontend is copied in. The build context is this
# directory alone, so the service cannot quietly grow a dependency on the
# product's code and lose the independence it was separated out to have.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# Cloud Run supplies $PORT and it is not always 8080. Binding a literal would
# work locally and fail in the one environment that matters.
ENV PORT=8080
EXPOSE 8080

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
