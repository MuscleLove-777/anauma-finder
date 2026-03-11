from flask import Flask, render_template, request, jsonify
from scraper import fetch_race_data
from analyzer import analyze_anauma

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/analyze", methods=["POST"])
def analyze():
    """レースURLを受け取り、穴馬分析結果を返す"""
    url = request.json.get("url", "")
    if not url:
        return jsonify({"error": "URLを入力してください"}), 400

    # netkeibaのURLかバリデーション
    if "netkeiba.com" not in url:
        return jsonify({"error": "netkeibaのレースURLを入力してください"}), 400

    try:
        race_data = fetch_race_data(url)
        result = analyze_anauma(race_data)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
