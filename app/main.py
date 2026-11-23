from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core import settings
from app.core.exception_handlers import register_exception_handlers


app = FastAPI(
    title=settings.APP_NAME
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_exception_handlers(app)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)
