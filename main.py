from fastapi import FastAPI
from dotenv import load_dotenv
import os
from datetime import datetime
from fastapi import Request
from groq import Groq


load_dotenv()

app = FastAPI()

# In-memory store for context
context_store = {}

@app.get("/v1/healthz")
def healthz():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}

@app.get("/v1/metadata")
def metadata():
    return {
        "bot_name": "Vera",
        "version": "1.0.0",
        "description": "Vera - magicpin merchant growth assistant",
        "supported_triggers": ["recall", "spike", "dip", "research", "festival"],
        "supported_categories": ["dentist", "salon", "restaurant", "gym", "pharmacy"]
    }

@app.post("/v1/context")
async def receive_context(request: Request):
    body = await request.json()
    
    scope = body.get("scope")
    context_id = body.get("context_id")
    version = body.get("version", 1)
    payload = body.get("payload", {})
    
    key = f"{scope}:{context_id}"
    
    # Only update if new version is higher
    existing = context_store.get(key)
    if existing and existing.get("version", 0) >= version:
        return {"accepted": False, "reason": "same or older version"}
    
    context_store[key] = {
        "scope": scope,
        "context_id": context_id,
        "version": version,
        "payload": payload,
        "stored_at": datetime.utcnow().isoformat()
    }
    
    return {
        "accepted": True,
        "ack_id": f"ack_{context_id}_{version}",
        "stored_at": datetime.utcnow().isoformat()
    }

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def compose(category, merchant, trigger, customer=None):
    # Build context string from merchant data
    merchant_name = merchant.get("identity", {}).get("name", "Merchant")
    offers = merchant.get("offers", [])
    performance = merchant.get("performance", {})
    
    offers_text = ", ".join([f"{o.get('name')} at ₹{o.get('price')}" for o in offers]) if offers else "no current offers"
    perf_text = f"rating: {performance.get('rating')}, orders: {performance.get('orders_last_30d')}" if performance else "no performance data"

    prompt = f"""You are Vera, magicpin's AI assistant for merchant growth.

Merchant: {merchant_name}
Category: {category}
Performance: {perf_text}
Offers: {offers_text}
Trigger: {trigger.get('type')} — {trigger.get('description')}
Customer: {customer if customer else 'not specified'}

Write one short WhatsApp message from Vera to this merchant. Rules:
- Use real numbers and offer names from context
- One clear CTA (yes/no or single action)
- Max 3 sentences
- Sound helpful, not salesy
- End with a question they can answer in one word

Return JSON only:
{{
  "message": "...",
  "cta": "...",
  "send_as": "Vera",
  "suppression_key": "...",
  "rationale": "..."
}}"""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    import json
    text = response.choices[0].message.content
    try:
        return json.loads(text)
    except:
        return {"message": text, "cta": "Reply YES", "send_as": "Vera", "suppression_key": f"{category}_{trigger.get('type')}", "rationale": "LLM response"}


@app.post("/v1/tick")
async def tick(request: Request):
    body = await request.json()
    
    merchant_id = body.get("merchant_id")
    trigger = body.get("trigger", {})
    category = body.get("category", "general")
    customer_id = body.get("customer_id")
    
    # Fetch stored merchant context
    merchant_data = context_store.get(f"merchant:{merchant_id}", {}).get("payload", {})
    customer_data = context_store.get(f"customer:{customer_id}", {}).get("payload") if customer_id else None
    
    result = compose(category, merchant_data, trigger, customer_data)
    
    return {
        "actions": [
            {
                "type": "send_message",
                "payload": result
            }
        ]
    }

@app.post("/v1/reply")
async def reply(request: Request):
    body = await request.json()
    
    merchant_id = body.get("merchant_id")
    message = body.get("message", "")
    conversation_history = body.get("history", [])
    
    merchant_data = context_store.get(f"merchant:{merchant_id}", {}).get("payload", {})
    merchant_name = merchant_data.get("identity", {}).get("name", "Merchant")
    
    history_text = "\n".join([f"{h['role']}: {h['content']}" for h in conversation_history])
    
    prompt = f"""You are Vera, magicpin's AI assistant for merchant growth.
Merchant: {merchant_name}

Conversation so far:
{history_text}

Merchant just replied: "{message}"

Respond as Vera. Be short, helpful, and move toward one clear next action.
Max 2 sentences."""

    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    
    return {
        "reply": response.choices[0].message.content,
        "send_as": "Vera"
    }