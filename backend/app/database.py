
import os

# pyrefly: ignore[missing-import]
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

#establishes a MySQL connection using the credentials in .env.
def get_connection():
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        database=os.getenv("DB_NAME", "genetic_compiler"),
    )

#inserts the incoming source code into the database before execution.
def save_job(p_id, language, source_code):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        query = """
            INSERT INTO compilation_jobs
                (p_id, language, source_code, status)
            VALUES (%s, %s, %s, %s)
        """

        cursor.execute(
            query,
            (p_id, language, source_code, "running"),
        )

        connection.commit()

    finally:
        connection.close()

#stores the output, error, exit code, runtime and final status after execution.
def update_job(
    p_id,
    stdout,
    stderr,
    exit_code,
    execution_time_ms,
    status,
):
    connection = get_connection()

    try:
        cursor = connection.cursor()

        query = """
            UPDATE compilation_jobs
            SET original_stdout = %s,
                original_stderr = %s,
                exit_code = %s,
                execution_time_ms = %s,
                status = %s
            WHERE p_id = %s
        """

        cursor.execute(
            query,
            (
                stdout,
                stderr,
                exit_code,
                execution_time_ms,
                status,
                p_id,
            ),
        )

        connection.commit()

    finally:
        connection.close()
