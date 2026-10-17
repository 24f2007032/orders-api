# Orders API

FastAPI demonstration of:
- Idempotent POST /orders
- Cursor pagination over 60 fixed orders
- Per-client rate limiting: 17 requests per 10 seconds
- CORS support

## Run locally

pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000