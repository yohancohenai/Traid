
const axios = require('axios');
const { getContractInfo } = require('./etherscan');

const fetchFromAI = async (address) => {
  const contractInfo = await getContractInfo(address);
  const aiRes = await axios.post('http://localhost:8000/predict', { address });

  return {
    ...aiRes.data,
    contractInfo
  };
};

module.exports = fetchFromAI;
