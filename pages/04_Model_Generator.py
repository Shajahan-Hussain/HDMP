
import streamlit as st

# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="dbt Model Generator - Healthcare Platform",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# IMPORTS
# ============================================================

import base64
import json
import re
from datetime import datetime

import pandas as pd
import requests
import yaml

from snowflake.snowpark.context import get_active_session
from style_utils import apply_style, render_header

# ============================================================
# SESSION STATE INITIALIZATION
# ============================================================

SESSION_DEFAULTS = {
    "github_connected": False,
    "github_validation_message": "",
    "github_user": "",
    "github_repo": "",
    "github_pat": "",
    "github_branch": "main",
    "github_owner": "",
    "github_repo_name": "",
    "metadata_uploaded": False,
    "generated_scripts": [],
}

for key, value in SESSION_DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

# ============================================================
# SNOWFLAKE SESSION
# ============================================================

session = get_active_session()

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def text_value(value):
    """Safely convert an Excel value to a trimmed string."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value).strip()


def sql_escape(value):
    """Escape a value for a Snowflake single-quoted string."""
    return text_value(value).replace("'", "''")


def clean_ai_response(response):
    """
    Clean the response returned by AI_COMPLETE.

    AI_COMPLETE can return the generated SQL as a quoted/escaped string,
    which may contain literal \\n sequences instead of actual line breaks.
    Normalize those sequences before storing or pushing the file.
    """
    response = text_value(response)

    # If AI_COMPLETE returned a JSON-style quoted string such as:
    # "select ...\\nfrom ..."
    # decode it so \\n becomes a real newline.
    if len(response) >= 2 and response[0] == '"' and response[-1] == '"':
        try:
            decoded = json.loads(response)
            if isinstance(decoded, str):
                response = decoded
        except (json.JSONDecodeError, TypeError):
            pass

    # Handle literal escaped line breaks even when the whole response
    # is not wrapped in quotes.
    response = response.replace("\\r\\n", "\n")
    response = response.replace("\\n", "\n")
    response = response.replace("\\r", "\r")
    response = response.replace("\\t", "\t")

    response = re.sub(
        r"^\s*```(?:sql|yaml|yml|text)?\s*",
        "",
        response,
        flags=re.IGNORECASE,
    )

    response = re.sub(
        r"\s*```\s*$",
        "",
        response,
        flags=re.IGNORECASE,
    )

    response = re.sub(
        r"^\s*(sure|certainly|here(?:'s| is)|output):?\s*",
        "",
        response,
        flags=re.IGNORECASE,
    )

    return response.strip()


def ai_complete(prompt, model="claude-sonnet-5"):
    """Call Snowflake AI_COMPLETE."""
    sql = f"""
        SELECT SNOWFLAKE.CORTEX.AI_COMPLETE(
            '{sql_escape(model)}',
            '{sql_escape(prompt)}'
        ) AS RESPONSE
    """

    rows = session.sql(sql).collect()

    if not rows:
        raise RuntimeError("AI_COMPLETE returned no result.")

    response = rows[0]["RESPONSE"]

    if response is None:
        raise RuntimeError("AI_COMPLETE returned an empty response.")

    return clean_ai_response(response)


def validate_github_connection(repo_user, repo_name, pat, branch):
    """Validate repository and branch access."""
    try:
        repo_user = text_value(repo_user)
        repo_name = text_value(repo_name).rstrip("/").replace(".git", "")
        pat = text_value(pat)
        branch = text_value(branch)

        if "github.com/" in repo_name:
            path = repo_name.split("github.com/", 1)[1].strip("/")
            parts = path.split("/")
            if len(parts) >= 2:
                repo_user = parts[0]
                repo_name = parts[1]

        if "/" in repo_name:
            parts = repo_name.split("/")
            if len(parts) >= 2:
                if not repo_user:
                    repo_user = parts[0]
                repo_name = parts[1]

        if not repo_user or not repo_name or not pat or not branch:
            return False, "❌ GitHub username, repository, PAT and branch are required."

        url = (
            f"https://api.github.com/repos/"
            f"{repo_user}/{repo_name}/branches/{branch}"
        )

        headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        }

        response = requests.get(url, headers=headers, timeout=15)

        if response.status_code == 200:
            return (
                True,
                f"✅ Successfully connected to "
                f"{repo_user}/{repo_name} (branch: {branch})",
            )

        if response.status_code == 404:
            repo_url = (
                f"https://api.github.com/repos/"
                f"{repo_user}/{repo_name}"
            )
            repo_response = requests.get(
                repo_url,
                headers=headers,
                timeout=15,
            )

            if repo_response.status_code == 200:
                return (
                    False,
                    f"❌ Repository found but branch "
                    f"'{branch}' does not exist.",
                )

            return False, "❌ Repository not found or access denied."

        if response.status_code == 401:
            return (
                False,
                "❌ Authentication failed. Please check the GitHub PAT.",
            )

        return (
            False,
            f"❌ GitHub request failed with status code "
            f"{response.status_code}.",
        )

    except requests.exceptions.Timeout:
        return False, "❌ GitHub connection timed out."
    except Exception as exc:
        return False, f"❌ Error: {exc}"


def push_file_to_github(token, owner, repo, branch, file_path, content, message):
    """Create or update a file in GitHub."""
    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/contents/{file_path}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    encoded = base64.b64encode(
        content.encode("utf-8")
    ).decode("utf-8")

    existing = requests.get(
        url,
        headers=headers,
        params={"ref": branch},
        timeout=20,
    )

    data = {
        "message": message,
        "content": encoded,
        "branch": branch,
    }

    if existing.status_code == 200:
        data["sha"] = existing.json().get("sha")

    return requests.put(
        url,
        headers=headers,
        json=data,
        timeout=30,
    )


def github_details():
    """Return normalized owner/repository from session state."""
    owner = text_value(st.session_state.get("github_owner"))
    repo = text_value(st.session_state.get("github_repo_name"))

    if owner and repo:
        return owner, repo

    user = text_value(st.session_state.get("github_user"))
    raw_repo = text_value(st.session_state.get("github_repo"))

    raw_repo = raw_repo.rstrip("/").replace(".git", "")

    if "github.com/" in raw_repo:
        raw_repo = raw_repo.split("github.com/", 1)[1].strip("/")

    parts = raw_repo.split("/")

    if len(parts) >= 2:
        return parts[0], parts[1]

    return user, raw_repo


def save_artifact(name, content, file_path, status):
    """Track generated artifacts in Streamlit session state."""
    st.session_state.generated_scripts.append(
        {
            "name": name,
            "content": content,
            "file_path": file_path,
            "github_status": status,
            "timestamp": datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
        }
    )


def normalize_mapping_columns(df):
    """
    Normalize the current Excel Mapping sheet headers.

    The current workbook uses uppercase names such as:
    TARGET_DATABASE, TARGET_SCHEMA, TARGET_TABLE, etc.
    """
    df = df.copy()

    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.upper()
    )

    return df


# ============================================================
# REQUIRED CURRENT EXCEL STRUCTURE
# ============================================================

REQUIRED_COLUMNS = [
    "SOURCE_DATABASE",
    "SOURCE_SCHEMA",
    "SOURCE_TABLE",
    "SOURCE_COLUMN",
    "SOURCE_DATATYPE",
    "SOURCE_NULLABLE",
    "TARGET_DATABASE",
    "TARGET_SCHEMA",
    "TARGET_TABLE",
    "TARGET_COLUMN",
    "TARGET_DATATYPE",
    "TARGET_NULLABLE",
    "MAPPING_RULE",
    "NOTES",
    "TABLE_DESCRIPTION",
    "BUSINESS_RULE",
    "CONFIDENCE",
    "COMMENTS",
]

# ============================================================
# STYLING
# ============================================================

# apply_style()
render_header()

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        text-align: center;
        padding: 1rem 0;
    }

    .info-box {
        padding: 1rem;
        border-radius: 5px;
        background-color: #e7f3ff;
        border-left: 5px solid #1f77b4;
        margin: 1rem 0;
    }

    .stButton > button {
        width: 100%;
        background-color: #1f77b4;
        color: white;
        border-radius: 5px;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="main-header">🗄️ dbt Model Generator</div>',
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="info-box">
    Generate dbt model files using AI, review them, and automatically
    push them to your GitHub repository.
    </div>
    """,
    unsafe_allow_html=True,
)

