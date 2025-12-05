from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

class Database:
    client: AsyncIOMotorClient = None

    def connect(self):
        self.client = AsyncIOMotorClient(settings.MONGO_URI)
        print(f"✅ Connected to MongoDB at {settings.MONGO_URI}")

    def close(self):
        if self.client:
            self.client.close()
            print("🛑 Disconnected from MongoDB")

    def get_db(self):
        return self.client[settings.MONGO_DB_NAME]

    def get_collection(self, name: str):
        return self.get_db()[name]

db = Database()

def get_event_collection():
    return db.get_collection(settings.MONGO_COLL_NAME)

def get_victoria_collection():
    return db.get_collection(settings.MONGO_COLL_VICTORIA)
