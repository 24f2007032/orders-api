
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

from fastapi import FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Orders API")

# Ensure CORS headers are applied to every response,
# including 429 responses returned by the rate limiter.
app = CORSMiddleware(
    app=app,
    allow_origins=["https://exam.sanand.workers.dev"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

TOTAL_ORDERS = 60
RATE_LIMIT = 17
WINDOW_SECONDS = 10

# Fixed catalog: IDs 1 through 60
catalog = [
    {"id": i, "name": f"Order {i}"}
    for i in range(1, TOTAL_ORDERS + 1)
]

# Idempotency storage
idempotency_store = {}
idempotency_lock = Lock()

# Independent sliding-window bucket for every client
client_requests = defaultdict(deque)
rate_lock = Lock()


class OrderCreate(BaseModel):
    product: str = "default-product"
    quantity: int = 1


@app.middleware("http")
async def per_client_rate_limit(request: Request, call_next):
    # Browser CORS preflight must not consume the quota.
    if request.method == "OPTIONS":
        return await call_next(request)

    client_id = request.headers.get("X-Client-Id", "anonymous")
    now = time.monotonic()

    with rate_lock:
        requests = client_requests[client_id]

        while requests and now - requests[0] >= WINDOW_SECONDS:
            requests.popleft()

        if len(requests) >= RATE_LIMIT:
            retry_after = max(
                1, int(WINDOW_SECONDS - (now - requests[0]) + 0.999)
            )
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        requests.append(now)

    return await call_next(request)


@app.get("/")
def health():
    return {"status": "ok", "total_orders": TOTAL_ORDERS}


@app.post("/orders", status_code=201)
def create_order(
    payload: OrderCreate,
    response: Response,
    idempotency_key: str = Header(alias="Idempotency-Key"),
):
    with idempotency_lock:
        existing = idempotency_store.get(idempotency_key)

        if existing is not None:
            response.status_code = 200
            return existing

        order = {
            "id": str(uuid.uuid4()),
            "product": payload.product,
            "quantity": payload.quantity,
        }

        idempotency_store[idempotency_key] = order
        return order


@app.get("/orders")
def list_orders(
    limit: int = Query(default=10, ge=1, le=60),
    cursor: str | None = None,
):
    try:
        start_id = int(cursor) + 1 if cursor is not None else 1
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    if not 1 <= start_id <= TOTAL_ORDERS + 1:
        raise HTTPException(status_code=400, detail="Invalid cursor")

    items = catalog[start_id - 1 : start_id - 1 + limit]
    last_id = items[-1]["id"] if items else None

    next_cursor = (
        str(last_id)
        if last_id is not None and last_id < TOTAL_ORDERS
        else None
    )

    return {
        "items": items,
        "next_cursor": next_cursor,
    }
