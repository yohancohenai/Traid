
const express = require('express');
const router = express.Router();
const mockScanner = require('../services/mockScanner');

router.post('/', async (req, res) => {
  const { address } = req.body;
  if (!address) return res.status(400).json({ error: "Token address required" });

  const result = await mockScanner(address);
  res.json(result);
});

module.exports = router;
