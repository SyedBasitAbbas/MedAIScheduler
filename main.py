import logging
import os
from dotenv import load_dotenv
import datetime
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from pymongo.server_api import ServerApi
from pydantic import BaseModel
import nest_asyncio
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import uuid
from typing import List
from openai import OpenAI

# Apply nest_asyncio to allow nested event loops
nest_asyncio.apply()

# Set up logging
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("scheduler.log"), logging.StreamHandler()]
)

logger.info(f"Current working directory: {os.getcwd()}")
env_file_path = os.path.join(os.getcwd(), ".env")
logger.info(f"Looking for .env file at: {env_file_path}")
if os.path.exists(env_file_path):
    logger.info(".env file found")
else:
    logger.warning(".env file not found")

load_dotenv()

# API Keys and MongoDB URI from environment variables
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
MONGODB_URI = os.environ.get(
    "MONGODB_URI",
    "mongodb+srv://syedbasitabbas10:FZg3aL0FbRYyxGdh@topmedicalarticles.pfo2g.mongodb.net/?retryWrites=true&w=majority&appName=TopMedicalArticles"
)

logger.info(f"OPENAI_API_KEY: {'Set' if OPENAI_API_KEY else 'Not set'}")
logger.info(f"MONGODB_URI: {'Set' if MONGODB_URI else 'Not set'}")

if not all([OPENAI_API_KEY, MONGODB_URI]):
    raise ValueError("One or more required keys (API keys or MongoDB URI) are missing.")

# Initialize OpenAI client
openai_client = OpenAI(api_key=OPENAI_API_KEY)
logger.info("OpenAI client initialized.")

# Connect to MongoDB
try:
    client_mongo = MongoClient(MONGODB_URI, server_api=ServerApi('1'))
    client_mongo.admin.command('ping')
    logger.info("Successfully connected to MongoDB!")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {str(e)}")
    raise ValueError(f"Error connecting to MongoDB: {str(e)}")

db = client_mongo['TopMedicalArticles']
collection = db['topics']  # Topics collection

# FastAPI app initialization
app = FastAPI()

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Create a scheduler
scheduler = AsyncIOScheduler()

# Fetch and store topics function
async def fetch_and_store_topics():
    try:
        aus_tz = pytz.timezone("Australia/Sydney")
        current_time = datetime.datetime.now(aus_tz)
        logger.info(f"Starting topic fetch at {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')} in Australian time")

        # Add a unique identifier to the prompt to avoid caching
        unique_id = str(uuid.uuid4())
        prompt = f"""As of {current_time.strftime('%Y-%m-%d %H:%M:%S %Z')}, perform a fresh, real-time search of the web and current online discussions to identify the 5 most talked-about medical topics today. Focus on trends that have emerged or gained significant attention in the last 24 hours. This request is unique (ID: {unique_id}) to ensure a new search. Provide only the list of topics, ranked by popularity, that are trending and suitable for creating articles for medical students. Just return the topic names, don't say any other thing, and don't add numbering."""
        
        completion = openai_client.chat.completions.create(
            model="gpt-4o-search-preview",
            messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )
        # Split the response into individual topics
        topics = completion.choices[0].message.content.strip().split("\n")
        # Clean up each topic: remove leading Markdown list markers (e.g., "- ", "* ", "1. ") and extra whitespace
        cleaned_topics = []
        for topic in topics:
            topic = topic.strip()  # Remove leading/trailing whitespace
            # Remove common Markdown list markers
            for marker in ['- ', '* ', '1. ', '2. ', '3. ', '4. ', '5. ']:
                if topic.startswith(marker):
                    topic = topic[len(marker):].strip()
                    break
            if topic:  # Only add non-empty topics
                cleaned_topics.append(topic)
        
        logger.info(f"Fetched and cleaned topics: {cleaned_topics}")
        
        # Clear old topics and insert new ones
        deleted_count = collection.delete_many({}).deleted_count
        logger.info(f"Deleted {deleted_count} old topic documents from MongoDB")
        
        insert_result = collection.insert_one({"topics": cleaned_topics, "timestamp": current_time.isoformat()})
        logger.info(f"Stored {len(cleaned_topics)} trending topics in MongoDB with timestamp {current_time.isoformat()}, ID: {insert_result.inserted_id}")
        
        return {"topics": cleaned_topics}
    except Exception as e:
        logger.error(f"Error fetching and storing topics: {str(e)}")
        raise

# Run task on startup and schedule it
@app.on_event("startup")
async def startup_event():
    try:
        # Initial fetch
        await fetch_and_store_topics()
        logger.info("Initial topic fetch completed at startup")
        
        # Schedule the task to run every day at 12 AM Australia/Sydney time
        scheduler.add_job(
            fetch_and_store_topics,
            'cron',
            hour=0,  # 12 AM
            minute=0,
            second=0,
            timezone=pytz.timezone("Australia/Sydney")
        )
        scheduler.start()
        logger.info("Scheduled topic fetching every day at 12 AM Australia/Sydney time")
    except Exception as e:
        logger.error(f"Failed to fetch initial topics or set up scheduler: {str(e)}")
        raise

# Pydantic models
class TopicsResponse(BaseModel):
    topics: List[str]

# FastAPI endpoints
@app.get("/get-topics", response_model=TopicsResponse)
async def get_topics():
    try:
        logger.info("Attempting to fetch topics from MongoDB")
        document = collection.find_one({}, sort=[("timestamp", -1)])
        logger.info(f"Retrieved document from MongoDB: {document}")

        if not document:
            logger.warning("No documents found in MongoDB - returning empty list")
            return JSONResponse(content={"topics": []}, headers={"Cache-Control": "no-store"})

        if 'topics' not in document:
            logger.error("Document found but 'topics' field is missing - returning empty list")
            return JSONResponse(content={"topics": []}, headers={"Cache-Control": "no-store"})

        if 'timestamp' not in document:
            logger.warning("Document found but 'timestamp' field is missing")

        topics = document['topics']
        timestamp = document.get('timestamp', 'unknown')

        if not isinstance(topics, list):
            logger.error(f"Topics field is not a list: {topics} - returning empty list")
            return JSONResponse(content={"topics": []}, headers={"Cache-Control": "no-store"})

        logger.info(f"Successfully retrieved {len(topics)} topics from MongoDB with timestamp {timestamp}")
        return JSONResponse(content={"topics": topics}, headers={"Cache-Control": "no-store"})
    except Exception as e:
        logger.error(f"Error fetching topics from MongoDB: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error fetching topics from MongoDB: {str(e)}")

@app.post("/fetch-topics")
async def trigger_fetch_topics():
    try:
        result = await fetch_and_store_topics()
        return {"status": "success", "topics": result["topics"]}
    except Exception as e:
        logger.error(f"Failed to fetch topics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch topics: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    server.run() 