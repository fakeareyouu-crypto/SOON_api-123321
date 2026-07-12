import os
import uuid
import requests
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Zapupi Integrated Payment API", docs_url="/docs")

# Replace this with the unique URL you got from running the curl command above!
KV_BUCKET_URL = "https://kvdb.io/XaEy1AsdVB47ajcDwDpp7d/"

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

    order_id = str(uuid.uuid4().hex[:8]).upper()
    amount = payload.amount

    # Save to cloud bucket permanently
    order_data = {"status": "Payment Pending", "amount": amount}
    requests.post(f"{KV_BUCKET_URL}/order_{order_id}", json=order_data, timeout=5)

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
        
    order_id = str(payload.get("order_id", "")).strip().upper()
    status = payload.get("status", "success")
    
    # Fetch from live cloud bucket
    res = requests.get(f"{KV_BUCKET_URL}/order_{order_id}", timeout=5)
    if res.status_code == 200:
        order_data = res.json()
        order_data["status"] = "Success" if status == "success" else status
        
        # Save updated status back to cloud bucket
        requests.post(f"{KV_BUCKET_URL}/order_{order_id}", json=order_data, timeout=5)
        return {"status": "acknowledged"}
            
    return {"status": "ignored", "message": "Order reference mismatch"}

# --- 3. ENDPOINT: CHECK STATUS ---
@app.get("/api/check-status/{order_id}")
async def check_status(order_id: str):
    clean_id = order_id.strip().upper()
    
    res = requests.get(f"{KV_BUCKET_URL}/order_{clean_id}", timeout=5)
    if res.status_code != 200:
        raise HTTPException(status_code=404, detail="Order ID code does not exist.")
        
    order_data = res.json()
    return {
        "order_id": clean_id,
        "amount": order_data["amount"],
        "status": order_data["status"]
    }
