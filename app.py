from flask import Flask, render_template, request, jsonify
from urllib.parse import urlsplit
from scraper import fetch_race_data
from analyzer import analyze_anauma

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    """レースURLを受け取り、穴馬分析結果を返す"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "JSON形式でURLを入力してください"}), 400
    url = data.get("url", "")
    if not isinstance(url, str) or not url:
        return jsonify({"error": "URLを入力してください"}), 400

    # schemeとhostnameを検証し、userinfoや別サービスへの接続を許可しない
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or ""
        valid_host = host == "netkeiba.com" or host.endswith(".netkeiba.com")
        valid_port = parsed.port in (None, 443 if parsed.scheme == "https" else 80)
        if (parsed.scheme not in ("http", "https") or not valid_host or not valid_port
                or parsed.username is not None or parsed.password is not None
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)):
            raise ValueError("invalid URL")
    except ValueError:
        return jsonify({"error": "netkeibaのレースURLを入力してください"}), 400

    try:
        race_data = fetch_race_data(url)
        result = analyze_anauma(race_data)
        return jsonify(result)
    except Exception:
        return jsonify({"error": "レース情報の取得または分析に失敗しました"}), 500

if __name__ == "__main__":
    app.run(debug=False, host="127.0.0.1", port=5000)
