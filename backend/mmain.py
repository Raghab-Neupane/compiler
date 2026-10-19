
from fastapi import FastAPI

#cors import section
from app.middleware import register_middleware

app = FastAPI(
    title="Genetic Compiler Backend",
    description="Backend for the Genetic Compiler project",
    version="1.0.0",
)

register_middleware(app)
