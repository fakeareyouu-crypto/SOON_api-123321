import os
import json
import uuid
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List

app = FastAPI(title="Zapupi Integrated Payment API", docs_url="/docs", openapi_url="/openapi.json")

# --- SIMULATED HARDWARE STORAGE DIRECTORY ---
# Vercel allows write access exclusively to the serverless /tmp folder
STORAGE_FILE = "/tmp/orders_db.json"

def load_local_db() -> dict:
    """Helper to cleanly read the temp file storage."""
    if not os.path.exists(STORAGE_FILE):
        return {}
    try:
        with open(STORAGE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_local_db(data: dict):
    """Helper to cleanly write changes back to the temp file storage."""
    try:
        with open(STORAGE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

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

    order_id = str(uuid.uuid4().hex[:8]).upper()
    amount = payload.amount

    # Fetch our file system tracking structure
    db_orders = load_local_db()
    db_orders[order_id] = {
        "status": "Payment Pending",
        "amount": amount,
        "zapupi_details": None
    }
    save_local_db(db_orders)

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
    db_orders = load_local_db()
    
    if order_id in db_orders:
        db_orders[order_id]["status"] = payload.status  
        db_orders[order_id]["zapupi_details"] = payload.dict()
        save_local_db(db_orders)
        return {"status": "acknowledged"}
    else:
        raise HTTPException(status_code=404, detail="Order ID not found in system storage")


# --- 3. ENDPOINT: CHECK STATUS ---
@app.get("/api/check-status/{order_id}")
async def check_status(order_id: str):
    db_orders = load_local_db()
    
    if order_id not in db_orders:
        raise HTTPException(status_code=404, detail="Order ID code does not exist.")
        
    order_data = db_orders[order_id]
    return {
        "order_id": order_id,
        "amount": order_data["amount"],
        "status": order_data["status"]
    }