# ============================================================
# GITHUB CONNECTION
# ============================================================

st.markdown("### 🔗 GitHub Connection")

with st.expander(
    "⚙️ Configure GitHub Connection",
    expanded=not st.session_state.github_connected,
):

    st.markdown(
        "Configure your GitHub repository connection to enable Git push functionality."
    )

    github_user = st.text_input(
        "GitHub Repository User Name",
        value=st.session_state.github_user,
        help="Enter your GitHub repository username.",
    )

    github_repo = st.text_input(
        "GitHub Repository Name",
        value=st.session_state.github_repo,
        help=(
            "Enter repository name, owner/repository, "
            "or the GitHub repository URL."
        ),
    )

    github_pat = st.text_input(
        "Personal Access Token (PAT)",
        value=st.session_state.github_pat,
        type="password",
        placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
        help="GitHub Personal Access Token.",
    )

    github_branch = st.text_input(
        "Branch Name",
        value=st.session_state.github_branch,
        placeholder="main",
    )

    col_validate, col_disconnect = st.columns(2)

    with col_validate:
        if st.button(
            "🔍 Validate Connection",
            type="primary",
            use_container_width=True,
        ):

            if not github_repo or not github_pat or not github_branch:
                st.error(
                    "❌ Please fill in repository, PAT and branch."
                )
            else:

                with st.spinner(
                    "Validating GitHub connection..."
                ):

                    success, message = validate_github_connection(
                        github_user,
                        github_repo,
                        github_pat,
                        github_branch,
                    )

                st.session_state.github_connected = success
                st.session_state.github_validation_message = message

                if success:

                    repo_value = (
                        github_repo
                        .rstrip("/")
                        .replace(".git", "")
                    )

                    if "github.com/" in repo_value:
                        repo_value = repo_value.split(
                            "github.com/",
                            1,
                        )[1].strip("/")

                    parts = repo_value.split("/")

                    if len(parts) >= 2:
                        owner = parts[0]
                        repo_name = parts[1]
                    else:
                        owner = github_user.strip()
                        repo_name = parts[0]

                    st.session_state.github_user = github_user
                    st.session_state.github_repo = github_repo
                    st.session_state.github_pat = github_pat
                    st.session_state.github_branch = github_branch
                    st.session_state.github_owner = owner
                    st.session_state.github_repo_name = repo_name

    with col_disconnect:

        if st.button(
            "🔌 Disconnect",
            use_container_width=True,
            disabled=not st.session_state.github_connected,
        ):

            st.session_state.github_connected = False
            st.session_state.github_validation_message = ""
            st.session_state.github_user = ""
            st.session_state.github_repo = ""
            st.session_state.github_pat = ""
            st.session_state.github_owner = ""
            st.session_state.github_repo_name = ""
            st.session_state.github_branch = "main"

            st.rerun()

    if st.session_state.github_validation_message:

        if st.session_state.github_connected:
            st.success(
                st.session_state.github_validation_message
            )
        else:
            st.error(
                st.session_state.github_validation_message
            )

