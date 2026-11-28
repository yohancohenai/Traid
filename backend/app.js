
const express = require('express');
const cors = require('cors');
const scannerRoute = require('./routes/scanner');
require('dotenv').config();

const app = express();
app.use(cors());
app.use(express.json());

// Health check endpoint
app.get('/health', (req, res) => {
  res.json({ status: 'healthy', service: 'Traid Backend API' });
});

app.use('/api/scan', scannerRoute);

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  console.log(`Traid API running on port ${PORT}`);
});
