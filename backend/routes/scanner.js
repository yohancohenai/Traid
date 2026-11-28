
const express = require('express');
const router = express.Router();
const mockScanner = require('../services/mockScanner');

router.post('/', async (req, res) => {
  try {
    const { address } = req.body;
    if (!address) {
      return res.status(400).json({ error: "Token address required" });
    }

    // Basic address validation
    if (!address.match(/^0x[a-fA-F0-9]{40}$/)) {
      return res.status(400).json({ error: "Invalid Ethereum address format" });
    }

    const result = await mockScanner(address);
    res.json(result);
  } catch (error) {
    console.error('Scanner error:', error);
    res.status(500).json({ error: error.message || "Internal server error" });
  }
});

module.exports = router;
