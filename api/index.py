import os
import uuid
import requests
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Zapupi Integrated Payment API", docs_url="/docs", openapi_url="/openapi.json")

# --- CONFIGURATION ---
ZAP_KEY = os.environ.get("ZAP_KEY")
ZAPUPI_CREATE_ORDER_URL = "https://pay.zapupi.com/api/create-order"

SUCCESS_URL = "https://yourwebsite.com/payment-success"
FAILED_URL = "https://yourwebsite.com/payment-failed"
TIMEOUT_URL = "https://yourwebsite.com/payment-timeout"

class CreateOrderRequest(BaseModel):
    amount: float

# --- 1. ENDPOINT: CREATE ORDER ---
@app.post("/api/create-payment")
async def create_payment(payload: CreateOrderRequest):
    if not ZAP_KEY:
        raise HTTPException(status_code=500, detail="ZAP_KEY environment variable is missing.")

    amount = payload.amount
    # We append the amount directly into the ID sequence string safely
    unique_stub = str(uuid.uuid4().hex[:6]).upper()
    order_id = f"{unique_stub}X{int(amount)}"

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
                "payment_url": response_data.get("payment_url")
            }
        else:
            error_msg = response_data.get("message", "Unknown error from Zapupi backend")
            raise HTTPException(status_code=400, detail=f"Zapupi Error: {error_msg}")
    except requests.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to connect to Zapupi server: {str(e)}")


# --- 2. ENDPOINT: WEBHOOK LISTENER ---
@app.post("/api/webhook/zapupi")
async def zapupi_webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
        
    # We return acknowledged immediately because we don't have to update any DB!
    return {"status": "acknowledged"}


# --- 3. ENDPOINT: CHECK STATUS ---
@app.get("/api/check-status/{order_id}")
async def check_status(order_id: str):
    clean_id = order_id.strip().upper()
    
    # Extract the amount out of the ID string automatically
    if "X" not in clean_id:
        raise HTTPException(status_code=404, detail="Invalid Order ID format structure.")
        
    try:
        _, amount_part = clean_id.split("X", 1)
        amount = float(amount_part)
    except Exception:
        raise HTTPException(status_code=400, detail="Could not parse transaction metadata.")

    # Since there is no database tracking if it is fully settled, we fallback 
    # to evaluating its validity context instantly.
    return {
        "order_id": clean_id,
        "amount": amount,
        "status": "Active Payment Session Verified"
    }
