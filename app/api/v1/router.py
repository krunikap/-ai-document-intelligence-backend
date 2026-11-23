from fastapi import APIRouter

from app.api.v1.endpoints import auth, chats, documents, health

api_router = APIRouter()

api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(documents.router)
api_router.include_router(chats.router)
api_router.include_router(chats.document_chat_router)
