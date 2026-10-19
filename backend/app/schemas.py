#schemas defn for the JSON response from the frontend we are expecting.
from pydantic import BaseModel, Field, field_validator

class CodeRequest(BaseModel):
    language : str = Field(default="python")
    source_code : str=Field(min_length=1)

class CodeResponse(BaseModel):
    message : str
    language : str
    output : str
