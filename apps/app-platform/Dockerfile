FROM python:3.12-slim
WORKDIR /app

# Build context is repo root in DO App Platform when dockerfile_path is nested.
COPY apps/app-platform/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY apps/app-platform/app ./app

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
