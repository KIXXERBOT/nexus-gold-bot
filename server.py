from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import hmac, hashlib, time, requests, os

app = Flask(__name__, static_folder='.')
CORS(app)

MEXC_BASE = "https://api.mexc.com"

def sign_params(secret, params):
    query = "&".join(f"{k}={v}" for k,v in sorted(params.items()))
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig

def mexc_get(path, params, api_key="", api_secret="", signed=False):
    headers = {"X-MEXC-APIKEY": api_key} if api_key else {}
    if signed:
        params["timestamp"] = int(time.time() * 1000)
        params["recvWindow"] = 5000
        query = sign_params(api_secret, params)
        url = f"{MEXC_BASE}{path}?{query}"
    else:
        query = "&".join(f"{k}={v}" for k,v in params.items())
        url = f"{MEXC_BASE}{path}?{query}" if query else f"{MEXC_BASE}{path}"
    r = requests.get(url, headers=headers, timeout=10)
    return r.json()

def mexc_post(path, params, api_key, api_secret):
    headers = {"X-MEXC-APIKEY": api_key, "Content-Type": "application/json"}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    query = sign_params(api_secret, params)
    url = f"{MEXC_BASE}{path}?{query}"
    r = requests.post(url, headers=headers, timeout=10)
    return r.json()

# ── Frontend ──────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory('.', 'index.html')

# ── Preis ─────────────────────────────────────────────────────
@app.route("/api/price")
def price():
    symbol = request.args.get("symbol", "XAUUSDT")
    try:
        d = mexc_get("/api/v3/ticker/24hr", {"symbol": symbol})
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Klines ────────────────────────────────────────────────────
@app.route("/api/klines")
def klines():
    symbol   = request.args.get("symbol", "XAUUSDT")
    interval = request.args.get("interval", "1m")
    limit    = request.args.get("limit", "100")
    try:
        d = mexc_get("/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": limit})
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Balance ───────────────────────────────────────────────────
@app.route("/api/balance")
def balance():
    key    = request.headers.get("X-API-KEY", "")
    secret = request.headers.get("X-API-SECRET", "")
    if not key or not secret:
        return jsonify({"error": "API Key fehlt"}), 401
    try:
        d = mexc_get("/api/v3/account", {}, key, secret, signed=True)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Order ─────────────────────────────────────────────────────
@app.route("/api/order", methods=["POST"])
def order():
    key    = request.headers.get("X-API-KEY", "")
    secret = request.headers.get("X-API-SECRET", "")
    if not key or not secret:
        return jsonify({"error": "API Key fehlt"}), 401
    data = request.json or {}
    try:
        d = mexc_post("/api/v3/order", {
            "symbol":   data.get("symbol", "XAUUSDT"),
            "side":     data.get("side", "BUY"),
            "type":     "MARKET",
            "quantity": str(data.get("quantity", "0")),
        }, key, secret)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Health ────────────────────────────────────────────────────
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "NEXUS v11"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
