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
- `GET /db-status` - Diagnostic endpoint to check MongoDB connection status

## Troubleshooting

If you encounter issues with MongoDB connectivity or data retrieval:

1. Check the `/db-status` endpoint to verify MongoDB connection
2. Ensure the database name is `medical_topics_db` and collection name is `topics`
3. Check server logs for any errors with the MongoDB connection
4. Manually trigger a fetch using the `/fetch-topics` endpoint
5. Verify MONGODB_URI in your environment variables

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