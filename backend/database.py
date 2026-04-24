import mysql.connector
import hashlib
import requests
from datetime import datetime


# ── CONFIGURATION ──
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "",   # change ici
    "database": "folio",
    "charset":  "utf8mb4"
}

# ══════════════════════════════════════════
#  CONNEXION
# ══════════════════════════════════════════

def get_connection():
    return mysql.connector.connect(**DB_CONFIG)

def hash_password(password: str) -> str:
    """Hash SHA-256 — jamais stocker en clair"""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


# ══════════════════════════════════════════
#  CRÉATION DES TABLES
# ══════════════════════════════════════════

def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # Table 1 : utilisateurs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INT AUTO_INCREMENT PRIMARY KEY,
            username      VARCHAR(50)  UNIQUE NOT NULL,
            email         VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(64)  NOT NULL,
            created_at    DATETIME DEFAULT NOW()
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # Table 2 : livres (importés depuis Goodreads CSV)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS books (
            book_id     VARCHAR(50)  PRIMARY KEY,
            title       VARCHAR(300) NOT NULL,
            author      VARCHAR(200),
            genre       VARCHAR(100),
            description TEXT,
            image_url   VARCHAR(500),
            avg_rating  FLOAT DEFAULT 0
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    # Table 3 : interactions user ↔ livre
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_book_interactions (
            id         INT AUTO_INCREMENT PRIMARY KEY,
            user_id    INT         NOT NULL,
            book_id    VARCHAR(50) NOT NULL,
            is_read    TINYINT     DEFAULT 0,
            rating     INT         DEFAULT 0,
            review     TEXT        DEFAULT NULL,
            created_at DATETIME    DEFAULT NOW(),
            FOREIGN KEY (user_id) REFERENCES users(id)    ON DELETE CASCADE,
            FOREIGN KEY (book_id) REFERENCES books(book_id) ON DELETE CASCADE,
            UNIQUE KEY unique_user_book (user_id, book_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """)

    genres = [
        "fantasy", "science fiction", "romance", "mystery",
        "history", "horror", "biography", "fiction"
    ]

    inserted = 0

    for genre in genres:
        url = f"https://openlibrary.org/search.json?q={genre}"
        data = requests.get(url).json()

        for b in data.get("docs", []):

            if inserted >= 40:
                break

            title = b.get("title")
            if not title:
                continue

            author = b.get("author_name", ["Unknown"])[0]
            external_id = b.get("key", "")

            cover_id = b.get("cover_i")
            image_url = (
                f"https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"
                if cover_id else None
            )

            # 📌 Description simple (car API n'en donne pas)
            description = f"{title} est un livre de genre {genre} écrit par {author}."

            # 📌 Rating simulé (OpenLibrary ne donne pas rating fiable)
            avg_rating = round(3.5 + (hash(title) % 15) / 10, 1)

            sql = """
            INSERT INTO books 
            (book_id, title, author, genre, description, image_url, avg_rating)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(sql, (
                external_id,
                title,
                author,
                genre,
                description,
                image_url,
                avg_rating
            ))

            inserted += 1

        if inserted >= 40:
            break

    conn.commit()
    cursor.close()
    conn.close()
    # print("Tables créées avec succès.")


# ══════════════════════════════════════════
#  USERS — AUTH
# ══════════════════════════════════════════

def register_user(username: str, email: str, password: str) -> dict:
    """Créer un compte utilisateur. Retourne {ok, user_id} ou {error}"""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (username, email, hash_password(password))
        )
        conn.commit()
        return {"ok": True, "user_id": cursor.lastrowid, "username": username}
    except mysql.connector.IntegrityError:
        return {"ok": False, "error": "Username ou email déjà utilisé"}
    finally:
        cursor.close(); conn.close()


def login_user(username: str, password: str) -> dict:
    """Vérifier les identifiants. Retourne {ok, user_id, username} ou {error}"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT id, username FROM users WHERE username=%s AND password_hash=%s",
        (username, hash_password(password))
    )
    user = cursor.fetchone()
    cursor.close(); conn.close()
    if not user:
        return {"ok": False, "error": "Identifiants incorrects"}
    return {"ok": True, "user_id": user["id"], "username": user["username"]}


def get_user_by_id(user_id: int) -> dict:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT id, username, email, created_at FROM users WHERE id=%s", (user_id,))
    user = cursor.fetchone()
    cursor.close(); conn.close()
    return user


# ══════════════════════════════════════════
#  BOOKS — CRUD
# ══════════════════════════════════════════

def get_books(genre: str = None, author: str = None, limit: int = 20, offset: int = 0) -> list:
    """Récupérer les livres avec filtres optionnels"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT * FROM books WHERE 1=1"
    params = []
    if genre:
        query += " AND genre = %s"
        params.append(genre)
    if author:
        query += " AND author LIKE %s"
        params.append(f"%{author}%")
    query += " ORDER BY avg_rating DESC LIMIT %s OFFSET %s"
    params += [limit, offset]
    cursor.execute(query, params)
    books = cursor.fetchall()
    cursor.close(); conn.close()
    return books


def search_books(query: str, limit: int = 20) -> list:
    """Recherche texte dans titre et auteur"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM books WHERE title LIKE %s OR author LIKE %s ORDER BY avg_rating DESC LIMIT %s",
        (f"%{query}%", f"%{query}%", limit)
    )
    books = cursor.fetchall()
    cursor.close(); conn.close()
    return books


def get_book_by_id(book_id: str) -> dict:
    """Récupérer le détail complet d'un livre"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM books WHERE book_id=%s", (book_id,))
    book = cursor.fetchone()
    cursor.close(); conn.close()
    return book


def insert_book(book: dict):
    """Insérer un livre depuis le dataset CSV"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT IGNORE INTO books (book_id, title, author, genre, description, image_url, avg_rating)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (
        book.get("book_id"), book.get("title"), book.get("author"),
        book.get("genre"), book.get("description"), book.get("image_url"),
        book.get("avg_rating", 0)
    ))
    conn.commit()
    cursor.close(); conn.close()


# ══════════════════════════════════════════
#  USER_BOOK_INTERACTIONS — CRUD
# ══════════════════════════════════════════

def mark_as_read(user_id: int, book_id: str) -> dict:
    """Bouton is_read — passe de 0 à 1"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_book_interactions (user_id, book_id, is_read)
        VALUES (%s, %s, 1)
        ON DUPLICATE KEY UPDATE is_read = 1
    """, (user_id, book_id))
    conn.commit()
    cursor.close(); conn.close()
    return {"ok": True, "is_read": 1}


def rate_book(user_id: int, book_id: str, rating: int) -> dict:
    """L'utilisateur note un livre (1-5)"""
    if rating < 1 or rating > 5:
        return {"ok": False, "error": "La note doit être entre 1 et 5"}
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_book_interactions (user_id, book_id, rating)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE rating = %s
    """, (user_id, book_id, rating, rating))
    conn.commit()
    # Recalcul de la moyenne dans books
    cursor.execute("""
        UPDATE books SET avg_rating = (
            SELECT AVG(rating) FROM user_book_interactions
            WHERE book_id = %s AND rating > 0
        ) WHERE book_id = %s
    """, (book_id, book_id))
    conn.commit()
    cursor.close(); conn.close()
    return {"ok": True, "rating": rating}


def add_review(user_id: int, book_id: str, review: str) -> dict:
    """L'utilisateur écrit une review"""
    if not review or len(review.strip()) < 5:
        return {"ok": False, "error": "La review est trop courte"}
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO user_book_interactions (user_id, book_id, review)
        VALUES (%s, %s, %s)
        ON DUPLICATE KEY UPDATE review = %s
    """, (user_id, book_id, review.strip(), review.strip()))
    conn.commit()
    cursor.close(); conn.close()
    return {"ok": True, "message": "Review enregistrée"}


def get_user_interaction(user_id: int, book_id: str) -> dict:
    """Récupérer l'interaction d'un user pour un livre précis"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute(
        "SELECT * FROM user_book_interactions WHERE user_id=%s AND book_id=%s",
        (user_id, book_id)
    )
    row = cursor.fetchone()
    cursor.close(); conn.close()
    return row or {"is_read": 0, "rating": 0, "review": None}


