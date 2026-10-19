#schemas defn for the JSON response from the frontend we are expecting.
from pydantic import BaseModel, Field, field_validator

#code requst model to fetch the source code from the frontend.
class CodeRequest(BaseModel):
    language : str = Field(default="python")
    source_code : str=Field(min_length=1)
#code response model to send the code response that the frontend would return.
class CodeResponse(BaseModel):
    p_id : str
    message : str
    language : str
    output : str
    