if st.session_state.github_connected:

    st.success(
        f"✅ Connected to GitHub: "
        f"{st.session_state.github_owner}/"
        f"{st.session_state.github_repo_name} "
        f"(branch: {st.session_state.github_branch})"
    )

st.markdown("---")

# ============================================================
# MAPPING FILE
# ============================================================

st.subheader("Model Generation")

st.markdown(
    "### 📤 Upload Source - Target Mapping File"
)

mapping_file = st.file_uploader(
    "Upload Excel file with S-T mapping data for Gold Layer dbt models",
    type=["xlsx", "xls"],
    help=(
        "The current mapping workbook is expected to contain "
        "a sheet named 'Mapping'."
    ),
    key="mapping_uploader",
)

df = None

if mapping_file:

    try:

        df = pd.read_excel(
            mapping_file,
            sheet_name="Mapping",
        )

        df = normalize_mapping_columns(df)

        missing_columns = [
            col
            for col in REQUIRED_COLUMNS
            if col not in df.columns
        ]

        if missing_columns:

            st.session_state.metadata_uploaded = False

            st.error(
                "❌ The Mapping sheet is missing required columns."
            )

            st.code(
                "\n".join(missing_columns)
            )

            st.info(
                "The application normalizes Excel headers to uppercase. "
                "Please compare the missing columns with your Mapping sheet."
            )

            df = None

        else:

            st.session_state.metadata_uploaded = True

            st.success(
                f"✅ Mapping file uploaded: "
                f"{mapping_file.name}"
            )

            with st.expander("📋 Mapping Preview"):

                st.dataframe(
                    df,
                    use_container_width=True,
                )

            with st.expander("📋 Mapping File Details"):

                st.write(
                    f"**Filename:** {mapping_file.name}"
                )

                st.write(
                    f"**Size:** "
                    f"{mapping_file.size / 1024:.2f} KB"
                )

                st.write(
                    f"**Rows:** {len(df)}"
                )

                st.write(
                    f"**Columns:** "
                    f"{', '.join(df.columns.tolist())}"
                )

    except ValueError:

        st.session_state.metadata_uploaded = False

        st.error(
            "❌ The uploaded workbook does not contain "
            "a sheet named 'Mapping'."
        )

        df = None

    except Exception as exc:

        st.session_state.metadata_uploaded = False

        st.error(
            f"❌ Failed to read the mapping workbook: {exc}"
        )

        df = None

