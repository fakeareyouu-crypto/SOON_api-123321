import os
import json
import uuid
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
from upstash_redis import Redis

app = FastAPI(title="Zapupi Integrated Payment API", docs_url="/docs", openapi_url="/openapi.json")

# Initialize connection safely from environment variables
try:
    kv = Redis.from_env()
except Exception as e:
    kv = None

# --- CONFIGURATION ---
ZAP_KEY = os.environ.get("ZAP_KEY")
ZAPUPI_CREATE_ORDER_URL = "https://pay.zapupi.com/api/create-order"

SUCCESS_URL = "https://yourwebsite.com/payment-success"
FAILED_URL = "https://yourwebsite.com/payment-failed"
TIMEOUT_URL = "https://yourwebsite.com/payment-timeout"


class CreateOrderRequest(BaseModel):
    amount: float

class ZapupiWebhookPayload(BaseModel):
    order_id: str
    txn_id: str
    status: str
    amount: str
    pay_amount: str
    utr: str
    customer_mobile: str
    remark: str
    remark_array: List[str]
    create_at: str
    environment: str


# --- 1. ENDPOINT: CREATE ORDER ---
@app.post("/api/create-payment")
async def create_payment(payload: CreateOrderRequest):
    if not ZAP_KEY:
        raise HTTPException(status_code=500, detail="Server Error: ZAP_KEY environment variable is missing.")
    if not kv:
        raise HTTPException(status_code=500, detail="Server Error: Redis client could not connect.")

    order_id = str(uuid.uuid4().hex[:8]).upper()
    amount = payload.amount

    order_data = {
        "status": "Payment Pending",
        "amount": amount,
        "zapupi_details": None
    }
    
    # FIX: Safely stringify the dictionary into JSON before saving to Redis
    kv.set(f"order:{order_id}", json.dumps(order_data))

    zapupi_payload = {
        "zap_key": ZAP_KEY,
        "order_id": order_id,
        "amount": amount,
        "success_url": SUCCESS_URL,
        "failed_url": FAILED_URL,
        "timeout_url": TIMEOUT_URL
    }

    try:
        response = requests.post(ZAPUPI_CREATE_ORDER_URL, json=zapupi_payload, timeout=10)
        response_data = response.json()

        if response.status_code == 200 and response_data.get("status") == "success":
            return {
                "status": "success",
                "order_id": order_id,
                "amount": amount,
                "payment_url": response_data.get("payment_url"),
                "zapupi_txn_id": response_data.get("txn_id")
            }
        else:
            error_msg = response_data.get("message", "Unknown error from Zapupi backend")
            raise HTTPException(status_code=400, detail=f"Zapupi Error: {error_msg}")

    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to Zapupi server: {str(e)}")


# --- 2. ENDPOINT: WEBHOOK LISTENER ---
@app.post("/api/webhook/zapupi")
async def zapupi_webhook(payload: ZapupiWebhookPayload):
    order_id = payload.order_id
    db_key = f"order:{order_id}"
    
    raw_data = kv.get(db_key)
    
    if raw_data:
        # FIX: Safely unpack string back into a Python Dictionary
        if isinstance(raw_data, str):
            order_data = json.loads(raw_data)
        else:
            order_data = raw_data

        order_data["status"] = payload.status  
        order_data["zapupi_details"] = payload.dict()
        
        # Save structural JSON back to string storage
        kv.set(db_key, json.dumps(order_data))
        return {"status": "acknowledged"}
    else:
        raise HTTPException(status_code=404, detail="Order ID not found in database")


# --- 3. ENDPOINT: CHECK STATUS ---
@app.get("/api/check-status/{order_id}")
async def check_status(order_id: str):
    db_key = f"order:{order_id}"
    raw_data = kv.get(db_key)
    
    if not raw_data:
        raise HTTPException(status_code=404, detail="Order ID code does not exist.")
        
    # FIX: Parse the text data cleanly back into JSON parameters
    if isinstance(raw_data, str):
        order_data = json.loads(raw_data)
    else:
        order_data = raw_data
        
    return {
        "order_id": order_id,
        "amount": order_data["amount"],
        "status": order_data["status"]
    }
