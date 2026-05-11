from pydantic import BaseModel

class LoginRequest(BaseModel):
    email: str
    password: str

class LoginResponse(BaseModel):
    role: str
    name: str
    email: str

class SessionResponse(BaseModel):
    id: str
    email: str
    role: str
    name: str

class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "VIEWER"
