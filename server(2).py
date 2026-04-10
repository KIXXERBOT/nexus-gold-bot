from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import hmac, hashlib, time, requests, os, json

app = Flask(__name__, static_folder='.')
CORS(app)

MEXC_SPOT    = "https://api.mexc.com"
MEXC_FUTURES = "https://contract.mexc.com"

def sign_spot(secret, params):
    query = "&".join(f"{k}={v}" for k,v in sorted(params.items()))
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def sign_futures(secret, params):
    # MEXC Futures uses different signing
    ts = str(int(time.time() * 1000))
    body = json.dumps(params) if params else ""
    sign_str = ts + body
    sig = hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()
    return sig, ts

# ── Frontend ──────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory('.', 'index.html')

# ── Spot Preis (public) ───────────────────────────────────────
@app.route("/api/price")
def price():
    symbol = request.args.get("symbol", "XAUUSDT")
    try:
        r = requests.get(f"{MEXC_SPOT}/api/v3/ticker/24hr",
            params={"symbol": symbol}, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Spot Klines (public) ──────────────────────────────────────
@app.route("/api/klines")
def klines():
    symbol   = request.args.get("symbol", "XAUUSDT")
    interval = request.args.get("interval", "Min1")
    limit    = request.args.get("limit", "80")

    # Konvertiere Chart Interval zu Futures Format
    interval_map = {
        "1m": "Min1", "3m": "Min5", "5m": "Min5",
        "15m": "Min15", "30m": "Min30",
        "1h": "Min60", "4h": "Hour4", "1d": "Day1"
    }
    futures_interval = interval_map.get(interval, interval)

    try:
        # Versuche zuerst Futures Klines
        r = requests.get(f"{MEXC_FUTURES}/api/v1/contract/kline/{symbol}",
            params={"interval": futures_interval, "limit": limit}, timeout=10)
        data = r.json()
        if data.get("success") and data.get("data"):
            # Konvertiere zu Standard Format [ts, open, high, low, close, vol]
            d = data["data"]
            candles = []
            for i in range(len(d.get("time", []))):
                candles.append([
                    d["time"][i] * 1000,
                    d["open"][i],
                    d["high"][i],
                    d["low"][i],
                    d["close"][i],
                    d.get("vol", [0]*len(d["time"]))[i]
                ])
            return jsonify(candles)
    except Exception as e:
        pass

    # Fallback: Spot Klines
    try:
        r = requests.get(f"{MEXC_SPOT}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Balance (Futures) ─────────────────────────────────────────
@app.route("/api/balance")
def balance():
    key    = request.headers.get("X-API-KEY", "")
    secret = request.headers.get("X-API-SECRET", "")
    if not key or not secret:
        return jsonify({"error": "API Key fehlt"}), 401
    try:
        sig, ts = sign_futures(secret, {})
        headers = {
            "ApiKey": key,
            "Request-Time": ts,
            "Signature": sig,
            "Content-Type": "application/json"
        }
        r = requests.get(f"{MEXC_FUTURES}/api/v1/private/account/assets",
            headers=headers, timeout=10)
        data = r.json()
        if data.get("success") and data.get("data"):
            assets = data["data"]
            if isinstance(assets, list):
                usdt = next((a for a in assets if a.get("currency") == "USDT"), None)
                if usdt:
                    bal = usdt.get("availableBalance", 0)
                    return jsonify({"balances": [{"asset": "USDT", "free": str(bal)}]})
            elif isinstance(assets, dict):
                bal = assets.get("availableBalance", 0)
                return jsonify({"balances": [{"asset": "USDT", "free": str(bal)}]})
        # Fallback Spot
        params = {"timestamp": int(time.time()*1000), "recvWindow": 5000}
        query = sign_spot(secret, params)
        r2 = requests.get(f"{MEXC_SPOT}/api/v3/account?{query}",
            headers={"X-MEXC-APIKEY": key}, timeout=10)
        return jsonify(r2.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Order (Futures) ───────────────────────────────────────────
@app.route("/api/order", methods=["POST"])
def order():
    key    = request.headers.get("X-API-KEY", "")
    secret = request.headers.get("X-API-SECRET", "")
    if not key or not secret:
        return jsonify({"error": "API Key fehlt"}), 401

    data   = request.json or {}
    symbol = data.get("symbol", "XAUUSDT")
    side   = data.get("side", "BUY")
    qty    = float(data.get("quantity", 0))

    body = {
        "symbol":    symbol,
        "side":      1 if side == "BUY" else 3,
        "orderType": 5,
        "vol":       qty,
        "leverage":  200,
        "openType":  1,
    }

    try:
        sig, ts = sign_futures(secret, body)
        headers = {
            "ApiKey": key,
            "Request-Time": ts,
            "Signature": sig,
            "Content-Type": "application/json"
        }
        r = requests.post(f"{MEXC_FUTURES}/api/v1/private/order/submit",
            headers=headers, json=body, timeout=10)
        result = r.json()
        if result.get("success"):
            return jsonify({"orderId": result.get("data"), "success": True})
        else:
            return jsonify({"error": result.get("message", "Order fehlgeschlagen"), "raw": result}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Health ────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "Kröte V1"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