# ============================================================
# GENERATE BUTTON
# ============================================================

st.markdown("---")

generate_disabled = (
    df is None
    or not st.session_state.metadata_uploaded
    or not st.session_state.github_connected
)

if (
    df is not None
    and not st.session_state.github_connected
):

    st.warning(
        "⚠️ Please configure and validate GitHub connection "
        "before generating dbt scripts."
    )

if st.button(
    "🚀 Generate dbt Scripts",
    type="primary",
    disabled=generate_disabled,
):

    st.write(
        "🚀 Generating dbt models..."
    )

    st.write(
        "🚀 Reading current Mapping sheet..."
    )

    # --------------------------------------------------------
    # Group by CURRENT Excel target columns
    # --------------------------------------------------------

    grouped = df.groupby(
        [
            "TARGET_DATABASE",
            "TARGET_SCHEMA",
            "TARGET_TABLE",
        ],
        dropna=False,
    )

    generated_model_count = 0
    failed_model_count = 0

    # ========================================================
    # MODEL GENERATION
    # ========================================================

    for (
        target_database,
        target_schema,
        target_table,
    ), subdf in grouped:

        target_database = text_value(target_database)
        target_schema = text_value(target_schema)
        target_table = text_value(target_table)

        if not target_table:
            st.warning(
                "⚠️ Skipping a mapping group with an empty TARGET_TABLE."
            )
            continue

        st.markdown(
            f"### 🤖 {target_database}.{target_schema}.{target_table}"
        )

        mapping_lines = []
        source_tables = set()

        table_description = ""

        for _, row in subdf.iterrows():

            source_database = text_value(
                row.get("SOURCE_DATABASE")
            )

            source_schema = text_value(
                row.get("SOURCE_SCHEMA")
            )

            source_table = text_value(
                row.get("SOURCE_TABLE")
            )

            source_column = text_value(
                row.get("SOURCE_COLUMN")
            )

            source_datatype = text_value(
                row.get("SOURCE_DATATYPE")
            )

            source_nullable = text_value(
                row.get("SOURCE_NULLABLE")
            )

            target_column = text_value(
                row.get("TARGET_COLUMN")
            )

            target_datatype = text_value(
                row.get("TARGET_DATATYPE")
            )

            target_nullable = text_value(
                row.get("TARGET_NULLABLE")
            )

            mapping_rule = text_value(
                row.get("MAPPING_RULE")
            )

            notes = text_value(
                row.get("NOTES")
            )

            row_description = text_value(
                row.get("TABLE_DESCRIPTION")
            )

            business_rule = text_value(
                row.get("BUSINESS_RULE")
            )

            confidence = text_value(
                row.get("CONFIDENCE")
            )

            comments = text_value(
                row.get("COMMENTS")
            )

            if not table_description and row_description:
                table_description = row_description

            if source_database and source_schema and source_table:

                source_tables.add(
                    f"{source_database}.{source_schema}.{source_table}"
                )

            mapping_lines.append(
                f"""
SOURCE_DATABASE  : {source_database}
SOURCE_SCHEMA    : {source_schema}
SOURCE_TABLE     : {source_table}
SOURCE_COLUMN    : {source_column}
SOURCE_DATATYPE  : {source_datatype}
SOURCE_NULLABLE  : {source_nullable}

TARGET_DATABASE  : {target_database}
TARGET_SCHEMA    : {target_schema}
TARGET_TABLE     : {target_table}
TARGET_COLUMN    : {target_column}
TARGET_DATATYPE  : {target_datatype}
TARGET_NULLABLE  : {target_nullable}

MAPPING_RULE     : {mapping_rule}
NOTES            : {notes}
TABLE_DESCRIPTION: {row_description}
BUSINESS_RULE    : {business_rule}
CONFIDENCE       : {confidence}
COMMENTS         : {comments}
"""
            )

        mapping_str = "\n".join(mapping_lines)
        source_tables_str = "\n".join(sorted(source_tables))

        # ----------------------------------------------------
        # CURRENT-MAPPING AI PROMPT
        # ----------------------------------------------------

        model_prompt = f"""
You are an expert Snowflake analytics engineer and dbt developer.

Generate ONE production-ready dbt SQL model for the target table
specified below.

The Excel Mapping sheet is the AUTHORITATIVE specification.
Do not invent source tables, source columns, target columns,
relationships, filters, transformations, or business rules.

============================================================
TARGET
============================================================

TARGET_DATABASE : {target_database}
TARGET_SCHEMA   : {target_schema}
TARGET_TABLE    : {target_table}

TABLE_DESCRIPTION:
{table_description}

SOURCE TABLES:
{source_tables_str}

============================================================
CURRENT EXCEL MAPPING
============================================================

{mapping_str}

============================================================
TRANSFORMATION RULES
============================================================

1. MAPPING_RULE is the primary column-level transformation
   instruction.

2. BUSINESS_RULE provides business-level logic and must be
   followed when it contains a requirement.

3. NOTES and COMMENTS provide additional implementation
   guidance.

4. CONFIDENCE is metadata about the mapping. Do not use it as
   transformation logic unless the mapping explicitly says so.

5. SOURCE_DATATYPE and TARGET_DATATYPE must be considered when
   casts or conversions are required.

6. SOURCE_NULLABLE and TARGET_NULLABLE must be respected.

7. Every mapped TARGET_COLUMN must be generated unless the
   metadata explicitly says otherwise.

8. Do not invent columns or relationships.

============================================================
DBT REFERENCES
============================================================

For each source table, determine the dbt reference from its
SOURCE_SCHEMA.

If SOURCE_SCHEMA is RAW:
    {{ source('<source_schema>', '<source_table>') }}

If SOURCE_SCHEMA is STAGING:
    {{ ref('<source_table>') }}

If SOURCE_SCHEMA is SILVER:
    {{ ref('<source_table>') }}

If SOURCE_SCHEMA is INTERMEDIATE:
    {{ ref('<source_table>') }}

If SOURCE_SCHEMA is GOLD:
    {{ ref('<source_table>') }}

For other schemas, choose the appropriate dbt reference based
only on the mapping metadata.

When multiple source tables are required, use separate CTEs and
join them only when the mapping/business rules provide enough
information to establish the relationship.

============================================================
SNOWFLAKE SQL REQUIREMENTS
============================================================

- SQL must be executable in Snowflake.
- Use Snowflake SQL syntax and functions.
- Use CTEs.
- Use meaningful aliases.
- Prefix columns in joins.
- Do not use SELECT *.
- The final SELECT must explicitly list all target columns.
- Preserve TARGET_COLUMN names exactly.
- Use explicit CAST where needed.
- Avoid unnecessary nested subqueries.
- Avoid duplicate rows unless required by the business rule.
- Do not invent surrogate-key logic unless the mapping requires it.
- Do not invent filters.
- Do not invent joins.
- Do not add a semicolon at the end.

============================================================
DBT CONFIG
============================================================

Add a dbt config block.

Use:

{{ config(
    materialized='table',
    database='{target_database}',
    schema='{target_schema}'
) }}

The current Mapping workbook does not contain a dedicated
MATERIALIZATION column, so use table materialization by default.

============================================================
MODEL HEADER
============================================================

Add this SQL comment header:

------------------------------------------------------------------------
MODEL NAME    :
TARGET TABLE  :
SOURCE TABLES :
DESCRIPTION   :
PREREQUISITES :
PARAMETER     :
AUTHOR        :
------------------------------------------------------------------------

Populate it using the mapping metadata.

AUTHOR must be:

AI Generated by Shajahan - {datetime.now().strftime('%Y-%m-%d')}

============================================================
OUTPUT
============================================================

Return ONLY executable SQL.

No Markdown.
No code fences.
No explanation.
No YAML.
No prose outside the SQL.
"""

        try:

            print(
                f"Calling AI_COMPLETE for "
                f"{target_database}.{target_schema}.{target_table}"
            )

            model_sql = ai_complete(
                model_prompt
            )

            if not model_sql:
                raise RuntimeError(
                    "Cortex returned an empty model."
                )

            # ------------------------------------------------
            # Push model
            # ------------------------------------------------

            file_path = (
                f"models/gold/{target_table.lower()}.sql"
            )

            owner, repo = github_details()

            if not owner or not repo:
                raise RuntimeError(
                    "GitHub owner/repository is not available."
                )

            commit_message = (
                f"Auto commit - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            response = push_file_to_github(
                token=st.session_state.github_pat,
                owner=owner,
                repo=repo,
                branch=st.session_state.github_branch,
                file_path=file_path,
                content=model_sql,
                message=commit_message,
            )

            if response.status_code in [200, 201]:

                status = "✅ Pushed"

                st.success(
                    f"✅ Generated and pushed `{file_path}`"
                )

            else:

                status = (
                    f"❌ Push failed: "
                    f"{response.status_code}"
                )

                st.error(
                    f"❌ Failed to push `{file_path}`"
                )

                st.code(
                    response.text,
                    language="json",
                )

            save_artifact(
                name=file_path,
                content=model_sql,
                file_path=file_path,
                status=status,
            )

            generated_model_count += 1

        except Exception as exc:

            failed_model_count += 1

            st.error(
                f"❌ Failed to generate "
                f"{target_database}.{target_schema}.{target_table}: "
                f"{exc}"
            )

            print(
                f"ERROR: {target_table}: {exc}"
            )

    # ========================================================
    # SCHEMA.YML GENERATION
    # ========================================================

    st.markdown("---")
    st.subheader("📄 Generating schema.yml")

    model_summary = []

    for (
        target_database,
        target_schema,
        target_table,
    ), subdf in grouped:

        target_database = text_value(target_database)
        target_schema = text_value(target_schema)
        target_table = text_value(target_table)

        table_description = ""

        for value in subdf["TABLE_DESCRIPTION"]:
            value = text_value(value)
            if value:
                table_description = value
                break

        columns = []

        for _, row in subdf.iterrows():

            columns.append(
                f"""
TARGET_COLUMN   : {text_value(row.get("TARGET_COLUMN"))}
TARGET_DATATYPE : {text_value(row.get("TARGET_DATATYPE"))}
SOURCE_COLUMN   : {text_value(row.get("SOURCE_COLUMN"))}
MAPPING_RULE    : {text_value(row.get("MAPPING_RULE"))}
BUSINESS_RULE   : {text_value(row.get("BUSINESS_RULE"))}
NOTES           : {text_value(row.get("NOTES"))}
COMMENTS        : {text_value(row.get("COMMENTS"))}
"""
            )

        model_summary.append(
            f"""
MODEL: {target_table}
DATABASE: {target_database}
SCHEMA: {target_schema}
DESCRIPTION: {table_description}

COLUMNS:
{chr(10).join(columns)}
"""
        )

    schema_prompt = f"""
You are an expert Snowflake and dbt developer.

Generate ONE valid dbt schema.yml file for these models.

============================================================
MODELS
============================================================

{chr(10).join(model_summary)}

============================================================
REQUIREMENTS
============================================================

- Start with version: 2.
- Include models:.
- Create one model entry for every target model.
- Use the TARGET_TABLE as the dbt model name.
- Add model descriptions using TABLE_DESCRIPTION.
- Add every TARGET_COLUMN.
- Do not invent columns.
- Use MAPPING_RULE, BUSINESS_RULE, NOTES and COMMENTS to create
  useful column descriptions.
- Do not add tests unless the mapping metadata explicitly supports
  the test requirement.
- Use valid YAML indentation.
- Do not add database/schema/type fields unnecessarily.
- Return YAML only.
- Do not use Markdown fences.
- Do not add explanations.
"""

    try:

        schema_yml = ai_complete(
            schema_prompt
        )

        schema_path = "models/gold/models.yml"

        owner, repo = github_details()

        response = push_file_to_github(
            token=st.session_state.github_pat,
            owner=owner,
            repo=repo,
            branch=st.session_state.github_branch,
            file_path=schema_path,
            content=schema_yml,
            message=(
                f"Auto commit - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        )

        if response.status_code in [200, 201]:
            status = "✅ Pushed"
            st.success(
                f"✅ Generated and pushed `{schema_path}`"
            )
        else:
            status = f"❌ Push failed: {response.status_code}"
            st.error(
                f"❌ Failed to push `{schema_path}`"
            )

        save_artifact(
            name=schema_path,
            content=schema_yml,
            file_path=schema_path,
            status=status,
        )

    except Exception as exc:

        st.error(
            f"❌ Failed to generate schema.yml: {exc}"
        )

    # ========================================================
    # PROFILES.YML
    # ========================================================

    st.markdown("---")
    st.subheader("⚙️ Generating profiles.yml")

    profiles_content = """healthcare_dbt_project:
  target: dev
  outputs:
    dev:
      account: 'not needed'
      database: HDMP_SILVER
      role: ACCOUNTADMIN
      schema: PUBLIC
      threads: 1
      type: snowflake
      user: 'not needed'
      warehouse: COMPUTE_WH
"""

    profiles_path = "profiles.yml"

    try:

        owner, repo = github_details()

        response = push_file_to_github(
            token=st.session_state.github_pat,
            owner=owner,
            repo=repo,
            branch=st.session_state.github_branch,
            file_path=profiles_path,
            content=profiles_content,
            message=(
                f"Auto commit - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        )

        if response.status_code in [200, 201]:
            status = "✅ Pushed"
            st.success(
                f"✅ Generated and pushed `{profiles_path}`"
            )
        else:
            status = f"❌ Push failed: {response.status_code}"
            st.error(
                f"❌ Failed to push `{profiles_path}`"
            )

        save_artifact(
            name=profiles_path,
            content=profiles_content,
            file_path=profiles_path,
            status=status,
        )

    except Exception as exc:

        st.error(
            f"❌ Failed to push profiles.yml: {exc}"
        )

    # ========================================================
    # DBT_PROJECT.YML
    # ========================================================

    st.markdown("---")
    st.subheader("⚙️ Generating dbt_project.yml")

    project_content = """name: 'healthcare_dbt_project'
version: '1.0.0'
config-version: 2

profile: 'healthcare_dbt_project'

model-paths: ["models"]
analysis-paths: ["analyses"]
test-paths: ["tests"]
seed-paths: ["seeds"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

vars:
  dbt_date:time_zone: 'Asia/Kolkata'

on-run-end:
  - "truncate table if exists EHDP.LOGS.MODELS"
  - "truncate table if exists EHDP.LOGS.TESTS"
  - "truncate table if exists EHDP.LOGS.SNAPSHOTS"
  - "truncate table if exists EHDP.LOGS.SEEDS"
  - "truncate table if exists EHDP.LOGS.SOURCES"
  - "{{ dbt_artifacts.upload_results(results) }}"

target-path: "target"

clean-targets:
  - "target"
  - "dbt_packages"

models:
  healthcare_dbt_project:
    gold:
      +materialized: table

  dbt_artifacts:
    +enabled: false
    sources:
      +enabled: true
      +schema: logs
"""

    project_path = "dbt_project.yml"

    try:

        owner, repo = github_details()

        response = push_file_to_github(
            token=st.session_state.github_pat,
            owner=owner,
            repo=repo,
            branch=st.session_state.github_branch,
            file_path=project_path,
            content=project_content,
            message=(
                f"Auto commit - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            ),
        )

        if response.status_code in [200, 201]:
            status = "✅ Pushed"
            st.success(
                f"✅ Generated and pushed `{project_path}`"
            )
        else:
            status = f"❌ Push failed: {response.status_code}"
            st.error(
                f"❌ Failed to push `{project_path}`"
            )

        save_artifact(
            name=project_path,
            content=project_content,
            file_path=project_path,
            status=status,
        )

    except Exception as exc:

        st.error(
            f"❌ Failed to push dbt_project.yml: {exc}"
        )

    # ========================================================
    # FINAL SUMMARY
    # ========================================================

    st.markdown("---")
    st.subheader("📊 Generation Summary")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Total Models",
            generated_model_count + failed_model_count,
        )

    with col2:
        st.metric(
            "Successfully Generated",
            generated_model_count,
        )

    with col3:
        st.metric(
            "Failed",
            failed_model_count,
        )

    if failed_model_count == 0:
        st.success(
            "🎉 All dbt models and supporting artifacts "
            "were generated successfully."
        )
    else:
        st.warning(
            "⚠️ Generation completed with some model failures. "
            "Review the errors above."
        )

# ============================================================
# GENERATED ARTIFACTS
# ============================================================

if st.session_state.generated_scripts:

    st.markdown("---")
    st.subheader("📦 Generated Artifacts")

    artifact_df = pd.DataFrame(
        [
            {
                "File": item["file_path"],
                "GitHub Status": item["github_status"],
                "Timestamp": item["timestamp"],
            }
            for item in st.session_state.generated_scripts
        ]
    )

    st.dataframe(
        artifact_df,
        use_container_width=True,
    )

    for index, item in enumerate(
        st.session_state.generated_scripts
    ):

        with st.expander(
            f"📄 {item['file_path']}"
        ):

            extension = item["file_path"].lower()

            if extension.endswith(".sql"):
                language = "sql"
            elif extension.endswith((".yml", ".yaml")):
                language = "yaml"
            else:
                language = "text"

            st.code(
                item["content"],
                language=language,
            )

            st.download_button(
                label=f"⬇️ Download {item['name']}",
                data=item["content"],
                file_name=item["name"],
                mime="text/plain",
                key=f"download_{index}_{item['name']}",
                use_container_width=True,
            )
