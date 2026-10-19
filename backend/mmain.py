
from fastapi import FastAPI

#cors import section
from app.middleware import register_middleware
from app.routes import router

app = FastAPI(
    title="Genetic Compiler Backend",
    description="Backend for the Genetic Compiler project",
    version="1.0.0",
)

#register middleware
register_middleware(app)

#include the router
app.include_router(router)
