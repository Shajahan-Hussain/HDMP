import hashlib
import json
import re
import xml.etree.ElementTree as ET

from snowflake.snowpark import Session


# ============================================================
# CONFIGURATION
# ============================================================

RAW_TABLES = []
REGISTRY_TABLE = None
MAPPING_TABLE = None
ERROR_LOG_TABLE = None
CORTEX_MODEL = None
MAX_REPAIR_ATTEMPTS = 1


# ============================================================
# STREAMLIT PROGRESS CALLBACK
# ============================================================

PROGRESS_CALLBACK = None

def configure(config):
    """Configure the engine from the application's external config."""
    global RAW_TABLES, REGISTRY_TABLE, MAPPING_TABLE
    global ERROR_LOG_TABLE, CORTEX_MODEL, MAX_REPAIR_ATTEMPTS

    sources = config.get("sources", {})
    RAW_TABLES = []
    for source_type in ("FHIR", "JSON", "XML"):
        if source_type in sources:
            raw_table = sources[source_type].get("raw_table")
            if raw_table:
                RAW_TABLES.append((source_type, raw_table))

    controls = config.get("control_tables", {})
    REGISTRY_TABLE = controls.get(
        "flatten_query_registry",
        controls.get("registry_table")
    )
    MAPPING_TABLE = controls.get(
        "source_target_mapping",
        controls.get("mapping_table")
    )
    ERROR_LOG_TABLE = controls.get(
        "flatten_error_log",
        controls.get("error_log_table")
    )

    ai = config.get("ai", config.get("cortex", {}))
    CORTEX_MODEL = ai.get("model", ai.get("cortex_model"))
    MAX_REPAIR_ATTEMPTS = int(
        ai.get("max_repair_attempts", 1)
    )

    required = {
        "REGISTRY_TABLE": REGISTRY_TABLE,
        "MAPPING_TABLE": MAPPING_TABLE,
        "ERROR_LOG_TABLE": ERROR_LOG_TABLE,
        "CORTEX_MODEL": CORTEX_MODEL
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise ValueError(
            "Missing flattening configuration: " + ", ".join(missing)
        )


def set_progress_callback(callback):
    """Register a callback receiving pipeline progress events."""
    global PROGRESS_CALLBACK
    PROGRESS_CALLBACK = callback


def emit_progress(message, event_type="INFO", source_type=None,
                  structure_hash=None, target_table=None, status=None,
                  details=None):
    event = {
        "message": message,
        "event_type": event_type,
        "source_type": source_type,
        "structure_hash": structure_hash,
        "target_table": target_table,
        "status": status,
        "details": details or {}
    }
    if PROGRESS_CALLBACK:
        PROGRESS_CALLBACK(event)
    else:
        print(message)


# ============================================================
# BASIC HELPERS
# ============================================================

def sql_escape(value):
    """Escape a value before putting it inside a SQL string."""

    if value is None:
        return ""

    return str(value).replace("'", "''")


def clean_generated_sql(sql_text):
    """Remove markdown fences if Cortex returns them."""

    if sql_text is None:
        return ""

    sql_text = str(sql_text).strip()

    sql_text = re.sub(
        r"^```(?:sql)?\s*",
        "",
        sql_text,
        flags=re.IGNORECASE
    )

    sql_text = re.sub(
        r"\s*```$",
        "",
        sql_text
    )

    return sql_text.strip()


def parse_target_tables(value):
    """
    Convert a Snowflake ARRAY value into a Python list.

    Snowpark normally returns an ARRAY as a Python list,
    but this also handles string representations safely.
    """

    if value is None:
        return []

    if isinstance(value, (list, tuple)):
        return [str(x) for x in value if x is not None]

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return []

        # Sometimes an ARRAY can arrive as JSON text.
        try:
            parsed = json.loads(value)

            if isinstance(parsed, list):
                return [
                    str(x)
                    for x in parsed
                    if x is not None
                ]

        except Exception:
            pass

        # Fallback for a single target table.
        return [value]

    return [str(value)]


# ============================================================
# ERROR LOGGING
# ============================================================

def log_error(
    session,
    source_type,
    target_table,
    structure_hash,
    stage,
    message,
    raw_sql=""
):
    """Write an error into FLATTEN_ERROR_LOG."""

    try:

        safe_message = sql_escape(message)[:4000]
        safe_sql = sql_escape(raw_sql)[:8000]

        session.sql(f"""
            INSERT INTO {ERROR_LOG_TABLE}
            (
                SOURCE_TYPE,
                TARGET_TABLE,
                STRUCTURE_HASH,
                STAGE,
                ERROR_MESSAGE,
                RAW_SQL
            )
            VALUES
            (
                '{sql_escape(source_type)}',
                '{sql_escape(target_table)}',
                '{sql_escape(structure_hash)}',
                '{sql_escape(stage)}',
                '{safe_message}',
                '{safe_sql}'
            )
        """).collect()

    except Exception as log_exception:

        print(
            f"[WARNING] Unable to write error log: "
            f"{log_exception}"
        )


# ============================================================
# STRUCTURE HASHING
# ============================================================

def json_shape(value):
    """
    Create a representation of JSON structure.

    Actual values are ignored.

    Example:

        {
            "id": "123",
            "name": {
                "family": "Smith"
            }
        }

    becomes a structure representation based on keys/types.
    """

    if isinstance(value, dict):

        return {
            key: json_shape(value[key])
            for key in sorted(value.keys())
        }

    if isinstance(value, list):

        if len(value) == 0:
            return ["empty_list"]

        element_shapes = []

        # Inspect multiple elements so that different array
        # structures can be detected.
        for item in value[:20]:

            item_shape = json_shape(item)

            serialized = json.dumps(
                item_shape,
                sort_keys=True
            )

            if serialized not in element_shapes:
                element_shapes.append(serialized)

        return [
            json.loads(shape)
            for shape in sorted(element_shapes)
        ]

    return type(value).__name__


def xml_shape(element):
    """Create a representation of XML structure."""

    children = []

    for child in element:
        children.append(
            xml_shape(child)
        )

    return {
        "tag": element.tag,
        "attrs": sorted(element.attrib.keys()),
        "children": children
    }


def structure_hash(source_type, content):
    """
    Generate SHA256 hash based on document structure.
    """

    if source_type in ("FHIR", "JSON"):

        if isinstance(content, str):
            data = json.loads(content)
        else:
            data = content

        shape = json_shape(data)

    elif source_type == "XML":

        root = ET.fromstring(content)

        shape = xml_shape(root)

    else:

        raise ValueError(
            f"Unsupported source type: {source_type}"
        )

    shape_text = json.dumps(
        shape,
        sort_keys=True
    )

    return hashlib.sha256(
        shape_text.encode("utf-8")
    ).hexdigest()


# ============================================================
# RESOURCE TYPE
# ============================================================

def get_fhir_resource_type(content):
    """
    Get resourceType from a FHIR document.

    Example:

        {
            "resourceType": "Patient"
        }

    returns:

        Patient
    """

    if content is None:
        return None

    if isinstance(content, str):
        content = json.loads(content)

    if isinstance(content, dict):
        return content.get("resourceType")

    return None


# ============================================================
# ASSIGN TARGET TABLES
# ============================================================

def assign_target_tables(session, source_type, raw_table):
    """
    Populate TARGET_TABLE using set-based Snowflake SQL.

    No per-record Python loop is used here.

    FHIR:
        - Matches FILE_NAME + RESOURCE_TYPE.
        - Collects all matched target tables into one ARRAY.

    JSON/XML:
        - Matches FILE_NAME.
        - Uses the first target from the best matching mapping row.
    """

    print()
    print("[MAPPING] Assigning target tables using bulk SQL...")
    print(f"[MAPPING] Source type : {source_type}")
    print(f"[MAPPING] Raw table   : {raw_table}")

    before_count = session.sql(f"""
        SELECT COUNT(*) AS CNT
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND TARGET_TABLE IS NULL
    """).collect()[0]["CNT"]

    print(f"[MAPPING] Records requiring target mapping: {before_count}")

    if before_count == 0:
        print("[MAPPING] Nothing to update.")
        return

    if source_type == "FHIR":
        # TARGET_TABLE in SOURCE_TARGET_MAPPING can itself be an ARRAY.
        # FLATTEN expands it, ARRAY_AGG recreates one distinct target array
        # per raw RECORD_ID, and MERGE updates all matching raw rows in one DML.
        mapping_sql = f"""
            MERGE INTO {raw_table} L
            USING (
                SELECT
                    RRAW.RECORD_ID,
                    ARRAY_AGG(DISTINCT F.VALUE) AS TARGET_TABLES
                FROM {raw_table} RRAW
                JOIN {MAPPING_TABLE} M
                  ON M.SOURCE_TYPE = 'FHIR'
                 AND RRAW.FILE_NAME LIKE M.FILE_PATH_PATTERN
                 AND (
                        M.RESOURCE_TYPE IS NULL
                        OR M.RESOURCE_TYPE = ''
                        OR UPPER(M.RESOURCE_TYPE) =
                           UPPER(RRAW.CONTENT:resourceType::STRING)
                     )
                , LATERAL FLATTEN(INPUT => M.TARGET_TABLE) F
                WHERE RRAW.PROCESSED_FLAG = FALSE
                  AND RRAW.TARGET_TABLE IS NULL
                GROUP BY RRAW.RECORD_ID
            ) R
            ON L.RECORD_ID = R.RECORD_ID
            WHEN MATCHED THEN UPDATE SET
                L.TARGET_TABLE = R.TARGET_TABLES
        """

    else:
        # JSON/XML raw TARGET_TABLE is a single value.  Flatten mapping arrays,
        # rank matches per RECORD_ID, then update all raw records in one MERGE.
        # If more than one mapping pattern matches a file, the longest pattern
        # wins; ties are resolved by target name for deterministic behaviour.
        mapping_sql = f"""
            MERGE INTO {raw_table} L
            USING (
                SELECT RECORD_ID, TARGET_TABLE
                FROM (
                    SELECT
                        RRAW.RECORD_ID,
                        F.VALUE::STRING AS TARGET_TABLE,
                        ROW_NUMBER() OVER (
                            PARTITION BY RRAW.RECORD_ID
                            ORDER BY LENGTH(M.FILE_PATH_PATTERN) DESC,
                                     F.INDEX,
                                     F.VALUE::STRING
                        ) AS RN
                    FROM {raw_table} RRAW
                    JOIN {MAPPING_TABLE} M
                      ON M.SOURCE_TYPE = '{sql_escape(source_type)}'
                     AND RRAW.FILE_NAME LIKE M.FILE_PATH_PATTERN
                    , LATERAL FLATTEN(INPUT => M.TARGET_TABLE) F
                    WHERE RRAW.PROCESSED_FLAG = FALSE
                      AND RRAW.TARGET_TABLE IS NULL
                )
                WHERE RN = 1
            ) R
            ON L.RECORD_ID = R.RECORD_ID
            WHEN MATCHED THEN UPDATE SET
                L.TARGET_TABLE = R.TARGET_TABLE
        """

    session.sql(mapping_sql).collect()

    remaining_count = session.sql(f"""
        SELECT COUNT(*) AS CNT
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND TARGET_TABLE IS NULL
    """).collect()[0]["CNT"]

    mapped_count = before_count - remaining_count

    print(f"[MAPPING] Bulk mapping completed.")
    print(f"[MAPPING] Records mapped   : {mapped_count}")
    print(f"[MAPPING] Records unmapped : {remaining_count}")

    if remaining_count > 0:
        print(
            "[MAPPING WARNING] Some records did not match "
            "SOURCE_TARGET_MAPPING. They will not be processed."
        )


# ============================================================
# CALCULATE STRUCTURE HASH
# ============================================================

def calculate_structure_hashes(
    session,
    source_type,
    raw_table,
    fetch_batch_size=5000
):
    """
    Calculate structure hashes in Python, but write them back to Snowflake
    in bulk instead of issuing one UPDATE for every record.

    Why Python is still used:
        structure_hash() intentionally normalizes JSON/XML structure and
        ignores actual values. Keeping that logic here preserves the existing
        structure-detection behaviour.

    Why this is faster:
        A batch of hashes is loaded into a temporary table and one MERGE
        updates the raw table for the whole batch.
    """

    print()
    print("[HASH] Calculating structure hashes...")
    print(f"[HASH] Bulk update batch size: {fetch_batch_size}")

    pending_count = session.sql(f"""
        SELECT COUNT(*) AS CNT
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND STRUCTURE_HASH IS NULL
    """).collect()[0]["CNT"]

    print(f"[HASH] Records requiring hashing: {pending_count}")

    if pending_count == 0:
        print("[HASH] Nothing to hash.")
        return

    temp_table = "TMP_STRUCTURE_HASH_UPDATES"

    session.sql(f"""
        CREATE OR REPLACE TEMPORARY TABLE {temp_table} (
            RECORD_ID STRING,
            STRUCTURE_HASH STRING
        )
    """).collect()

    processed = 0
    failed = 0

    try:
        # Keyset pagination avoids OFFSET getting slower on large tables.
        last_record_id = None

        while True:
            record_filter = ""

            if last_record_id is not None:
                record_filter = (
                    "AND RECORD_ID > "
                    f"'{sql_escape(last_record_id)}'"
                )

            rows = session.sql(f"""
                SELECT
                    RECORD_ID,
                    FILE_ID,
                    FILE_NAME,
                    CONTENT
                FROM {raw_table}
                WHERE PROCESSED_FLAG = FALSE
                  AND STRUCTURE_HASH IS NULL
                  {record_filter}
                ORDER BY RECORD_ID
                LIMIT {int(fetch_batch_size)}
            """).collect()

            if not rows:
                break

            hash_rows = []

            for row in rows:
                record_id = row["RECORD_ID"]
                file_id = row["FILE_ID"]
                file_name = row["FILE_NAME"]
                content = row["CONTENT"]

                try:
                    hash_value = structure_hash(
                        source_type,
                        content
                    )

                    hash_rows.append((record_id, hash_value))

                except Exception as e:
                    failed += 1

                    print(
                        f"[HASH ERROR] RECORD_ID={record_id}, "
                        f"FILE_ID={file_id}, FILE_NAME={file_name}: {e}"
                    )

                    log_error(
                        session,
                        source_type,
                        "N/A",
                        "N/A",
                        "fingerprint",
                        f"record_id={record_id}: {e}"
                    )

            if hash_rows:
                # One INSERT into the temporary table for the complete batch.
                values_sql = ",\n".join(
                    "(" +
                    f"'{sql_escape(record_id)}', " +
                    f"'{sql_escape(hash_value)}'" +
                    ")"
                    for record_id, hash_value in hash_rows
                )

                session.sql(f"""
                    INSERT INTO {temp_table}
                        (RECORD_ID, STRUCTURE_HASH)
                    VALUES
                        {values_sql}
                """).collect()

                # One set-based update for the whole batch.
                session.sql(f"""
                    MERGE INTO {raw_table} L
                    USING {temp_table} R
                       ON L.RECORD_ID = R.RECORD_ID
                    WHEN MATCHED THEN UPDATE SET
                        L.STRUCTURE_HASH = R.STRUCTURE_HASH
                """).collect()

                processed += len(hash_rows)

                # Reuse the temp table for the next batch.
                session.sql(
                    f"TRUNCATE TABLE {temp_table}"
                ).collect()

            last_record_id = rows[-1]["RECORD_ID"]

            print(
                f"[HASH] Progress: {processed + failed}/{pending_count} "
                f"| hashed={processed} | failed={failed}"
            )

        print("[HASH] Bulk hashing completed.")
        print(f"[HASH] Successfully hashed: {processed}")
        print(f"[HASH] Failed             : {failed}")

    finally:
        try:
            session.sql(
                f"DROP TABLE IF EXISTS {temp_table}"
            ).collect()
        except Exception:
            pass


# ============================================================
# GET PENDING STRUCTURE HASHES
# ============================================================

def get_pending_hashes(session, raw_table):
    """
    Return unique structure hashes that still need processing.
    """

    rows = session.sql(f"""
        SELECT DISTINCT
            STRUCTURE_HASH
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND STRUCTURE_HASH IS NOT NULL
          AND TARGET_TABLE IS NOT NULL
        ORDER BY STRUCTURE_HASH
    """).collect()

    return [
        row["STRUCTURE_HASH"]
        for row in rows
    ]


# ============================================================
# GET TARGET TABLES FOR STRUCTURE
# ============================================================

def get_target_tables_for_structure(
    session,
    source_type,
    raw_table,
    structure_hash
):
    """
    Return all target tables required for a structure.

    For FHIR, this returns the UNION of all target tables
    contained in TARGET_TABLE arrays.
    """

    rows = session.sql(f"""
        SELECT TARGET_TABLE
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND STRUCTURE_HASH =
              '{sql_escape(structure_hash)}'
          AND TARGET_TABLE IS NOT NULL
    """).collect()

    target_tables = []

    for row in rows:

        values = parse_target_tables(
            row["TARGET_TABLE"]
        )

        for target in values:

            if target not in target_tables:
                target_tables.append(target)

    return target_tables


# ============================================================
# GET TARGET COLUMNS
# ============================================================

def get_target_columns(session, target_table):
    """
    Read the actual columns from the target table.
    """

    rows = session.sql(
        f"DESCRIBE TABLE {target_table}"
    ).collect()

    columns = []

    for row in rows:

        try:
            column_name = row["name"]
        except Exception:
            column_name = row["NAME"]

        columns.append(column_name)

    return columns


# ============================================================
# GET SAMPLE RECORD
# ============================================================

def get_sample_record(
    session,
    source_type,
    raw_table,
    target_table,
    structure_hash
):
    """
    Get one source record that belongs to this structure
    and target table.

    This sample is sent to Cortex.
    """

    if source_type == "FHIR":

        condition = f"""
            ARRAY_CONTAINS(
                '{sql_escape(target_table)}'::VARIANT,
                TARGET_TABLE
            )
        """

    else:

        condition = f"""
            TARGET_TABLE =
                '{sql_escape(target_table)}'
        """

    rows = session.sql(f"""
        SELECT
            RECORD_ID,
            CONTENT
        FROM {raw_table}
        WHERE PROCESSED_FLAG = FALSE
          AND STRUCTURE_HASH =
              '{sql_escape(structure_hash)}'
          AND {condition}
        ORDER BY RECORD_ID
        LIMIT 1
    """).collect()

    if not rows:
        raise ValueError(
            f"No sample record found for "
            f"target={target_table}, "
            f"hash={structure_hash}"
        )

    return (
        rows[0]["RECORD_ID"],
        rows[0]["CONTENT"]
    )


# ============================================================
# QUERY REGISTRY
# ============================================================

def get_cached_flatten_sql(
    session,
    source_type,
    target_table,
    structure_hash
):
    """
    Look for an existing flatten query.
    """

    rows = session.sql(f"""
        SELECT FLATTEN_SELECT
        FROM {REGISTRY_TABLE}
        WHERE SOURCE_TYPE =
            '{sql_escape(source_type)}'
          AND TARGET_TABLE =
            '{sql_escape(target_table)}'
          AND STRUCTURE_HASH =
            '{sql_escape(structure_hash)}'
        ORDER BY CREATED_TS DESC
        LIMIT 1
    """).collect()

    if rows:
        return rows[0]["FLATTEN_SELECT"]

    return None


def save_to_registry(
    session,
    source_type,
    target_table,
    structure_hash,
    sql_text,
    sample_record_id
):
    """
    Save a newly generated query.
    """

    escaped_sql = sql_escape(sql_text)

    session.sql(f"""
        INSERT INTO {REGISTRY_TABLE}
        (
            SOURCE_TYPE,
            TARGET_TABLE,
            STRUCTURE_HASH,
            FLATTEN_SELECT,
            SAMPLE_RECORD_ID
        )
        VALUES
        (
            '{sql_escape(source_type)}',
            '{sql_escape(target_table)}',
            '{sql_escape(structure_hash)}',
            '{escaped_sql}',
            '{sql_escape(sample_record_id)}'
        )
    """).collect()


def update_registry_sql(
    session,
    source_type,
    target_table,
    structure_hash,
    sql_text
):
    """
    Replace the cached SQL after a successful Cortex repair.
    """

    escaped_sql = sql_escape(sql_text)

    session.sql(f"""
        UPDATE {REGISTRY_TABLE}
        SET FLATTEN_SELECT =
            '{escaped_sql}'
        WHERE SOURCE_TYPE =
            '{sql_escape(source_type)}'
          AND TARGET_TABLE =
            '{sql_escape(target_table)}'
          AND STRUCTURE_HASH =
            '{sql_escape(structure_hash)}'
    """).collect()


# ============================================================
# CORTEX SQL GENERATION
# ============================================================

def ask_cortex_for_flatten_sql(
    session,
    source_type,
    target_table,
    sample_content
):
    """
    Ask Cortex to generate one INSERT...SELECT statement.
    """

    columns = get_target_columns(
        session,
        target_table
    )

    if source_type in ("FHIR", "JSON"):

        content_instruction = """
SOURCE CONTENT is a Snowflake VARIANT.

The original JSON/FHIR document is available as:

    SRC.CONTENT

For scalar fields use VARIANT paths.

Examples:

    SRC.CONTENT:gender::STRING
    SRC.CONTENT:birthDate::DATE
    SRC.CONTENT:id::STRING

For nested objects:

    SRC.CONTENT:managingOrganization.reference::STRING

For arrays:

    SRC.CONTENT:name[0]:family::STRING

Use LATERAL FLATTEN when the target table requires
multiple rows from a repeating FHIR/JSON array.
"""

    else:

        content_instruction = """
SOURCE CONTENT contains XML text.

Use:

    PARSE_XML(SRC.CONTENT)

Inspect the supplied XML structure before generating
the SQL.
"""

    if source_type == "FHIR":

        fhir_rules = """
FHIR-SPECIFIC RULES
===================

1. This is a FHIR resource.

2. One FHIR resource can populate multiple target tables.

3. This SQL is being generated for ONE target table only.

4. Generate SQL only for the supplied target table.

5. Repeating FHIR elements may require LATERAL FLATTEN.

Examples of repeating FHIR elements include:

    name
    identifier
    telecom
    address
    contact
    communication

6. When the target table represents a repeating array,
   use LATERAL FLATTEN on the relevant array.

7. Do NOT flatten unrelated arrays in the same query.

8. Avoid Cartesian products between independent arrays.

9. The parent FHIR record identifier should be preserved
   when the target table has an appropriate parent identifier
   column.

10. Inspect the actual sample FHIR document. Do not guess
    the JSON structure.
"""

    else:

        fhir_rules = ""

    prompt = f"""
You are an expert Snowflake SQL engineer.

Generate exactly ONE executable Snowflake
INSERT INTO ... SELECT statement.

SOURCE TYPE:
{source_type}

TARGET TABLE:
{target_table}

{content_instruction}

{fhir_rules}

============================================================
SOURCE
============================================================

The source must use this exact alias:

SRC

SRC contains these columns:

    RECORD_ID
    FILE_ID
    FILE_NAME
    CONTENT

The source table itself must NOT be referenced.

============================================================
TARGET
============================================================

The target table is:

{target_table}

The ONLY valid target columns are:

{", ".join(columns)}

============================================================
MANDATORY RULES
============================================================

1. Generate exactly ONE INSERT...SELECT statement.

2. The statement must start with:

   INSERT INTO {target_table}

3. The source must contain:

   FROM SRC

4. SRC is a placeholder.

5. Do not create a CTE named SRC.

6. Do not reference the physical raw table.

7. Do not invent target columns.

8. Use only the supplied target columns.

9. The number of INSERT columns must exactly match
   the number of SELECT expressions.

10. Inspect the actual sample document before generating
    the mapping.

11. Do not assume target column names are JSON properties.

12. Navigate the actual JSON/FHIR structure.

13. Use safe conversions where appropriate:

       TRY_TO_DATE
       TRY_TO_TIMESTAMP
       TRY_TO_NUMBER

14. Use array indexing when a target column needs one value.

15. Use LATERAL FLATTEN when the target table requires
    multiple rows from a repeating array.

16. Do not independently flatten unrelated arrays because
    that can create a Cartesian product.

17. Include RECORD_ID, FILE_ID and FILE_NAME if those
    columns exist in the target table.

18. Do not use:

       ARRAY_CONSTRUCT(SRC.CONTENT)

    The complete document must not be inserted as one array.

19. Do not use:

       DROP
       DELETE
       TRUNCATE
       ALTER
       MERGE
       CREATE
       GRANT
       REVOKE

20. Return ONLY SQL.

21. Do not return markdown.

22. Do not return ```sql.

23. Do not return an explanation.

============================================================
SAMPLE SOURCE DOCUMENT
============================================================

{str(sample_content)[:12000]}
"""

    escaped_prompt = sql_escape(prompt)

    result = session.sql(f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            '{CORTEX_MODEL}',
            '{escaped_prompt}'
        ) AS SQL_TEXT
    """).collect()

    return clean_generated_sql(
        result[0]["SQL_TEXT"]
    )


# ============================================================
# SQL VALIDATION
# ============================================================

def is_safe_flatten_sql(
    sql_text,
    raw_table,
    target_table
):
    """
    Basic validation before executing Cortex SQL.
    """

    if not sql_text:
        return False, "Cortex returned empty SQL"

    normalized = re.sub(
        r"\s+",
        " ",
        sql_text.strip()
    )

    upper = normalized.upper()

    expected_start = (
        f"INSERT INTO {target_table}"
    ).upper()

    if not upper.startswith(expected_start):

        return (
            False,
            f"SQL does not start with "
            f"INSERT INTO {target_table}"
        )

    if not re.search(
        r"\bFROM\s+SRC\b",
        upper
    ):

        return (
            False,
            "Generated SQL does not contain FROM SRC"
        )

    if raw_table.upper() in upper:

        return (
            False,
            "Generated SQL references the raw table"
        )

    if "ARRAY_CONSTRUCT(SRC.CONTENT)" in upper:

        return (
            False,
            "Generated SQL incorrectly wraps "
            "the entire document in ARRAY_CONSTRUCT"
        )

    forbidden = [
        "DROP ",
        "DELETE ",
        "TRUNCATE ",
        "ALTER ",
        "MERGE ",
        "GRANT ",
        "REVOKE ",
        "CREATE "
    ]

    for word in forbidden:

        if word in upper:

            return (
                False,
                f"Generated SQL contains forbidden "
                f"keyword: {word.strip()}"
            )

    # Cortex should return one statement.
    # A trailing semicolon is allowed.
    sql_without_trailing_semicolon = (
        sql_text.strip().rstrip(";").strip()
    )

    if ";" in sql_without_trailing_semicolon:

        return (
            False,
            "Generated SQL contains multiple SQL statements"
        )

    return True, ""


# ============================================================
# CREATE SOURCE TEMP TABLE
# ============================================================

def create_source_temp_table(
    session,
    source_type,
    raw_table,
    target_table,
    structure_hash
):
    """
    Create a temporary source table containing only records
    that should be loaded into the current target table.

    This is NOT batch processing.

    It simply gives the generated Cortex SQL a clean SRC source.
    """

    temp_table = "TMP_FLATTEN_SOURCE"

    if source_type == "FHIR":

        target_condition = f"""
            ARRAY_CONTAINS(
                '{sql_escape(target_table)}'::VARIANT,
                TARGET_TABLE
            )
        """

    else:

        target_condition = f"""
            TARGET_TABLE =
                '{sql_escape(target_table)}'
        """

    session.sql(f"""
        CREATE OR REPLACE TEMPORARY TABLE
        {temp_table} AS

        SELECT
            RECORD_ID,
            FILE_ID,
            FILE_NAME,
            CONTENT

        FROM {raw_table}

        WHERE PROCESSED_FLAG = FALSE

          AND STRUCTURE_HASH =
              '{sql_escape(structure_hash)}'

          AND {target_condition}
    """).collect()

    count = session.sql(f"""
        SELECT COUNT(*) AS RECORD_COUNT
        FROM {temp_table}
    """).collect()[0]["RECORD_COUNT"]

    return temp_table, count


# ============================================================
# PREPARE SQL FOR EXECUTION
# ============================================================

def prepare_executable_sql(
    sql_text,
    temp_table
):
    """
    Replace FROM SRC with the temporary source table.
    """

    pattern = r"\bFROM\s+SRC\b"

    replacement = (
        f"FROM {temp_table} SRC"
    )

    executable_sql, count = re.subn(
        pattern,
        replacement,
        sql_text,
        count=1,
        flags=re.IGNORECASE
    )

    if count != 1:

        raise ValueError(
            "Unable to replace FROM SRC "
            "in generated SQL"
        )

    return executable_sql


# ============================================================
# CORTEX SQL REPAIR
# ============================================================

def repair_flatten_sql(
    session,
    source_type,
    target_table,
    sample_content,
    failed_sql,
    error_message
):
    """
    Ask Cortex to repair SQL after an execution failure.
    """

    columns = get_target_columns(
        session,
        target_table
    )

    prompt = f"""
You are an expert Snowflake SQL engineer.

The following SQL was generated for a
{source_type} document but failed during execution.

Fix the SQL.

Return ONLY the corrected SQL.
Do not return markdown.
Do not return an explanation.

============================================================
TARGET TABLE
============================================================

{target_table}

============================================================
VALID TARGET COLUMNS
============================================================

{", ".join(columns)}

============================================================
SOURCE
============================================================

The source alias must be:

SRC

SRC contains:

    RECORD_ID
    FILE_ID
    FILE_NAME
    CONTENT

Do not reference the physical raw table.

============================================================
RULES
============================================================

1. SQL must start with:

   INSERT INTO {target_table}

2. SQL must contain:

   FROM SRC

3. Use only valid target columns.

4. Inspect the actual sample document.

5. Do not invent JSON paths.

6. For FHIR/JSON arrays, use LATERAL FLATTEN only
   when multiple rows are actually required.

7. Avoid Cartesian products between independent arrays.

8. Do not use:

   ARRAY_CONSTRUCT(SRC.CONTENT)

9. INSERT and SELECT column counts must match.

10. Return exactly one INSERT...SELECT statement.

============================================================
FAILED SQL
============================================================

{failed_sql}

============================================================
SNOWFLAKE ERROR
============================================================

{error_message}

============================================================
SAMPLE SOURCE
============================================================

{str(sample_content)[:12000]}
"""

    escaped_prompt = sql_escape(prompt)

    result = session.sql(f"""
        SELECT SNOWFLAKE.CORTEX.COMPLETE(
            '{CORTEX_MODEL}',
            '{escaped_prompt}'
        ) AS SQL_TEXT
    """).collect()

    return clean_generated_sql(
        result[0]["SQL_TEXT"]
    )


# ============================================================
# EXECUTE ONE TARGET QUERY
# ============================================================

def execute_target_query(
    session,
    source_type,
    raw_table,
    target_table,
    structure_hash,
    sql_text
):
    """
    Execute one target-table flatten query.

    Returns the number of source records selected.
    """

    temp_table = None

    try:

        # ----------------------------------------------------
        # Create source for this target table
        # ----------------------------------------------------

        temp_table, record_count = (
            create_source_temp_table(
                session,
                source_type,
                raw_table,
                target_table,
                structure_hash
            )
        )

        if record_count == 0:

            print(
                f"[EXECUTE] No records for "
                f"{target_table}"
            )

            return 0

        print(
            f"[EXECUTE] Target       : {target_table}"
        )

        print(
            f"[EXECUTE] Source rows  : {record_count}"
        )

        current_sql = sql_text
        repair_attempt = 0

        while True:

            executable_sql = prepare_executable_sql(
                current_sql,
                temp_table
            )

            try:

                print(
                    f"[EXECUTE] Running flatten query..."
                )

                emit_progress(
                    f"Executing flatten query: {target_table}",
                    "EXECUTION", source_type, structure_hash,
                    target_table, "RUNNING",
                    {"record_count": record_count}
                )

                session.sql(
                    executable_sql
                ).collect()

                print(
                    f"[EXECUTE] SUCCESS: "
                    f"{target_table}"
                )

                emit_progress(
                    f"Execution successful: {target_table}",
                    "EXECUTION_SUCCESS", source_type, structure_hash,
                    target_table, "SUCCESS",
                    {"record_count": record_count}
                )

                return record_count

            except Exception as e:

                error_message = str(e)

                print(
                    f"[EXECUTE ERROR] {error_message}"
                )

                if repair_attempt >= MAX_REPAIR_ATTEMPTS:
                    emit_progress(
                        f"Execution failed: {target_table}: {error_message}",
                        "EXECUTION_ERROR", source_type, structure_hash,
                        target_table, "FAILED"
                    )

                    log_error(
                        session,
                        source_type,
                        target_table,
                        structure_hash,
                        "flatten_execute",
                        error_message,
                        executable_sql
                    )

                    raise

                repair_attempt += 1

                print(
                    f"[CORTEX REPAIR] "
                    f"Attempt {repair_attempt}/"
                    f"{MAX_REPAIR_ATTEMPTS}"
                )

                emit_progress(
                    f"Cortex repair attempt {repair_attempt}/{MAX_REPAIR_ATTEMPTS}: {target_table}",
                    "CORTEX_REPAIR", source_type, structure_hash,
                    target_table, "RUNNING"
                )

                try:

                    sample_record_id, sample_content = (
                        get_sample_record(
                            session,
                            source_type,
                            raw_table,
                            target_table,
                            structure_hash
                        )
                    )

                    repaired_sql = repair_flatten_sql(
                        session,
                        source_type,
                        target_table,
                        sample_content,
                        current_sql,
                        error_message
                    )

                    ok, reason = is_safe_flatten_sql(
                        repaired_sql,
                        raw_table,
                        target_table
                    )

                    if not ok:

                        raise ValueError(
                            f"Repaired SQL failed validation: "
                            f"{reason}"
                        )

                    update_registry_sql(
                        session,
                        source_type,
                        target_table,
                        structure_hash,
                        repaired_sql
                    )

                    current_sql = repaired_sql

                    print(
                        "[CORTEX REPAIR] "
                        "Corrected SQL cached."
                    )

                    emit_progress(
                        f"Repaired SQL cached: {target_table}",
                        "REPAIR_SUCCESS", source_type, structure_hash,
                        target_table, "SUCCESS"
                    )

                except Exception as repair_error:

                    log_error(
                        session,
                        source_type,
                        target_table,
                        structure_hash,
                        "cortex_repair",
                        str(repair_error),
                        current_sql
                    )

                    raise

    finally:

        if temp_table:

            try:

                session.sql(
                    f"DROP TABLE IF EXISTS {temp_table}"
                ).collect()

            except Exception:
                pass


# ============================================================
# PROCESS ONE STRUCTURE
# ============================================================

def process_structure(
    session,
    source_type,
    raw_table,
    structure_hash
):
    """
    Process every target table belonging to one structure.

    For FHIR, several target tables can be returned.

    All target-table inserts are executed in one transaction.
    """

    print()
    print("=" * 80)
    print("PROCESSING STRUCTURE")
    print("=" * 80)

    print(f"Source type    : {source_type}")
    print(f"Raw table      : {raw_table}")
    print(f"Structure hash : {structure_hash}")

    emit_progress(
        f"Processing structure {structure_hash}",
        "STRUCTURE_START", source_type, structure_hash, status="RUNNING"
    )

    # --------------------------------------------------------
    # Get all target tables for this structure
    # --------------------------------------------------------

    target_tables = get_target_tables_for_structure(
        session,
        source_type,
        raw_table,
        structure_hash
    )

    if not target_tables:

        print(
            "[SKIP] No target tables found."
        )

        return 0

    print(
        f"Target tables  : {target_tables}"
    )

    emit_progress(
        f"Target tables: {', '.join(target_tables)}",
        "TARGET_TABLES", source_type, structure_hash, status="RUNNING"
    )

    total_records = 0

    try:

        # ----------------------------------------------------
        # Everything for this structure is one transaction.
        # ----------------------------------------------------

        session.sql("BEGIN").collect()

        for target_table in target_tables:

            print()
            print(
                f"[TARGET] Processing: {target_table}"
            )

            # ------------------------------------------------
            # Check registry
            # ------------------------------------------------

            cached_sql = get_cached_flatten_sql(
                session,
                source_type,
                target_table,
                structure_hash
            )

            if cached_sql:

                print(
                    "[REGISTRY] CACHE HIT"
                )

                emit_progress(
                    f"Cache HIT: {target_table}",
                    "CACHE_HIT", source_type, structure_hash,
                    target_table, "SUCCESS"
                )

                sql_text = cached_sql

            else:

                print(
                    "[REGISTRY] CACHE MISS"
                )

                emit_progress(
                    f"Cache MISS: {target_table}",
                    "CACHE_MISS", source_type, structure_hash,
                    target_table, "RUNNING"
                )

                # --------------------------------------------
                # Get sample
                # --------------------------------------------

                sample_record_id, sample_content = (
                    get_sample_record(
                        session,
                        source_type,
                        raw_table,
                        target_table,
                        structure_hash
                    )
                )

                print(
                    "[CORTEX] Generating flatten query..."
                )

                emit_progress(
                    f"Cortex generating SQL: {target_table}",
                    "CORTEX_CALL", source_type, structure_hash,
                    target_table, "RUNNING"
                )

                sql_text = ask_cortex_for_flatten_sql(
                    session,
                    source_type,
                    target_table,
                    sample_content
                )

                # --------------------------------------------
                # Validate Cortex SQL
                # --------------------------------------------

                emit_progress(
                    f"Validating generated SQL: {target_table}",
                    "SQL_VALIDATION", source_type, structure_hash,
                    target_table, "RUNNING"
                )

                ok, reason = is_safe_flatten_sql(
                    sql_text,
                    raw_table,
                    target_table
                )

                if not ok:

                    log_error(
                        session,
                        source_type,
                        target_table,
                        structure_hash,
                        "cortex_generate_validation",
                        reason,
                        sql_text
                    )

                    raise ValueError(
                        f"Cortex SQL validation failed: "
                        f"{reason}"
                    )

                # --------------------------------------------
                # Save to registry
                # --------------------------------------------

                save_to_registry(
                    session,
                    source_type,
                    target_table,
                    structure_hash,
                    sql_text,
                    sample_record_id
                )

                emit_progress(
                    f"New query saved to registry: {target_table}",
                    "REGISTRY_SAVE", source_type, structure_hash,
                    target_table, "SUCCESS"
                )

                print(
                    "[REGISTRY] New query saved."
                )

            # ------------------------------------------------
            # Execute query
            # ------------------------------------------------

            records = execute_target_query(
                session,
                source_type,
                raw_table,
                target_table,
                structure_hash,
                sql_text
            )

            total_records += records

        # ----------------------------------------------------
        # All target tables succeeded.
        # Now mark source records processed.
        # ----------------------------------------------------

        session.sql(f"""
            UPDATE {raw_table}
            SET
                PROCESSED_FLAG = TRUE,
                PROCESSED_TS = CURRENT_TIMESTAMP()

            WHERE PROCESSED_FLAG = FALSE
              AND STRUCTURE_HASH =
                  '{sql_escape(structure_hash)}'
              AND TARGET_TABLE IS NOT NULL
        """).collect()

        session.sql("COMMIT").collect()

        print()
        print(
            "[STRUCTURE] SUCCESS"
        )

        print(
            f"[STRUCTURE] Target tables processed: "
            f"{len(target_tables)}"
        )

        emit_progress(
            f"Structure completed successfully: {structure_hash}",
            "STRUCTURE_SUCCESS", source_type, structure_hash,
            status="SUCCESS",
            details={"target_count": len(target_tables), "records": total_records}
        )

        return total_records

    except Exception as e:

        print()
        print(
            "[STRUCTURE] FAILED"
        )

        print(
            f"[STRUCTURE] Rolling back: {e}"
        )

        try:
            session.sql("ROLLBACK").collect()
        except Exception:
            pass

        log_error(
            session,
            source_type,
            "MULTIPLE_TARGETS",
            structure_hash,
            "structure_execute",
            str(e)
        )

        emit_progress(
            f"Structure failed: {structure_hash}: {e}",
            "STRUCTURE_ERROR", source_type, structure_hash,
            status="FAILED"
        )

        return 0


# ============================================================
# PROCESS ONE SOURCE TABLE
# ============================================================

def process_source_table(
    session,
    source_type,
    raw_table
):
    """
    Process one raw source table from beginning to end.
    """

    print()
    print("=" * 80)
    print(f"SOURCE TYPE : {source_type}")
    print(f"RAW TABLE   : {raw_table}")
    print("=" * 80)

    emit_progress(
        f"Starting {source_type} flattening",
        "SOURCE_START", source_type=source_type, status="RUNNING"
    )

    # --------------------------------------------------------
    # STEP 1
    # Assign target table(s)
    # --------------------------------------------------------

    assign_target_tables(
        session,
        source_type,
        raw_table
    )

    # --------------------------------------------------------
    # STEP 2
    # Calculate structure hash
    # --------------------------------------------------------

    calculate_structure_hashes(
        session,
        source_type,
        raw_table
    )

    # --------------------------------------------------------
    # STEP 3
    # Get all pending structures
    # --------------------------------------------------------

    hashes = get_pending_hashes(
        session,
        raw_table
    )

    print()
    print(
        f"[SOURCE] Pending structures: {len(hashes)}"
    )

    emit_progress(
        f"{len(hashes)} pending structure(s) found",
        "PENDING_STRUCTURES", source_type=source_type,
        status="RUNNING", details={"count": len(hashes)}
    )

    records_processed = 0

    # --------------------------------------------------------
    # STEP 4
    # Process every structure
    # --------------------------------------------------------

    for index, structure_hash in enumerate(
        hashes,
        start=1
    ):

        print()
        print(
            f"[SOURCE] Structure "
            f"{index}/{len(hashes)}"
        )

        emit_progress(
            f"Processing structure {index}/{len(hashes)}: {structure_hash}",
            "STRUCTURE_PROGRESS", source_type, structure_hash,
            status="RUNNING", details={"index": index, "total": len(hashes)}
        )

        records_processed += process_structure(
            session,
            source_type,
            raw_table,
            structure_hash
        )

    print()
    print(
        f"[SOURCE COMPLETE] {source_type}"
    )

    print(
        f"[SOURCE COMPLETE] "
        f"Structures processed: {len(hashes)}"
    )

    print(
        f"[SOURCE COMPLETE] "
        f"Source records handled: {records_processed}"
    )

    emit_progress(
        f"{source_type} completed: {records_processed} source record(s) handled",
        "SOURCE_COMPLETE", source_type=source_type, status="SUCCESS",
        details={"records_processed": records_processed, "structures": len(hashes)}
    )

    return records_processed


# ============================================================
# MAIN
# ============================================================

def main(session: Session) -> str:

    print()
    print("=" * 80)
    print("FHIR / JSON / XML FLATTEN PIPELINE")
    print("=" * 80)

    summary = []

    for source_type, raw_table in RAW_TABLES:

        try:

            processed = process_source_table(
                session,
                source_type,
                raw_table
            )

            summary.append(
                f"{source_type}: "
                f"{processed} source records handled"
            )

        except Exception as e:

            print()
            print(
                f"[SOURCE FAILED] "
                f"{source_type}: {e}"
            )

            summary.append(
                f"{source_type}: FAILED - {e}"
            )

    print()
    print("=" * 80)
    print("PIPELINE COMPLETED")
    print("=" * 80)

    for line in summary:
        print(line)

    print("=" * 80)

    return "\n".join(summary)


# ============================================================
# STANDALONE EXECUTION
# ============================================================

if __name__ == "__main__":
    import json
    from pathlib import Path
    from snowflake.snowpark.context import get_active_session

    config_candidates = [
        Path(__file__).resolve().parent.parent / "config" / "config.json",
        Path(__file__).resolve().parent.parent / "config.json"
    ]

    config_path = next(
        (path for path in config_candidates if path.exists()),
        None
    )

    if config_path is None:
        raise FileNotFoundError(
            "Configuration file not found. Expected config/config.json."
        )

    with config_path.open("r", encoding="utf-8") as config_file:
        standalone_config = json.load(config_file)

    configure(standalone_config)

    standalone_session = get_active_session()
    main(standalone_session)