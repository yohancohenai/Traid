
from flask import Flask, request, jsonify
import random

app = Flask(__name__)

@app.route('/predict', methods=['POST'])
def predict_rug_risk():
    data = request.json
    token_address = data.get('address', '')

    response = {
        "tokenName": "MockCoin",
        "rugRiskScore": random.randint(10, 95),
        "hypeScore": random.randint(30, 99),
        "whaleBacked": random.choice([True, False]),
        "recommendation": random.choice(["Buy", "Hold", "Avoid"]),
    }
    return jsonify(response)

if __name__ == '__main__':
    app.run(port=8000)
