import os
from flask import Flask, jsonify, request

app = Flask(__name__)

@app.get("/")
def health():
    return "ok", 200

@app.post("/check")
def run_check():
    import ktmb_checker
    try:
        # result = subprocess.run(
        #     ["python", "ktmb_checker.py"],
        #     capture_output=True,
        #     text=True,
        #     timeout=180,
        # )
        result = ktmb_checker.main()
        return jsonify({"status": "success", "result": result}), 200
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)