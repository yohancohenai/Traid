#!/bin/bash

echo "🚀 Starting Traid - Blockchain Token Scanner"
echo "============================================="

# Function to kill all background processes on exit
cleanup() {
    echo "🛑 Stopping all services..."
    kill $(jobs -p) 2>/dev/null
    exit
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Start AI service
echo "🤖 Starting AI service on port 8000..."
cd ai
source venv/bin/activate
python rugpull_model.py &
AI_PID=$!
cd ..

# Wait a moment for AI service to start
sleep 2

# Start backend
echo "🖥️  Starting backend on port 3001..."
cd backend
npm start &
BACKEND_PID=$!
cd ..

# Wait a moment for backend to start
sleep 2

# Start frontend
echo "🌐 Starting frontend on port 3000..."
cd frontend
npm start &
FRONTEND_PID=$!
cd ..

echo ""
echo "✅ All services started!"
echo "📱 Frontend: http://localhost:3000"
echo "🖥️  Backend API: http://localhost:3001"
echo "🤖 AI Service: http://localhost:8000"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for all background processes
wait