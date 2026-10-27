import json
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


def save_original_tac(p_id, original_tac):
    # TAC instruction arrays are JSON; legacy string representations remain plain text.
    serialized_tac = (
        original_tac
        if isinstance(original_tac, str)
        else json.dumps(original_tac, ensure_ascii=False)
    )
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT p_id FROM compilation_jobs WHERE p_id = %s FOR UPDATE",
            (p_id,),
        )
        if cursor.fetchone() is None:
            raise ValueError("Compilation job was not found.")

        cursor.execute(
            """
            SELECT optimization_id
            FROM optimization_runs
            WHERE p_id = %s
            ORDER BY optimization_id
            LIMIT 1
            FOR UPDATE
            """,
            (p_id,),
        )
        existing_run = cursor.fetchone()

        if existing_run:
            cursor.execute(
                """
                UPDATE optimization_runs
                SET original_tac = %s
                WHERE optimization_id = %s
                """,
                (serialized_tac, existing_run[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO optimization_runs (p_id, original_tac)
                VALUES (%s, %s)
                """,
                (p_id, serialized_tac),
            )

        connection.commit()
    finally:
        connection.close()


def get_original_tac(p_id):
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            SELECT original_tac
            FROM optimization_runs
            WHERE p_id = %s
            ORDER BY optimization_id
            LIMIT 1
            """,
            (p_id,),
        )
        row = cursor.fetchone()
        if not row or row[0] is None:
            return None
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return row[0]
    finally:
        connection.close()


def get_compilation_job(p_id):
    connection = get_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p_id, language, source_code, original_stdout,
                   original_stderr, exit_code, execution_time_ms, status
            FROM compilation_jobs
            WHERE p_id = %s
            """,
            (p_id,),
        )
        return cursor.fetchone()
    finally:
        connection.close()


def save_optimization_run(p_id, result):
    # optimized_code is a JSON envelope containing emitted assembly and GA
    # metadata because the existing schema has no dedicated metadata columns.
    optimized_code = json.dumps(
        {
            "assembly": result.get("optimized_code", ""),
            "metadata": result.get("metadata", {}),
        },
        ensure_ascii=False,
    )
    original_tac = result.get("original_tac")
    optimized_tac = result.get("optimized_tac")
    if original_tac is not None and not isinstance(original_tac, str):
        original_tac = json.dumps(original_tac, ensure_ascii=False)
    if optimized_tac is not None and not isinstance(optimized_tac, str):
        optimized_tac = json.dumps(optimized_tac, ensure_ascii=False)
    connection = get_connection()

    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT p_id FROM compilation_jobs WHERE p_id = %s FOR UPDATE",
            (p_id,),
        )
        if cursor.fetchone() is None:
            raise ValueError("Compilation job was not found.")

        cursor.execute(
            """
            SELECT optimization_id
            FROM optimization_runs
            WHERE p_id = %s
            ORDER BY optimization_id DESC
            LIMIT 1
            FOR UPDATE
            """,
            (p_id,),
        )
        existing_run = cursor.fetchone()
        values = (
            original_tac,
            optimized_tac,
            optimized_code,
            result.get("optimized_stdout"),
            result.get("optimized_exit_code"),
            result.get("optimized_execution_time_ms"),
            result.get("best_fitness"),
            result.get("equivalent"),
            result.get("status", "error"),
        )

        if existing_run:
            cursor.execute(
                """
                UPDATE optimization_runs
                SET original_tac = %s,
                    optimized_tac = %s,
                    optimized_code = %s,
                    optimized_stdout = %s,
                    optimized_exit_code = %s,
                    execution_time_ms = %s,
                    fitness_score = %s,
                    equivalent = %s,
                    status = %s
                WHERE optimization_id = %s
                """,
                values + (existing_run[0],),
            )
        else:
            cursor.execute(
                """
                INSERT INTO optimization_runs
                    (p_id, original_tac, optimized_tac, optimized_code,
                     optimized_stdout, optimized_exit_code, execution_time_ms,
                     fitness_score, equivalent, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (p_id,) + values,
            )
        connection.commit()
    finally:
        connection.close()


def get_optimization_result(p_id):
    connection = get_connection()

    try:
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT j.p_id, j.language, j.source_code, j.original_stdout,
                   j.original_stderr, j.exit_code AS original_exit_code,
                   j.execution_time_ms AS original_job_execution_time_ms,
                   j.status AS job_status, o.original_tac, o.optimized_tac,
                   o.optimized_code, o.optimized_stdout,
                   o.optimized_exit_code,
                   o.execution_time_ms AS optimized_execution_time_ms,
                   o.fitness_score, o.equivalent, o.status AS optimization_status
            FROM compilation_jobs AS j
            LEFT JOIN optimization_runs AS o ON o.p_id = j.p_id
            WHERE j.p_id = %s
            ORDER BY o.optimization_id DESC
            LIMIT 1
            """,
            (p_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        for field in ("original_tac", "optimized_tac"):
            value = row.get(field)
            if value is not None:
                try:
                    row[field] = json.loads(value)
                except json.JSONDecodeError:
                    pass

        stored_code = row.pop("optimized_code", None)
        if stored_code:
            try:
                code_data = json.loads(stored_code)
            except json.JSONDecodeError:
                row["optimized_code"] = stored_code
            else:
                if isinstance(code_data, dict) and "assembly" in code_data:
                    row["optimized_code"] = code_data["assembly"]
                    row["optimization_metadata"] = code_data.get("metadata", {})
                else:
                    row["optimized_code"] = stored_code
        else:
            row["optimized_code"] = ""
            row["optimization_metadata"] = {}
        return row
    finally:
        connection.close()
