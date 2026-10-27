#schemas defn for the JSON response from the frontend we are expecting.
from typing import Optional

from pydantic import BaseModel, Field, field_validator

MAX_SOURCE_SIZE_BYTES = 50 * 1024

#code requst model to fetch the source code from the frontend.
class CodeRequest(BaseModel):
    language : str = Field(default="python")
    source_code : str=Field(min_length=1)

    @field_validator("source_code")
    @classmethod
    def validate_source_size(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_code must not be empty.")
        if len(value.encode("utf-8")) > MAX_SOURCE_SIZE_BYTES:
            raise ValueError("source_code exceeds the 50 KB limit.")
        return value
#code response model to send the code response that the frontend would return.
class CodeResponse(BaseModel):
    p_id: str
    message: str
    language: str
    output: str
    stderr: str
    exit_code: int
    execution_time_ms: int
    status: str


class OptimizationRequest(BaseModel):
    p_id: str = Field(min_length=1)
    population_size: Optional[int] = Field(default=None, ge=2)
    generations: Optional[int] = Field(default=None, ge=1)
    max_chromosome_length: Optional[int] = Field(default=None, ge=1)
    mutation_probability: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    benchmark_runs: Optional[int] = Field(default=None, ge=1)
    random_seed: Optional[int] = None
    objective: Optional[str] = None
    tournament_size: Optional[int] = Field(default=None, ge=1)
