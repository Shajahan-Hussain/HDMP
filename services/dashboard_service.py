def get_source_metrics(session, source_config):
    """
    Get record counts and processing status for one source.
    """

    raw_table = source_config["raw_table"]

    query = f"""
        SELECT
            COUNT(*) AS TOTAL_RECORDS,

            COUNT_IF(
                PROCESSED_FLAG = TRUE
            ) AS PROCESSED_RECORDS,

            COUNT_IF(
                PROCESSED_FLAG = FALSE
            ) AS PENDING_RECORDS,

            COUNT_IF(
                TARGET_TABLE IS NULL
            ) AS UNMAPPED_RECORDS,

            COUNT_IF(
                STRUCTURE_HASH IS NULL
                AND PROCESSED_FLAG = FALSE
            ) AS UNHASHED_RECORDS

        FROM {raw_table}
    """

    row = session.sql(query).collect()[0]

    return {
        "total": row["TOTAL_RECORDS"],
        "processed": row["PROCESSED_RECORDS"],
        "pending": row["PENDING_RECORDS"],
        "unmapped": row["UNMAPPED_RECORDS"],
        "unhashed": row["UNHASHED_RECORDS"]
    }


def get_all_source_metrics(session, config):
    """
    Get metrics for FHIR, JSON and XML.
    """

    results = {}

    for source_type, source_config in config["sources"].items():

        results[source_type] = get_source_metrics(
            session,
            source_config
        )

    return results


def get_registry_metrics(session, config):
    """
    Get flatten query registry statistics.
    """

    registry_table = (
        config["control_tables"]["flatten_query_registry"]
    )

    query = f"""
        SELECT
            COUNT(*) AS TOTAL_QUERIES,

            COUNT(DISTINCT SOURCE_TYPE) AS SOURCE_TYPES,

            COUNT(DISTINCT STRUCTURE_HASH)
                AS STRUCTURES,

            COUNT(DISTINCT TARGET_TABLE)
                AS TARGET_TABLES

        FROM {registry_table}
    """

    row = session.sql(query).collect()[0]

    return {
        "total_queries": row["TOTAL_QUERIES"],
        "source_types": row["SOURCE_TYPES"],
        "structures": row["STRUCTURES"],
        "target_tables": row["TARGET_TABLES"]
    }


def get_error_metrics(session, config):
    """
    Get flatten error statistics.
    """

    error_table = (
        config["control_tables"]["flatten_error_log"]
    )

    query = f"""
        SELECT
            COUNT(*) AS TOTAL_ERRORS,

            COUNT_IF(
                STAGE = 'fingerprint'
            ) AS FINGERPRINT_ERRORS,

            COUNT_IF(
                STAGE = 'cortex_generate'
            ) AS CORTEX_ERRORS,

            COUNT_IF(
                STAGE = 'cortex_generate_validation'
            ) AS VALIDATION_ERRORS,

            COUNT_IF(
                STAGE = 'cortex_repair'
            ) AS REPAIR_ERRORS,

            COUNT_IF(
                STAGE = 'flatten_execute'
            ) AS EXECUTION_ERRORS

        FROM {error_table}
    """

    row = session.sql(query).collect()[0]

    return {
        "total": row["TOTAL_ERRORS"],
        "fingerprint": row["FINGERPRINT_ERRORS"],
        "cortex": row["CORTEX_ERRORS"],
        "validation": row["VALIDATION_ERRORS"],
        "repair": row["REPAIR_ERRORS"],
        "execution": row["EXECUTION_ERRORS"]
    }


def get_recent_errors(session, config):
    """
    Get recent flattening errors.
    """

    error_table = (
        config["control_tables"]["flatten_error_log"]
    )

    limit = int(
        config["dashboard"]["recent_errors_limit"]
    )

    query = f"""
        SELECT
            SOURCE_TYPE,
            TARGET_TABLE,
            STRUCTURE_HASH,
            STAGE,
            ERROR_MESSAGE,
            LOGGED_TS
        FROM {error_table}
        ORDER BY LOGGED_TS DESC
        LIMIT {limit}
    """

    return session.sql(query).to_pandas()


def get_recent_registry_entries(session, config):
    """
    Get recently generated/cached flatten queries.
    """

    registry_table = (
        config["control_tables"]["flatten_query_registry"]
    )

    limit = int(
        config["dashboard"]["recent_registry_limit"]
    )

    query = f"""
        SELECT
            SOURCE_TYPE,
            TARGET_TABLE,
            STRUCTURE_HASH,
            SAMPLE_RECORD_ID,
            CREATED_TS
        FROM {registry_table}
        ORDER BY CREATED_TS DESC
        LIMIT {limit}
    """

    return session.sql(query).to_pandas()


def get_mapping_metrics(session, config):
    """
    Get source-to-target mapping statistics.
    """

    mapping_table = (
        config["control_tables"]["source_target_mapping"]
    )

    query = f"""
        SELECT
            COUNT(*) AS MAPPING_ROWS,

            COUNT_IF(
                SOURCE_TYPE = 'FHIR'
            ) AS FHIR_MAPPINGS,

            COUNT_IF(
                SOURCE_TYPE = 'JSON'
            ) AS JSON_MAPPINGS,

            COUNT_IF(
                SOURCE_TYPE = 'XML'
            ) AS XML_MAPPINGS

        FROM {mapping_table}
    """

    row = session.sql(query).collect()[0]

    return {
        "total": row["MAPPING_ROWS"],
        "fhir": row["FHIR_MAPPINGS"],
        "json": row["JSON_MAPPINGS"],
        "xml": row["XML_MAPPINGS"]
    }