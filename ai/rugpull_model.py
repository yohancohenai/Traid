
from flask import Flask, request, jsonify
import random
import hashlib

app = Flask(__name__)

def generate_token_name(address):
    """Generate a deterministic token name based on address"""
    names = [
        "SafeMoon", "DogeCoin", "PepeCoin", "ShibilInu", "RocketToken", 
        "DiamondHands", "ToTheMoon", "HODL Token", "LamboToken", "YieldFarm",
        "DeFiMax", "CryptoGem", "MoonShot", "SafetyFirst", "TrustToken"
    ]
    hash_val = int(hashlib.md5(address.encode()).hexdigest()[:8], 16)
    return names[hash_val % len(names)]

def analyze_address_risk(address):
    """Generate deterministic risk scores based on address"""
    hash_val = int(hashlib.md5(address.encode()).hexdigest()[:8], 16)
    
    # Generate consistent scores for the same address
    rug_risk = (hash_val % 80) + 10  # 10-90 range
    hype_score = ((hash_val >> 8) % 70) + 30  # 30-100 range
    whale_backed = (hash_val % 3) == 0  # ~33% chance
    
    # Recommendation based on risk score
    if rug_risk < 30:
        recommendation = "Buy"
    elif rug_risk < 70:
        recommendation = "Hold"
    else:
        recommendation = "Avoid"
    
    return rug_risk, hype_score, whale_backed, recommendation

@app.route('/predict', methods=['POST'])
def predict_rug_risk():
    try:
        data = request.json
        if not data or 'address' not in data:
            return jsonify({"error": "Token address required"}), 400
        
        token_address = data.get('address', '').strip()
        
        if not token_address:
            return jsonify({"error": "Token address cannot be empty"}), 400
        
        # Basic address validation
        if not token_address.startswith('0x') or len(token_address) != 42:
            return jsonify({"error": "Invalid Ethereum address format"}), 400
        
        # Generate analysis
        rug_risk, hype_score, whale_backed, recommendation = analyze_address_risk(token_address)
        token_name = generate_token_name(token_address)
        
        response = {
            "tokenName": token_name,
            "rugRiskScore": rug_risk,
            "hypeScore": hype_score,
            "whaleBacked": whale_backed,
            "recommendation": recommendation,
        }
        return jsonify(response)
    
    except Exception as e:
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "service": "Traid AI Model"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
