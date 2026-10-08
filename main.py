from fastapi import FastAPI
from myproject.routers.auth import router as auth_router
from myproject.routers.chats import router as chats_router
from myproject.routers.documents import router as documents_router


app = FastAPI(
    title="AI Document Intelligence API"
)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(chats_router)


@app.get("/")
def home():
    return {
        "message": "AI Document Intelligence API is running"
    }
