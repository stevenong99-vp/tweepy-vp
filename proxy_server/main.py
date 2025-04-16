from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx
import redis
import time

app = FastAPI()

# Initialize Redis for rate limiting and billing
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)

# Twitter API base URL
TWITTER_API_BASE_URL = "https://api.twitter.com"

# Rate limit configuration (e.g., max 100 requests per hour per client)
RATE_LIMIT = 100
RATE_LIMIT_WINDOW = 3600  # in seconds (1 hour)

# Proxy endpoint
@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(path: str, request: Request):
    client_id = request.headers.get("X-Client-ID")
    if not client_id:
        raise HTTPException(status_code=400, detail="Missing X-Client-ID header")

    # Rate limiting logic
    current_time = int(time.time())
    window_start = current_time // RATE_LIMIT_WINDOW * RATE_LIMIT_WINDOW
    rate_limit_key = f"rate_limit:{client_id}:{window_start}"

    # Increment request count in Redis
    request_count = redis_client.incr(rate_limit_key)
    if request_count == 1:
        redis_client.expire(rate_limit_key, RATE_LIMIT_WINDOW)

    if request_count > RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # Forward the request to Twitter API
    async with httpx.AsyncClient() as client:
        twitter_url = f"{TWITTER_API_BASE_URL}/{path}"
        headers = dict(request.headers)
        headers.pop("host", None)  # Remove host header to avoid conflicts

        try:
            response = await client.request(
                method=request.method,
                url=twitter_url,
                headers=headers,
                params=request.query_params,
                data=await request.body(),
            )
            return JSONResponse(content=response.json(), status_code=response.status_code)
        except httpx.RequestError as exc:
            raise HTTPException(status_code=500, detail=f"Error connecting to Twitter API: {exc}")

# Billing endpoint (optional)
@app.get("/billing/{client_id}")
async def billing(client_id: str):
    keys = redis_client.keys(f"rate_limit:{client_id}:*")
    total_requests = sum(int(redis_client.get(key)) for key in keys)
    return {"client_id": client_id, "total_requests": total_requests}
