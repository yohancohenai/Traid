
const axios = require('axios');
const ETHERSCAN_KEY = process.env.ETHERSCAN_API_KEY;

const getContractInfo = async (address) => {
  try {
    const url = `https://api.etherscan.io/api?module=contract&action=getsourcecode&address=${address}&apikey=${ETHERSCAN_KEY}`;
    const res = await axios.get(url);
    const info = res.data.result[0];

    return {
      contractName: info.ContractName,
      isVerified: info.SourceCode !== '',
      compilerVersion: info.CompilerVersion,
      ownerAddress: info.CreatorAddress || 'Unknown',
    };
  } catch (err) {
    console.error("Etherscan error:", err.message);
    return null;
  }
};

module.exports = { getContractInfo };
