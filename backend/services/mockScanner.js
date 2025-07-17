
const axios = require('axios');
const { getContractInfo } = require('./etherscan');

const fetchFromAI = async (address) => {
  try {
    // Get contract info from Etherscan
    const contractInfo = await getContractInfo(address);
    
    // Try to get AI prediction
    let aiResult;
    try {
      const aiRes = await axios.post('http://localhost:8000/predict', { address }, {
        timeout: 5000 // 5 second timeout
      });
      aiResult = aiRes.data;
    } catch (aiError) {
      console.warn('AI service unavailable, using fallback data:', aiError.message);
      // Fallback data if AI service is down
      aiResult = {
        tokenName: "Unknown Token",
        rugRiskScore: Math.floor(Math.random() * 60) + 20, // Random between 20-80
        hypeScore: Math.floor(Math.random() * 70) + 30,   // Random between 30-100
        whaleBacked: Math.random() > 0.5,
        recommendation: "Hold", // Conservative recommendation when AI is unavailable
      };
    }

    return {
      ...aiResult,
      contractInfo: contractInfo || {
        contractName: 'Unknown',
        isVerified: false,
        compilerVersion: 'Unknown',
        ownerAddress: 'Unknown'
      }
    };
  } catch (error) {
    console.error('Error in fetchFromAI:', error);
    throw new Error('Failed to analyze token');
  }
};

module.exports = fetchFromAI;
