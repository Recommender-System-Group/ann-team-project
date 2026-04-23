"""
main.py — FastAPI Backend (Folio)
Version complète + JWT compatible frontend
"""

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
import jwt

import database as db


# ══════════════════════════════════════════════════════════
# 🔐 JWT CONFIG
# ══════════════════════════════════════════════════════════

SECRET_KEY = "secret_folio_key"   # ⚠️ change en prod
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60


def create_token(data: dict):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRE_MINUTES)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str):
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


# ══════════════════════════════════════════════════════════
# 🚀 APP INIT
# ══════════════════════════════════════════════════════════

app = FastAPI(
    title="Folio API",
    description="Book Recommendation Engine",
    version="1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ⚠️ change en prod
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBearer()


# ══════════════════════════════════════════════════════════
# 🔐 AUTH DEPENDENCY
# ══════════════════════════════════════════════════════════

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    try:
        payload = decode_token(token)
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Session expirée")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")


# ══════════════════════════════════════════════════════════
# 📦 SCHEMAS
# ══════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class RateRequest(BaseModel):
    book_id: str
    rating: int = Field(..., ge=1, le=5)


class ReviewRequest(BaseModel):
    book_id: str
    review: str = Field(..., min_length=5)


class ReadRequest(BaseModel):
    book_id: str


# ══════════════════════════════════════════════════════════
# 🔐 AUTH ROUTES
# ══════════════════════════════════════════════════════════

@app.post("/auth/register")
def register(data: RegisterRequest):
    result = db.register_user(data.username, data.email, data.password)
    # Retourner JSON direct — pas HTTPException — pour que le frontend lise data.ok
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    return {"ok": True, "message": "Compte créé avec succès", "username": data.username}


@app.post("/auth/login")
def login(data: LoginRequest):
    result = db.login_user(data.username, data.password)
    # Retourner JSON direct — pas HTTPException — pour que le frontend lise data.ok
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}

    token = create_token({
        "user_id": result["user_id"],
        "username": result["username"]
    })

    return {
        "ok": True,
        "token": token,
        "user_id": result["user_id"],
        "username": result["username"]
    }


# ══════════════════════════════════════════════════════════
# 📚 BOOKS
# ══════════════════════════════════════════════════════════

@app.get("/books")
def list_books(
    genre: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    user=Depends(get_current_user)
):
    if q:
        return db.search_books(q, limit)
    return db.get_books(genre=genre, limit=limit, offset=offset)


@app.get("/books/{book_id}")
def get_book(book_id: str, user=Depends(get_current_user)):
    book = db.get_book_by_id(book_id)
    if not book:
        return {"ok": False, "error": "Livre introuvable"}
    reviews = db.get_book_reviews(book_id)
    return {**book, "reviews": reviews, "ok": True}


# ══════════════════════════════════════════════════════════
# ⭐ INTERACTIONS
# ══════════════════════════════════════════════════════════

@app.get("/interactions")
def get_interaction(book_id: str, user=Depends(get_current_user)):
    return db.get_user_interaction(user["user_id"], book_id)


@app.post("/interactions/read")
def mark_read(data: ReadRequest, user=Depends(get_current_user)):
    return db.mark_as_read(user["user_id"], data.book_id)


@app.post("/interactions/rate")
def rate(data: RateRequest, user=Depends(get_current_user)):
    result = db.rate_book(user["user_id"], data.book_id, data.rating)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    return result


@app.post("/interactions/review")
def review(data: ReviewRequest, user=Depends(get_current_user)):
    result = db.add_review(user["user_id"], data.book_id, data.review)
    if not result["ok"]:
        return {"ok": False, "error": result["error"]}
    return result


# ══════════════════════════════════════════════════════════
# 👤 USER
# ══════════════════════════════════════════════════════════

@app.get("/user/profile")
def profile(user=Depends(get_current_user)):
    result = db.get_user_by_id(user["user_id"])
    if not result:
        return {"ok": False, "error": "Utilisateur introuvable"}
    return {**result, "ok": True}


@app.get("/user/ratings")
def ratings(user=Depends(get_current_user)):
    return db.get_user_ratings(user["user_id"])


# ══════════════════════════════════════════════════════════
# 🧪 HEALTH
# ══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    try:
        stats = db.get_stats()
        return {"status": "ok", **stats}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# ══════════════════════════════════════════════════════════
# ▶️ RUN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)