def get_user_ratings(user_id: int) -> list:
    """Récupérer toutes les notes d'un utilisateur — pour le modèle ANN"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.user_id, u.book_id, b.title, u.rating, u.is_read, u.review
        FROM user_book_interactions u
        JOIN books b ON u.book_id = b.book_id
        WHERE u.user_id = %s AND u.rating > 0
        ORDER BY u.created_at DESC
    """, (user_id,))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    return rows


def get_all_interactions_for_model() -> list:
    """Charger toutes les interactions pour entraîner le modèle ANN"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT user_id, book_id, rating
        FROM user_book_interactions
        WHERE rating > 0
    """)
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    return rows


def get_book_reviews(book_id: str) -> list:
    """Récupérer tous les avis d'un livre"""
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.username, i.rating, i.review, i.created_at
        FROM user_book_interactions i
        JOIN users u ON i.user_id = u.id
        WHERE i.book_id = %s AND i.review IS NOT NULL
        ORDER BY i.created_at DESC
    """, (book_id,))
    rows = cursor.fetchall()
    cursor.close(); conn.close()
    return rows


def save_recommendations(user_id: int, recommendations: list):
    """Sauvegarder les recommandations générées par le modèle"""
    conn = get_connection()
    cursor = conn.cursor()
    for rec in recommendations:
        cursor.execute("""
            INSERT INTO user_book_interactions (user_id, book_id)
            VALUES (%s, %s)
            ON DUPLICATE KEY UPDATE user_id = user_id
        """, (user_id, rec["book_id"]))
    conn.commit()
    cursor.close(); conn.close()


# ══════════════════════════════════════════
#  STATS — pour health.html
# ══════════════════════════════════════════

def get_stats() -> dict:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM books")
    books_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM user_book_interactions WHERE rating > 0")
    ratings_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM user_book_interactions WHERE review IS NOT NULL")
    reviews_count = cursor.fetchone()[0]
    cursor.close(); conn.close()
    return {
        "users": users_count,
        "books": books_count,
        "ratings": ratings_count,
        "reviews": reviews_count
    }


# ══════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════


def get_random_books_for_user(user_id: int, n: int):
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT b.*
        FROM books b
        WHERE b.book_id NOT IN (
            SELECT book_id
            FROM user_book_interactions
            WHERE user_id = %s
        )
        ORDER BY RAND()
        LIMIT %s
    """, (user_id, n))

    data = cursor.fetchall()

    cursor.close()
    conn.close()
    return data

def get_user_library(user_id: int) -> list:
    conn = get_connection()
    cursor = conn.cursor(dictionary=True)
    # On fait un LEFT JOIN pour avoir TOUS les livres (b.*) 
    # et on récupère l'interaction si elle existe pour cet user_id
    cursor.execute("""
        SELECT 
            b.book_id,
            b.title,
            b.author,
            b.genre,
            COALESCE(i.is_read, 0) AS is_read,
            COALESCE(i.rating, 0) AS rating,
            IF(i.review IS NOT NULL, 1, 0) AS has_review
        FROM books b
        LEFT JOIN user_book_interactions i 
            ON b.book_id = i.book_id AND i.user_id = %s
    """, (user_id,))
    
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

if __name__ == "__main__":
    create_tables()
    print("Base de données FolioDB initialisée.")
    print(get_stats())
