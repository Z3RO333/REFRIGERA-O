import uuid
from datetime import datetime
from pydantic import BaseModel

class BaseResponse(BaseModel):
    class Config:
        from_attributes = True

class PaginatedResponse(BaseModel):
    total: int
    page: int
    per_page: int
    items: list
