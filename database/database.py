import sqlite3
import os


DATABASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE_PATH = os.path.join(DATABASE_DIR, "docurag.db")


def get_db_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():

    os.makedirs(DATABASE_DIR, exist_ok=True)

    connection = get_db_connection()
    cursor = connection.cursor()

    # Users
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'user',
            is_active BOOLEAN NOT NULL DEFAULT 1,
            last_login DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Documents
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename VARCHAR(255) NOT NULL,
            original_filename VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            file_size INTEGER NOT NULL,
            file_path VARCHAR(500) NOT NULL,
            upload_date DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            uploader_id INTEGER NOT NULL,
            processing_status VARCHAR(30) NOT NULL DEFAULT 'uploaded',
            page_count INTEGER,
            error_message VARCHAR(1000),
            content_hash VARCHAR(64) NOT NULL,
            processed_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (uploader_id)
                REFERENCES users(id)
        )
    """)

    # Document Chunks
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            position INTEGER NOT NULL,
            embedding BLOB,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (document_id)
                REFERENCES documents(id)
                ON DELETE CASCADE
        )
    """)

    # Image Analysis
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            page_number INTEGER NOT NULL,
            image_index INTEGER NOT NULL,
            image_path VARCHAR(500),
            image_type VARCHAR(100),
            objects TEXT,
            extracted_text TEXT,
            orientation VARCHAR(100),
            colors TEXT,
            anomalies TEXT,
            description TEXT,
            raw_analysis TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (document_id)
                REFERENCES documents(id)
                ON DELETE CASCADE
        )
    """)

    # Queries
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            conversation_id VARCHAR(100) NOT NULL,
            question TEXT NOT NULL,
            answer TEXT,
            confidence FLOAT,
            response_time FLOAT,
            cache_hit BOOLEAN NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
                ON DELETE CASCADE
        )
    """)

    # Query Sources
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS query_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query_id INTEGER NOT NULL,
            document_id INTEGER NOT NULL,
            chunk_id INTEGER,
            similarity FLOAT,
            source_page INTEGER,
            retrieved_text TEXT,
            image_context TEXT,
            rank INTEGER,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

            FOREIGN KEY (query_id)
                REFERENCES queries(id)
                ON DELETE CASCADE,

            FOREIGN KEY (document_id)
                REFERENCES documents(id)
                ON DELETE CASCADE,

            FOREIGN KEY (chunk_id)
                REFERENCES document_chunks(id)
                ON DELETE SET NULL
        )
    """)

    # Indexes
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_uploader
        ON documents(uploader_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_documents_status
        ON documents(processing_status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_document
        ON document_chunks(document_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_chunks_page
        ON document_chunks(page_number)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_images_document
        ON image_analysis(document_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_queries_user
        ON queries(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_queries_conversation
        ON queries(conversation_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sources_query
        ON query_sources(query_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sources_document
        ON query_sources(document_id)
    """)

    connection.commit()
    connection.close()

    print("Database initialized successfully.")
    print(f"Database location: {DATABASE_PATH}")


if __name__ == "__main__":
    init_db()