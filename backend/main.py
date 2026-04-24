from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timedelta
import jwt
import numpy as np
import pickle
from tensorflow.keras.models import load_model
import tensorflow as tf
import database as db
import random


# ══════════════════════════════════════════════════════════
# 🔐 JWT CONFIG
# ══════════════════════════════════════════════════════════

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

try:
    # On charge le dossier qui contient saved_model.pb
    MODEL_PATH = str(BASE_DIR.parent / "ANNModel/clean_model")
    ANN_MODEL = tf.saved_model.load(MODEL_PATH)
    infer = ANN_MODEL.signatures["serving_default"]
    print("✅ TensorFlow SavedModel loaded successfully")
except Exception as e:
    print(f"❌ Error loading model: {e}")

# Tes encodeurs restent les mêmes
user_enc = pickle.load(open(BASE_DIR.parent / "ANNModel/user_encoder.pkl", "rb"))
book_enc = pickle.load(open(BASE_DIR.parent / "ANNModel/book_encoder.pkl", "rb"))

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

#Récupper les livres de la base de donnée
@app.get("/books")
def get_books(genre: str = None, q: str = None, limit: int = 100):
    try:
        if q:
            return db.search_books(q, limit=limit)
        else:
            return db.get_books(genre=genre, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health():
    try:
        stats = db.get_stats()
        return {"status": "ok", **stats}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.get("/books/random")
def get_random_books(limit: int = 6):
    try:
        books = db.get_books(limit=200)  # on prend un pool
        import random
        random.shuffle(books)
        return books[:limit]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/books/{book_id:path}")
def get_book(book_id: str):
    book = db.get_book_by_id(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Livre introuvable")
    return book

@app.get("/books/{book_id:path}/reviews")
def get_book_reviews(book_id: str):
    return db.get_book_reviews(book_id)

@app.post("/interactions/read")
def mark_read(data: ReadRequest, user=Depends(get_current_user)):
    return db.mark_as_read(user["user_id"], data.book_id)

@app.post("/interactions/rate")
def rate(data: RateRequest, user=Depends(get_current_user)):
    return db.rate_book(user["user_id"], data.book_id, data.rating)

@app.post("/interactions/review")
def review(data: ReviewRequest, user=Depends(get_current_user)):
    return db.add_review(user["user_id"], data.book_id, data.review)

@app.get("/interactions")
def get_interaction(book_id: str, user=Depends(get_current_user)):
    return db.get_user_interaction(user["user_id"], book_id)


@app.post("/user/preferences")
def save_preferences(data: dict, user=Depends(get_current_user)):

    user_id = user["user_id"]
    ratings = data.get("ratings", {})
    n = data.get("n", 10)

    # 🔥 SAVE RATINGS
    for book_id, rating in ratings.items():
        db.rate_book(user_id, book_id, rating)

    # 🔥 RANDOM BOOKS
    books = db.get_random_books_for_user(user_id, n)

    return {
        "ok": True,
        "ratings_saved": len(ratings),
        "recommendations": books
    }

@app.get("/user/library")
def get_user_library(current_user: dict = Depends(get_current_user)):
    data = db.get_user_library(current_user["user_id"])
    return data

@app.get("/user/library/is_read")
def get_user_library_is_read(current_user: dict = Depends(get_current_user)):
    data = db.get_user_library(current_user["user_id"])
    
    result = [row["is_read"] for row in data]
    
    return result

@app.get("/user/library/encoded")
def get_user_library_encoded(current_user: dict = Depends(get_current_user)):
    data = db.get_user_library(current_user["user_id"])
    
    # Générer des valeurs uniques aléatoires entre 800 et 900
    values = random.sample(range(800, 901), len(data))
    
    result = {
        row["book_id"]: values[i]
        for i, row in enumerate(data)
    }
    
    return result

@app.get("/user/library/reviews")
def get_user_library_reviews(current_user: dict = Depends(get_current_user)):
    data = db.get_user_library(current_user["user_id"])
    
    result = [
        1 if row["review"] else 0
        for row in data
    ]
    
    return result

@app.post("/recommend")
def recommend(data: dict, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"] # Récupération de l'ID (Etape 2)
    n = data.get("n", 10)        # Nombre choisi par l'utilisateur (Etape 1)

    # 1️⃣ Récupérer les 40 livres et interactions (Etape 3)
    library = db.get_user_library(user_id)
    
    # On ne veut recommander que des livres NON LUS (is_read == 0)
    to_predict = [b for b in library if b["is_read"] == 0]
    
    if not to_predict:
        return {"recommendations": []}

    # 2️⃣ Encodage pour le modèle
    try:
        user_idx = user_enc.transform([user_id])[0]
    except:
        user_idx = 0 # Gestion du cas où l'user n'est pas dans l'encodeur

    book_ids = [b["book_id"] for b in to_predict]
    try:
        books_encoded = book_enc.transform(book_ids)
    except:
        books_encoded = np.zeros(len(book_ids))

    # 3️⃣ Préparation des Tenseurs TensorFlow (Etape 4)
    # Note : Vérifie les noms des inputs de ton modèle (input_1, input_2...)
    user_input  = tf.constant(np.full((len(to_predict), 1), user_idx), dtype=tf.float32)
    book_input  = tf.constant(books_encoded.reshape(-1, 1), dtype=tf.float32)
    other_input = tf.constant(np.array([[b["is_read"], b["has_review"]] for b in to_predict]), dtype=tf.float32)

    # 4️⃣ Inférence (Prédiction)
    # On utilise les clés par défaut de Keras/TF pour les modèles multi-inputs
    predictions_dict = infer(
            user_input=user_input, 
            book_input=book_input, 
            other_input=other_input
    )
    
    # Récupérer le résultat (la première clé du dictionnaire de sortie)
    out_key = list(predictions_dict.keys())[0]
    preds = predictions_dict[out_key].numpy().flatten()

    # Conversion en note 1-5 (si ton modèle sort du 0-1)
    preds_reelles = np.clip(preds * 4 + 1, 1.0, 5.0)

    # 5️⃣ Trier les N meilleurs (Etape 5)
    top_indices = preds_reelles.argsort()[-n:][::-1]

    final_recs = []
    for idx in top_indices:
        book = to_predict[idx]
        final_recs.append({
            "book_id": book["book_id"],
            "title": book["title"],
            "author": book["author"],
            "genre": book["genre"],
            "predicted_rating": round(float(preds_reelles[idx]), 2),
            "score": round(float(preds_reelles[idx]) / 5, 2) # Pour la barre de progression
        })

    return {
        "user_id": user_id,
        "recommendations": final_recs
    }
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)