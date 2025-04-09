# Medical Content Scheduler

This application is responsible for fetching and storing trending medical topics on a scheduled basis. It provides an API for retrieving these topics.

## Features

- Daily fetching of trending medical topics using GPT-4o
- MongoDB storage of topics
- FastAPI endpoints for retrieving topics
- Automatic scheduling (runs at 12 AM Australia/Sydney time)

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

2. Create a `.env` file with the following variables:
   ```
   OPENAI_API_KEY=your_openai_api_key
   MONGODB_URI=your_mongodb_connection_string
   ```

3. Run the application:
   ```
   uvicorn main:app --reload
   ```

## API Endpoints

- `GET /get-topics` - Get the latest trending topics
- `POST /fetch-topics` - Manually trigger topic fetching
- `GET /health` - Health check endpoint

## Deployment on Digital Ocean Droplet

1. Clone this repository on your droplet
2. Install dependencies: `pip install -r requirements.txt`
3. Set up environment variables or create a `.env` file
4. Install and set up systemd to run the application as a service
5. Or use `gunicorn` to run the application:
   ```
   gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app
   ```

## Environment Variables

- `OPENAI_API_KEY`: Required for GPT-4o API calls
- `MONGODB_URI`: MongoDB connection string 