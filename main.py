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
from google import genai
from google.genai import types

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

# ——— Gemini client setup ———
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
logger.info(f"GEMINI_API_KEY: {'Set' if GEMINI_API_KEY else 'Not set'}")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable is required.")
    
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
logger.info("Gemini client initialized.")

# Connect to MongoDB
try:
    client_mongo = MongoClient(MONGODB_URI, server_api=ServerApi('1'))
    client_mongo.admin.command('ping')
    db = client_mongo['medical_topics_db']
    logger.info(f"Successfully connected to MongoDB! Database: medical_topics_db")
    # Log available collections
    collections = db.list_collection_names()
    logger.info(f"Available collections: {collections}")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {str(e)}")
    raise ValueError(f"Error connecting to MongoDB: {str(e)}")

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
        prompt = f"""You MUST use the Google Search tool to search for trending medical topics today ({current_time.strftime('%Y-%m-%d')}).
        
        Search for "trending medical news topics today" or "latest medical research topics" or similar queries to find fresh information.
        
        Based on your search results, compile exactly 5 trending medical topics that would be interesting to medical students.
        
        Return ONLY the topic names, one per line, with no numbering, commentary, or other text. You must return 5 topics regardless of search results.
        
        This request ID is {unique_id} to avoid caching."""
        
        logger.info(f"Sending API request to Gemini with prompt ID: {unique_id}")

        # — Enable Google Search plugin for live data —
        tools = [
            types.Tool(google_search=types.GoogleSearch()),
        ]
        generate_config = types.GenerateContentConfig(
            tools=tools,
            response_mime_type="text/plain",
            temperature=0.7,   
            top_p=0.9          
        )

        # Stream Gemini output and concatenate
        response_chunks = []
        for chunk in gemini_client.models.generate_content_stream(
            model="gemini-2.5-flash-preview-04-17",
            contents=[types.Content(role="user", parts=[types.Part.from_text(text=prompt)])],
            config=generate_config,
        ):
            response_chunks.append(chunk.text)
        full_response = "".join(response_chunks).strip()
        logger.info("Received response from Gemini")

        # Split into individual topics
        topics = full_response.split("\n")
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
        
        if not cleaned_topics:
            logger.error("No topics were extracted from the API response")
            return {"topics": []}
            
        # Verify connection before operation
        try:
            client_mongo.admin.command('ping')
            logger.info("MongoDB connection verified before operation")
        except Exception as e:
            logger.error(f"MongoDB connection failed before operation: {str(e)}")
            raise
            
        # Clear old topics and insert new ones
        deleted_count = collection.delete_many({}).deleted_count
        logger.info(f"Deleted {deleted_count} old topic documents from MongoDB")
        
        # Create a document with _id and topics array format matching the MongoDB screenshot
        new_document = {
            "topics": cleaned_topics,
            "timestamp": current_time.isoformat()
        }
        
        logger.info(f"Inserting document: {new_document}")
        insert_result = collection.insert_one(new_document)
        logger.info(f"Stored {len(cleaned_topics)} trending topics in MongoDB with timestamp {current_time.isoformat()}, ID: {insert_result.inserted_id}")
        
        # Verify the document was inserted
        inserted_doc = collection.find_one({"_id": insert_result.inserted_id})
        if inserted_doc:
            logger.info(f"Successfully verified document insertion with ID: {insert_result.inserted_id}")
        else:
            logger.error(f"Failed to verify document insertion with ID: {insert_result.inserted_id}")
        
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
        # List all collections in the database to verify
        collections = db.list_collection_names()
        logger.info(f"Available collections in medical_topics_db: {collections}")
        
        # Count documents to verify
        doc_count = collection.count_documents({})
        logger.info(f"Number of documents in topics collection: {doc_count}")
        
        document = collection.find_one({}, sort=[("timestamp", -1)])
        logger.info(f"Retrieved document from MongoDB: {document}")

        if not document:
            logger.warning("No documents found in MongoDB - returning empty list")
            # Trigger fetch if no documents are found
            logger.info("Triggering initial topic fetch since no documents were found")
            await fetch_and_store_topics()
            document = collection.find_one({}, sort=[("timestamp", -1)])
            if not document:
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
        logger.info("Triggering topic fetch via /fetch-topics endpoint")
        result = await fetch_and_store_topics()
        logger.info(f"Topic fetch completed via /fetch-topics endpoint. Fetched {len(result['topics'])} topics")
        return {
            "status": "success",
            "topics": result["topics"],
            "message": f"Successfully fetched and stored {len(result['topics'])} topics"
        }
    except Exception as e:
        logger.error(f"Failed to fetch topics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch topics: {str(e)}")

@app.post("/update-topics-now")
async def update_topics_now():
    try:
        logger.info("Immediate topic update triggered via /update-topics-now")
        result = await fetch_and_store_topics()
        logger.info("Immediate topic update completed")
        return {"status": "success", "topics": result["topics"], "message": "Topics updated immediately"}
    except Exception as e:
        logger.error(f"Failed to update topics immediately: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update topics immediately: {str(e)}")

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/db-status")
async def db_status():
    try:
        # Check MongoDB connection
        client_mongo.admin.command('ping')
        
        # Get list of collections in the database
        collections = db.list_collection_names()
        
        # Count documents in the topics collection
        topic_count = collection.count_documents({})
        
        # Get latest document for reference
        latest_doc = collection.find_one({}, sort=[("timestamp", -1)])
        latest_doc_id = str(latest_doc.get("_id")) if latest_doc else None
        
        return {
            "status": "connected",
            "database": "medical_topics_db",
            "collections": collections,
            "topics_collection_count": topic_count,
            "latest_document_id": latest_doc_id,
            "latest_document_timestamp": latest_doc.get("timestamp") if latest_doc else None,
            "topics_count": len(latest_doc.get("topics", [])) if latest_doc else 0
        }
    except Exception as e:
        logger.error(f"Error checking database status: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }

if __name__ == "__main__":
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="asyncio")
    server = uvicorn.Server(config)
    server.run()
