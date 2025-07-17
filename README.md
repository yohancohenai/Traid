# Traid - Blockchain Token Scanner

A comprehensive web application for scanning and analyzing blockchain tokens for potential rug pulls and security risks.

## 🚀 Features

- **Token Scanning**: Analyze ERC-20 tokens for potential risks
- **AI-Powered Analysis**: Machine learning model for rug pull detection
- **Real-time Data**: Live blockchain data integration
- **Modern UI**: Built with React and Tailwind CSS
- **Backend API**: Node.js/Express server with Etherscan integration

## 📁 Project Structure

```
traid/
├── frontend/          # React application
├── backend/           # Node.js API server
└── ai/               # Machine learning models
```

## 🛠️ Setup Instructions

### Prerequisites

- Node.js (v16 or higher)
- npm or yarn
- Python 3.8+ (for AI models)

### Frontend Setup

1. Navigate to the frontend directory:
   ```bash
   cd frontend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Start the development server:
   ```bash
   npm start
   ```

The app will be available at `http://localhost:3000`

### Backend Setup

1. Navigate to the backend directory:
   ```bash
   cd backend
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Create a `.env` file with your Etherscan API key:
   ```
   ETHERSCAN_API_KEY=your_api_key_here
   ```

4. Start the server:
   ```bash
   npm start
   ```

### AI Model Setup

1. Navigate to the ai directory:
   ```bash
   cd ai
   ```

2. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## 🎨 Technologies Used

- **Frontend**: React, Tailwind CSS, JavaScript
- **Backend**: Node.js, Express, Etherscan API
- **AI/ML**: Python, scikit-learn, pandas
- **Version Control**: Git, GitHub

## 🔧 Configuration

### Tailwind CSS

The project uses Tailwind CSS for styling. Configuration files:
- `frontend/tailwind.config.js` - Tailwind configuration
- `frontend/postcss.config.js` - PostCSS configuration
- `frontend/src/index.css` - Global styles with Tailwind directives

### Environment Variables

Create `.env` files in the backend directory with:
- `ETHERSCAN_API_KEY` - Your Etherscan API key
- `PORT` - Server port (default: 3001)

## 🚀 Deployment

### Frontend Deployment

The React app can be deployed to:
- Vercel
- Netlify
- GitHub Pages

Build the production version:
```bash
cd frontend
npm run build
```

### Backend Deployment

The Node.js server can be deployed to:
- Heroku
- Railway
- DigitalOcean

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## 📝 License

This project is licensed under the MIT License.

## 🆘 Troubleshooting

### Common Issues

1. **Tailwind CSS not working**: Ensure `tailwind.config.js` and `postcss.config.js` exist
2. **API errors**: Check your Etherscan API key in the `.env` file
3. **Port conflicts**: Change the port in the backend `.env` file

### Getting Help

If you encounter issues:
1. Check the console for error messages
2. Verify all dependencies are installed
3. Ensure environment variables are set correctly
4. Check the GitHub issues page for known problems 