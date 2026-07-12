import os
import uuid
import requests
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="Zapupi Integrated Payment API", docs_url="/docs", openapi_url="/openapi.json")

# --- CONFIGURATION ---
ZAP_KEY = os.environ.get("ZAP_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
ZAPUPI_CREATE_ORDER_URL = "https://pay.zapupi.com/api/create-order"

SUCCESS_URL = "https://yourwebsite.com/payment-success"
FAILED_URL = "https://yourwebsite.com/payment-failed"
TIMEOUT_URL = "https://yourwebsite.com/payment-timeout"

class CreateOrderRequest(BaseModel):
    amount: float

def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

# --- 1. ENDPOINT: CREATE ORDER ---
@app.post("/api/create-payment")
async def create_payment(payload: CreateOrderRequest):
    if not ZAP_KEY or not SUPABASE_URL or not SUPABASE_KEY:
        raise HTTPException(status_code=500, detail="Missing configuration environment variables on Vercel.")

    order_id = str(uuid.uuid4().hex[:8]).upper()
    amount = payload.amount
    
    row_data = {"order_id": order_id, "amount": amount, "status": "Payment Pending"}
    try:
        url = f"{SUPABASE_URL}/rest/v1/orders"
        requests.post(url, json=row_data, headers=get_supabase_headers(), timeout=5)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database save failed: {str(e)}")

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
@app.post("/api/webhook/zapupi/")
async def zapupi_webhook(request: Request):
    payload = {}
    try:
        payload = await request.json()
    except Exception:
        try:
            form_data = await request.form()
            payload = dict(form_data)
        except Exception:
            pass

    print(f"CRITICAL WEBHOOK INCOMING SIGNAL DATA: {payload}")
    
    order_id = payload.get("order_id") or payload.get("ORDER_ID")
    if not order_id:
        return {"status": "ignored", "message": "Missing order reference parameter"}
        
    order_id = str(order_id).strip().upper()
    incoming_status = str(payload.get("status", "")).strip().lower()
    final_status = "Success" if incoming_status in ["success", "paid"] else "Failed"
    
    # FIX: Added get_supabase_headers() here so Supabase actually accepts the update!
    url = f"{SUPABASE_URL}/rest/v1/orders?order_id=eq.{order_id}"
    res = requests.patch(url, json={"status": final_status}, headers=get_supabase_headers(), timeout=5)
    
    return {"status": "processed", "target": order_id, "db_response": res.status_code}


# --- 3. ENDPOINT: CHECK STATUS ---
@app.get("/api/check-status/{order_id}")
async def check_status(order_id: str):
    clean_id = order_id.strip().upper()
    
    url = f"{SUPABASE_URL}/rest/v1/orders?order_id=eq.{clean_id}&select=*"
    res = requests.get(url, headers=get_supabase_headers(), timeout=5)
    
    if res.status_code != 200 or not res.json():
        raise HTTPException(status_code=404, detail="Order ID code does not exist.")
        
    order_data = res.json()[0]
    return {
        "order_id": clean_id,
        "amount": order_data["amount"],
        "status": order_data["status"]
    }
