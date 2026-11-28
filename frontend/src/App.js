import React, { useState } from 'react';
import './App.css';

function App() {
  const [address, setAddress] = useState('');
  const [scanning, setScanning] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  const handleScan = async (e) => {
    e.preventDefault();
    if (!address.trim()) {
      setError('Please enter a token address');
      return;
    }

    setScanning(true);
    setError('');
    setResult(null);

    try {
      const response = await fetch('http://localhost:3001/api/scan', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ address: address.trim() }),
      });

      if (!response.ok) {
        throw new Error('Failed to scan token');
      }

      const data = await response.json();
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setScanning(false);
    }
  };

  const getRiskColor = (score) => {
    if (score < 30) return 'text-green-600';
    if (score < 70) return 'text-yellow-600';
    return 'text-red-600';
  };

  const getRiskLevel = (score) => {
    if (score < 30) return 'Low Risk';
    if (score < 70) return 'Medium Risk';
    return 'High Risk';
  };

  return (
    <div className="min-h-screen bg-gray-100">
      <div className="container mx-auto px-4 py-8">
        <div className="max-w-4xl mx-auto">
          {/* Header */}
          <div className="text-center mb-8">
            <h1 className="text-4xl font-bold text-gray-900 mb-2">Traid</h1>
            <p className="text-xl text-gray-600">Blockchain Token Scanner</p>
            <p className="text-gray-500 mt-2">Analyze tokens for potential rug pulls and security risks</p>
          </div>

          {/* Scanner Form */}
          <div className="bg-white rounded-lg shadow-md p-6 mb-8">
            <form onSubmit={handleScan} className="space-y-4">
              <div>
                <label htmlFor="address" className="block text-sm font-medium text-gray-700 mb-2">
                  Token Contract Address
                </label>
                <input
                  type="text"
                  id="address"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  placeholder="0x..."
                  className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  disabled={scanning}
                />
              </div>
              <button
                type="submit"
                disabled={scanning}
                className="w-full bg-blue-600 text-white py-2 px-4 rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {scanning ? 'Scanning...' : 'Scan Token'}
              </button>
            </form>

            {error && (
              <div className="mt-4 p-4 bg-red-100 border border-red-400 text-red-700 rounded">
                {error}
              </div>
            )}
          </div>

          {/* Results */}
          {result && (
            <div className="bg-white rounded-lg shadow-md p-6">
              <h2 className="text-2xl font-bold text-gray-900 mb-6">Scan Results</h2>
              
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Token Info */}
                <div className="space-y-4">
                  <h3 className="text-lg font-semibold text-gray-800">Token Information</h3>
                  <div className="space-y-2">
                    <p><span className="font-medium">Name:</span> {result.tokenName}</p>
                    <p><span className="font-medium">Recommendation:</span> 
                      <span className={`ml-2 font-semibold ${
                        result.recommendation === 'Buy' ? 'text-green-600' :
                        result.recommendation === 'Hold' ? 'text-yellow-600' : 'text-red-600'
                      }`}>
                        {result.recommendation}
                      </span>
                    </p>
                    <p><span className="font-medium">Whale Backed:</span> 
                      <span className={`ml-2 ${result.whaleBacked ? 'text-green-600' : 'text-red-600'}`}>
                        {result.whaleBacked ? 'Yes' : 'No'}
                      </span>
                    </p>
                  </div>
                </div>

                {/* Risk Scores */}
                <div className="space-y-4">
                  <h3 className="text-lg font-semibold text-gray-800">Risk Analysis</h3>
                  <div className="space-y-3">
                    <div>
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-medium">Rug Pull Risk</span>
                        <span className={`font-semibold ${getRiskColor(result.rugRiskScore)}`}>
                          {result.rugRiskScore}% - {getRiskLevel(result.rugRiskScore)}
                        </span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div 
                          className={`h-2 rounded-full ${
                            result.rugRiskScore < 30 ? 'bg-green-600' :
                            result.rugRiskScore < 70 ? 'bg-yellow-600' : 'bg-red-600'
                          }`}
                          style={{ width: `${result.rugRiskScore}%` }}
                        ></div>
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between items-center mb-1">
                        <span className="font-medium">Hype Score</span>
                        <span className="font-semibold text-blue-600">{result.hypeScore}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div 
                          className="h-2 rounded-full bg-blue-600"
                          style={{ width: `${result.hypeScore}%` }}
                        ></div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              {/* Contract Info */}
              {result.contractInfo && (
                <div className="mt-6 pt-6 border-t border-gray-200">
                  <h3 className="text-lg font-semibold text-gray-800 mb-4">Contract Information</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <p><span className="font-medium">Contract Name:</span> {result.contractInfo.contractName || 'Unknown'}</p>
                    <p><span className="font-medium">Verified:</span> 
                      <span className={`ml-2 ${result.contractInfo.isVerified ? 'text-green-600' : 'text-red-600'}`}>
                        {result.contractInfo.isVerified ? 'Yes' : 'No'}
                      </span>
                    </p>
                    <p><span className="font-medium">Compiler:</span> {result.contractInfo.compilerVersion || 'Unknown'}</p>
                    <p><span className="font-medium">Creator:</span> {result.contractInfo.ownerAddress}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
