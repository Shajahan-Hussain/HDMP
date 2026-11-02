import streamlit as st
import requests
import pandas as pd
import os
import snowflake.connector
from datetime import datetime
from style_utils import apply_style, render_header
import time
import base64
import io
import zipfile
from snowflake.snowpark.context import get_active_session
import tempfile


session = get_active_session()

# Apply Styles
# apply_style()
render_header()

# Page configuration
st.set_page_config(
    page_title="DDL Generator - Healthcare Platform",
    page_icon="🗄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Snowflake connection function
@st.cache_resource

# Function to validate GitHub connection
def validate_github_connection(repo_user, repo_name, pat, branch):
    """Validate GitHub connection using PAT and check if branch exists"""
    try:
        # repo_url = repo_url.rstrip('/')
        # if repo_url.endswith('.git'):
        #     repo_url = repo_url[:-4]
        
        # parts = repo_url.split('github.com/')
        # if len(parts) < 2:
        #     return False, "Invalid GitHub URL format"
        
        # repo_path = parts[1].strip('/')
        api_url = f"https://api.github.com/repos/{repo_user}/{repo_name}/branches/{branch}"
        
        headers = {
            'Authorization': f'token {pat}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        response = requests.get(api_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            return True, f"✅ Successfully connected to {repo_name} (branch: {branch})"
        elif response.status_code == 404:
            repo_check_url = f"https://api.github.com/repos/{repo_user}/{repo_name}"
            repo_response = requests.get(repo_check_url, headers=headers, timeout=10)
            
            if repo_response.status_code == 200:
                return False, f"❌ Repository found but branch '{branch}' does not exist"
            else:
                return False, "❌ Repository not found or access denied"
        elif response.status_code == 401:
            return False, "❌ Authentication failed. Please check your Personal Access Token"
        else:
            return False, f"❌ Connection failed with status code: {response.status_code}"
            
    except requests.exceptions.Timeout:
        return False, "❌ Connection timeout. Please check your internet connection"
    except Exception as e:
        return False, f"❌ Error: {str(e)}"

def push_file_to_github(token, owner, repo, branch, file_path, content, message):
    """Push file to GitHub repository"""
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{file_path}"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    
    encoded_content = base64.b64encode(content.encode()).decode()
    
    # Check if file exists
    r = requests.get(url, headers=headers, params={"ref": branch})
    sha = None
    if r.status_code == 200:
        sha = r.json()["sha"]
    
    data = {
        "message": message,
        "content": encoded_content,
        "branch": branch
    }
    
    if sha:
        data["sha"] = sha
    
    response = requests.put(url, headers=headers, json=data)
    return response

# Custom CSS
st.markdown("""
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
    .stButton>button {
        width: 100%;
        background-color: #1f77b4;
        color: white;
        border-radius: 5px;
        padding: 0.5rem 1rem;
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🗄️ DDL Generator</div>', unsafe_allow_html=True)

st.markdown("""
<div class="info-box">
Generate DDL scripts from Excel metadata file and deploy via Git or execute directly in Snowflake
</div>
""", unsafe_allow_html=True)

# Initialize session state
if 'generated_scripts' not in st.session_state:
    st.session_state.generated_scripts = []
if 'metadata_uploaded' not in st.session_state:
    st.session_state.metadata_uploaded = False
if 'generation_complete' not in st.session_state:
    st.session_state.generation_complete = False
if 'github_owner' not in st.session_state:
    st.session_state.github_owner = ""
if 'github_repo_name' not in st.session_state:
    st.session_state.github_repo_name = ""
if 'github_connected' not in st.session_state:
    st.session_state.github_connected = False
if 'github_validation_message' not in st.session_state:
    st.session_state.github_validation_message = ""

col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("### 📤 Upload Metadata File")
    metadata_file = st.file_uploader(
        "Upload Excel file with object metadata",
        type=["xlsx", "xls"],
        help="Upload an Excel file containing metadata for databases, schemas, tables, and other Snowflake objects",
        key="metadata_uploader"
    )
    
    if metadata_file:
        st.success(f"✅ Metadata file uploaded: {metadata_file.name}")
        st.session_state.metadata_uploaded = True

        df = pd.read_excel(metadata_file)

        with st.expander("📋 Metadata Preview"):
            st.dataframe(df, use_container_width=True)
        
        # Show file info
        with st.expander("📋 Metadata File Details"):
            st.write(f"**Filename:** {metadata_file.name}")
            st.write(f"**Size:** {metadata_file.size / 1024:.2f} KB")
            st.write(f"**Type:** {metadata_file.type}")
            st.write(f"**Rows:** {len(df)}")
            st.write(f"**Columns:** {', '.join(df.columns.tolist())}")
    
    st.markdown("---")
    
    # GitHub Connection Section
    st.markdown("### 🔗 GitHub Connection")
    
    with st.expander("⚙️ Configure GitHub Connection", expanded=not st.session_state.github_connected):
        st.markdown("Configure your GitHub repository connection to enable Git push functionality")
        
        # github_repo = st.text_input(
        #     "GitHub Repository URL",
        #     placeholder="https://github.com/username/repository",
        #     help="Enter your GitHub repository URL (e.g., https://github.com/username/repo)"
        # )

        github_user = st.text_input(
            "GitHub User Name",
            placeholder = "",
            help = "Enter the GitHub User Name"
        )

        github_repo = st.text_input(
            "GitHub Repo Name",
            placeholder = "",
            help = "Enter the GitHub Repo Name"
        )
        
        github_pat = st.text_input(
            "Personal Access Token (PAT)",
            type="password",
            placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
            help="Generate a PAT from GitHub Settings > Developer settings > Personal access tokens"
        )
        
        github_branch = st.text_input(
            "Branch Name",
            value="main",
            placeholder="main",
            help="Target branch for pushing DDL scripts"
        )
        
        col_validate, col_disconnect = st.columns([1, 1])
        
        with col_validate:
            if st.button("🔍 Validate Connection", type="primary", use_container_width=True):
                if not github_repo or not github_pat or not github_branch:
                    st.error("❌ Please fill in all fields")
                else:
                    with st.spinner("Validating GitHub connection..."):
                        success, message = validate_github_connection(github_user, github_repo, github_pat, github_branch)
                        st.session_state.github_connected = success
                        st.session_state.github_validation_message = message
                        
                        if success:
                            # Extract owner and repo name
                            repo_url = github_repo.rstrip('/').replace('.git', '')
                            parts = repo_url.split('github.com/')
                            if len(parts) >= 2:
                                repo_parts = parts[1].strip('/').split('/')
                                if len(repo_parts) >= 2:
                                    st.session_state.github_owner = repo_parts[0]
                                    st.session_state.github_repo_name = repo_parts[1]
                            
                            st.session_state.github_user = github_user
                            st.session_state.github_repo = github_repo
                            st.session_state.github_pat = github_pat
                            st.session_state.github_branch = github_branch
        
        with col_disconnect:
            if st.button("🔌 Disconnect", use_container_width=True, disabled=not st.session_state.github_connected):
                st.session_state.github_connected = False
                st.session_state.github_validation_message = ""
                st.session_state.pop('github_repo', None)
                st.session_state.pop('github_pat', None)
                st.session_state.pop('github_branch', None)
                st.session_state.pop('github_owner', None)
                st.session_state.pop('github_repo_name', None)
                st.rerun()
        
        if st.session_state.github_validation_message:
            if st.session_state.github_connected:
                st.success(st.session_state.github_validation_message)
            else:
                st.error(st.session_state.github_validation_message)
    
    if st.session_state.github_connected:
        st.success(f"✅ Connected to GitHub: {st.session_state.get('github_repo', 'Unknown')} (branch: {st.session_state.get('github_branch', 'Unknown')})")
    
    st.markdown("---")
    
    # Environment Selection
    st.markdown("### 🎯 Target Environment")
    environment = st.selectbox(
        "Select Environment",
        ["DEV", "QA", "UAT", "PROD"],
        help="Select the target environment for deployment"
    )
    
    st.markdown("---")
    
    # Generate Button
    generate_disabled = not st.session_state.metadata_uploaded or not st.session_state.github_connected
    
    if not st.session_state.github_connected and st.session_state.metadata_uploaded:
        st.warning("⚠️ Please configure and validate GitHub connection before generating DDL scripts")
    
    if st.button("🚀 Generate DDL Scripts", type="primary", disabled=generate_disabled):
        if metadata_file is None:
            st.error("⚠️ Please upload a Metadata File before generating ddls.")
        with st.spinner("Processing metadata and generating DDL scripts..."):
            import time
            time.sleep(2)  # Simulate processing
            
            # Normalize text
            df["object_type"] = df["object_type"].str.upper().str.strip()
            df["property"] = df["property"].str.upper().str.strip()

            # Fetch Databases from the metadata file
            db_df = df[df.object_type == "DATABASE"]

            databases = {}

            for _, row in db_df.iterrows():
                db = row["object_name"]
                prop = row["property"]
                val = row["value"]

                databases.setdefault(db, {})[prop] = val

            # Fetch Schemas from the metadata file
            schema_df = df[df.object_type == "SCHEMA"]

            schemas = {}

            for _, row in schema_df.iterrows():
                db = row["database"]
                schema = row["object_name"]
                prop = row["property"]
                val = row["value"]

                schemas.setdefault((db, schema), {})[prop] = val

            # Fetch stages from the metadata file
            stage_df = df[df.object_type == "STAGE"]

            stages = {}

            for _, row in stage_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])
                stages.setdefault(key, {})[row["property"]] = row["value"]


            # Fetch fileformats from the metadata file
            ff_df = df[df.object_type == "FILE_FORMAT"]

            file_formats = {}

            for _, row in ff_df.iterrows():
                fmt = (row["database"], row["schema"], row["object_name"])
                file_formats.setdefault(fmt, {})[row["property"]] = row["value"]


            # Fetch tables and columns from the Metadata file 
            table_df = df[df.object_type == "TABLE"]

            tables = {}

            for _, row in table_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])
                tables.setdefault(key, {})[row["property"]] = row["value"]

            col_df = df[df.object_type == "COLUMN"]

            columns = {}

            for _, row in col_df.iterrows():
                key = (row["database"], row["schema"], row["parent_object"])  # parent_object = table
                col_name = row["object_name"]
                prop = row["property"]
                val = row["value"]

                columns.setdefault(key, {}).setdefault(col_name, {})[prop] = val

            # Fetch warehouse from the metadata file
            wh_df = df[df.object_type == "WAREHOUSE"]

            warehouses = {}

            for _, row in wh_df.iterrows():
                wh = row["object_name"]
                warehouses.setdefault(wh, {})[row["property"]] = row["value"]


            # Fetch warehouse from the metadata file
            rm_df = df[df.object_type == "RESOURCE_MONITOR"]

            resource_monitors = {}

            for _, row in rm_df.iterrows():
                rm = row["object_name"]
                resource_monitors.setdefault(rm, {})[row["property"]] = row["value"]

           # Fetch copy commands from the metadata file
            copy_cmds = {}

            # COPY level metadata
            copy_df = df[df.object_type == "COPY"]

            for _, row in copy_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])

                copy_cmds.setdefault(key, {
                    "properties": {},
                    "columns": []
                })

                copy_cmds[key]["properties"][row["property"]] = row["value"]


            # COPY column mappings
            copy_col_df = df[df.object_type == "COPY_COLUMN"]

            for _, row in copy_col_df.iterrows():
                key = (row["database"], row["schema"], row["parent_object"])

                column_def = {
                    "column": row["object_name"],
                    "expression": row["value"]
                }

                copy_cmds.setdefault(key, {
                    "properties": {},
                    "columns": []
                })

                copy_cmds[key]["columns"].append(column_def)

            # Fetch storage integration commands from the metadata file
            storage_df = df[df.object_type == "STORAGE_INTEGRATION"]

            storage_integrations = {}

            for _, row in storage_df.iterrows():
                key = row["object_name"]
                storage_integrations.setdefault(key, {})[row["property"]] = row["value"]

            # Fetch notification integration commands from the metadata file
            notif_df = df[df.object_type == "NOTIFICATION_INTEGRATION"]

            notification_integrations = {}

            for _, row in notif_df.iterrows():
                key = row["object_name"]
                notification_integrations.setdefault(key, {})[row["property"]] = row["value"]

            # Fetch stream commands from the metadata file
            stream_df = df[df.object_type == "STREAM"]

            streams = {}

            for _, row in stream_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])
                streams.setdefault(key, {})[row["property"]] = row["value"]

            # Fetch task commands from the metadata file
            task_df = df[df.object_type == "TASK"]

            tasks = {}

            for _, row in task_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])
                tasks.setdefault(key, {})[row["property"]] = row["value"]

            # Fetch snowpipe commands from the metadata file
            pipe_df = df[df.object_type == "SNOWPIPE"]

            snowpipes = {}

            for _, row in pipe_df.iterrows():
                key = (row["database"], row["schema"], row["object_name"])
                snowpipes.setdefault(key, {})[row["property"]] = row["value"]

            # FUNCTIONS 

            def format_databases_for_cortex(databases: dict) -> str:
                blocks = []
                for db_name, props in databases.items():
                    lines = [
                        "OBJECT_TYPE: DATABASE",
                        f"NAME: {db_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_schemas_for_cortex(schemas: dict) -> str:
                blocks = []
                for (db_name, schema_name), props in schemas.items():
                    lines = [
                        "OBJECT_TYPE: SCHEMA",
                        f"DATABASE: {db_name}",
                        f"NAME: {schema_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_stages_for_cortex(stages: dict) -> str:
                blocks = []
                for (db, schema, stage_name), props in stages.items():
                    lines = [
                        "OBJECT_TYPE: STAGE",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {stage_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_file_formats_for_cortex(file_formats: dict) -> str:
                blocks = []
                for (db, schema, fmt_name),props in file_formats.items():
                    lines = [
                        "OBJECT_TYPE: FILE_FORMAT",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {fmt_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_tables_for_cortex(tables: dict) -> str:
                blocks = []
                for (db, schema, table_name), props in tables.items():
                    lines = [
                        "OBJECT_TYPE: TABLE",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {table_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_columns_for_cortex(columns: dict) -> str:
                blocks = []

                for (db, schema, table_name), cols in columns.items():
                    lines = [
                        "OBJECT_TYPE: COLUMNS",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"PARENT_TABLE: {table_name}",
                        "COLUMNS:"
                    ]

                    for col_name, props in cols.items():
                        lines.append(f"  - COLUMN_NAME: {col_name}")
                        for prop, val in props.items():
                            lines.append(f"      {prop}: {val}")

                    blocks.append("\n".join(lines))

                return "\n\n".join(blocks)

            def format_warehouses_for_cortex(warehouses: dict) -> str:
                blocks = []
                for wh_name, props in warehouses.items():
                    lines = [
                        "OBJECT_TYPE: WAREHOUSE",
                        f"NAME: {wh_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)


            def format_resource_monitors_for_cortex(resource_monitors: dict) -> str:
                blocks = []
                for rm_name, props in resource_monitors.items():
                    lines = [
                        "OBJECT_TYPE: RESOURCE_MONITOR",
                        f"NAME: {rm_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)


            def format_copy_commands_for_cortex(copy_cmds: dict) -> str:
                blocks = []

                for (db, schema, table_name), meta in copy_cmds.items():

                    lines = [
                        "OBJECT_TYPE: COPY_COMMAND",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"TARGET_TABLE: {table_name}",
                        "PROPERTIES:"
                    ]

                    for prop, val in meta["properties"].items():
                        lines.append(f"  - {prop}: {val}")

                    if meta["columns"]:
                        lines.append("COLUMN_MAPPINGS:")

                        for col in meta["columns"]:
                            lines.append(f"  - COLUMN: {col['column']}")
                            lines.append(f"    EXPRESSION: {col['expression']}")

                    blocks.append("\n".join(lines))

                return "\n\n".join(blocks)

            def format_storage_integrations_for_cortex(storage_integrations: dict) -> str:
                blocks = []
                for name, props in storage_integrations.items():
                    lines = [
                        "OBJECT_TYPE: STORAGE_INTEGRATION",
                        f"NAME: {name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_notification_integrations_for_cortex(notification_integrations: dict) -> str:
                blocks = []
                for name, props in notification_integrations.items():
                    lines = [
                        "OBJECT_TYPE: NOTIFICATION_INTEGRATION",
                        f"NAME: {name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_streams_for_cortex(streams: dict) -> str:
                blocks = []
                for (db, schema, stream_name), props in streams.items():
                    lines = [
                        "OBJECT_TYPE: STREAM",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {stream_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            def format_tasks_for_cortex(tasks: dict) -> str:
                EXCLUDED_PROPERTIES = {"ENABLED", "AUTO_RESUME_ENV"}
                blocks = []
                for (db, schema, task_name), props in tasks.items():
                    filtered_props = {
                        prop: val
                        for prop, val in props.items()
                        if prop not in EXCLUDED_PROPERTIES
                    }
                    if not filtered_props:
                        continue  # nothing to create
                    lines = [
                        "OBJECT_TYPE: TASK",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {task_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in filtered_props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)
        
            def format_snowpipes_for_cortex(snowpipes: dict) -> str:
                blocks = []
                for (db, schema, pipe_name), props in snowpipes.items():
                    lines = [
                        "OBJECT_TYPE: SNOWPIPE",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {pipe_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)  
        
            def format_task_resume_for_cortex(tasks: dict) -> str:
                RESUME_PROPERTIES = {"ENABLED", "AUTO_RESUME_ENV"}
                blocks = []
                for (db, schema, task_name), props in tasks.items():
                    filtered_props = {
                        prop: val
                        for prop, val in props.items()
                        if prop in RESUME_PROPERTIES
                    }
                    if not filtered_props:
                        continue  # task not resumable
                    lines = [
                        "OBJECT_TYPE: TASK",
                        f"DATABASE: {db}",
                        f"SCHEMA: {schema}",
                        f"NAME: {task_name}",
                        "PROPERTIES:"
                    ]
                    for prop, val in filtered_props.items():
                        lines.append(f"  - {prop}: {val}")
                    blocks.append("\n".join(lines))
                return "\n\n".join(blocks)

            # FUNCTION OUTPUT
            database_metadata_str = format_databases_for_cortex(databases)
            schema_metadata_str = format_schemas_for_cortex(schemas)
            stage_metadata_str = format_stages_for_cortex(stages)
            file_format_metadata_str = format_file_formats_for_cortex(file_formats)
            table_metadata_str = format_tables_for_cortex(tables)
            column_metadata_str = format_columns_for_cortex(columns)
            warehouse_metadata_str = format_warehouses_for_cortex(warehouses)
            resource_monitor_metadata_str = format_resource_monitors_for_cortex(resource_monitors)
            copy_metadata_str = format_copy_commands_for_cortex(copy_cmds) 
            storage_metadata_str = format_storage_integrations_for_cortex(storage_integrations)
            notification_metadata_str = format_notification_integrations_for_cortex(notification_integrations)
            stream_metadata_str = format_streams_for_cortex(streams)
            task_metadata_str = format_tasks_for_cortex(tasks)
            snowpipe_metadata_str = format_snowpipes_for_cortex(snowpipes)
            alter_task_metadata_str = format_task_resume_for_cortex(tasks)

            
            generation_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

        
            # FUNCTION to dynamicall create prompt 
            def build_prompt(object_type: str, metadata: str) -> str:
                """
                Build a prompt for Snowflake DDL generation.
                
                Args:
                    object_type: Type of Snowflake object (e.g., 'TABLE', 'VIEW', 'FILE FORMAT')
                    metadata: JSON or string containing object metadata
                    gen_timestamp: Timestamp when the DDL is being generated
                    additional_context: Optional additional context (e.g., COPY_COMMAND definitions)
                
                Returns:
                    Formatted prompt string
                """
                return f"""
            
            You are a Snowflake DDL generator. Your ONLY task is to generate executable SQL DDL statements.

                STRICT OUTPUT REQUIREMENTS:
                1. Generate ONLY the objects explicitly defined in the metadata - NO additional objects
                2. Generate each object EXACTLY ONCE - NO duplicates
                3. Use FULLY QUALIFIED NAMES (database.schema.object_name) for ALL objects Except account level objects
                4. Include a formatted header block at the top of the file
                5. Output ONLY valid Snowflake SQL - NO markdown, NO explanations, NO comments except the header

                HEADER BLOCK FORMAT (include ONCE at the top of the file):
                /*
                ==============================================================================
                OBJECT TYPE: {object_type}
                GENERATED: {generation_timestamp}
                SOURCE: Automated deployment from metadata
                DESCRIPTION: DDL statements for {object_type} objects
                ==============================================================================
                */

                DDL GENERATION RULES:
                1. ALWAYS use fully qualified names: DATABASE_NAME.SCHEMA_NAME.OBJECT_NAME
                2. Extract database and schema from each objects metadata - NEVER assume defaults
                3. ALWAYS use CREATE IF NOT EXISTS for ALL object types
                4. Format properties with one property per line, properly indented
                5. Include COMMENT clauses when comment field exists in metadata
                6. Maintain dependency order: databases → schemas → objects
                7. Separate each CREATE statement with a blank line for readability

                OBJECT-SPECIFIC RULES:

                For TASKS and SNOWPIPES with COPY operations:
                - If COPY_REF field exists in metadata, locate the matching COPY_COMMAND in ADDITIONAL CONTEXT
                - Match COPY_COMMAND where TARGET_TABLE = COPY_REF value
                - Construct the COPY INTO statement from the COPY_COMMAND metadata
                - Embed COPY INTO directly in the CREATE statement:
                * CREATE TASK IF NOT EXISTS [fully_qualified_name] AS COPY INTO ...
                * CREATE PIPE IF NOT EXISTS [fully_qualified_name] AS COPY INTO ...
                - DO NOT generate standalone COPY INTO statements

                For TABLES:
                - Use CREATE TABLE IF NOT EXISTS
                - Include all columns with data types
                - Include constraints (PRIMARY KEY, FOREIGN KEY, UNIQUE, NOT NULL)
                - Include clustering keys if specified
                - Include retention time if specified

                For VIEWS:
                - Use CREATE VIEW IF NOT EXISTS
                - Include the full SQL definition from metadata

                For STREAMS:
                - Use CREATE STREAM IF NOT EXISTS
                - Specify the source table with fully qualified name
                - Include stream type (STANDARD, APPEND_ONLY, INSERT_ONLY)

                For FILE FORMATS, STAGES, SEQUENCES, etc.:
                - Use CREATE [OBJECT_TYPE] IF NOT EXISTS
                - Extract database and schema from each objects metadata
                - Each object must have its own fully qualified name

                For TASK RESUME operations:
                - Generate ONLY ALTER TASK statements wrapped in Jinja conditionals.
                - Use fully qualified task names in the format:
                DATABASE.SCHEMA.TASK_NAME
                syntax: ALTER TASK <task_name> RESUME
                - A task is eligible for resume ONLY if:
                - Property ENABLED = TRUE
                - Property AUTO_RESUME_ENV exists
        
                - AUTO_RESUME_ENV contains one or more comma-separated environment names
                (for example: DEV,QA,INT).
        
                - Generate Jinja logic that:
                - Checks whether the schemachange variable `env` is defined
                - Checks whether `env` is present in AUTO_RESUME_ENV
                - Executes ALTER TASK … RESUME only when the condition is satisfied
        
                - Do NOT resolve or substitute the environment value directly.
                - Do NOT hardcode environment names outside Jinja.
                - Do NOT generate ALTER TASK statements without Jinja guards.
                - Do NOT generate CREATE TASK or SUSPEND statements.
                - Do NOT include comments or explanations.
                - Output only executable Snowflake SQL with Jinja templating.

                VALIDATION CHECKLIST (verify before output):
                ☑ Single header block at top of file
                ☑ All object names are fully qualified (database.schema.object)
                ☑ ALL CREATE statements use IF NOT EXISTS
                ☑ Only objects from metadata are generated (count matches metadata entries)
                ☑ No duplicate objects
                ☑ No markdown formatting (```, ``sql, etc.)
                ☑ No explanatory text
                ☑ Valid Snowflake SQL syntax
                ☑ Each CREATE statement separated by blank line

                METADATA: {metadata}

                Generate the DDL now. Output ONLY the SQL with a single header block followed by all CREATE statements for all objects and ALTER statements only for Resume task."""

            # LOOP through different object types and metadata 

            def add_if_present(metadata_map: dict, key: str, primary_metadata: str, additional_metadata: str = ""):
                """Add metadata to map only if primary metadata is not empty."""
                if primary_metadata.strip():
                    if additional_metadata.strip():
                        metadata_map[key] = primary_metadata + "\n\nADDITIONAL CONTEXT:\n" + additional_metadata
                    else:
                        metadata_map[key] = primary_metadata

            object_metadata_map = {}

            # Simple objects
            add_if_present(object_metadata_map, "RESOURCE_MONITORS", resource_monitor_metadata_str)
            add_if_present(object_metadata_map, "WAREHOUSES", warehouse_metadata_str)
            add_if_present(object_metadata_map, "DATABASES", database_metadata_str)
            add_if_present(object_metadata_map, "SCHEMAS", schema_metadata_str)
            add_if_present(object_metadata_map, "STORAGE_INTEGRATIONS", storage_metadata_str)
            add_if_present(object_metadata_map, "NOTIFICATION_INTEGRATIONS", notification_metadata_str)
            add_if_present(object_metadata_map, "FILE_FORMATS", file_format_metadata_str)
            add_if_present(object_metadata_map, "STAGES", stage_metadata_str)
            add_if_present(object_metadata_map, "STREAMS", stream_metadata_str)

            # Combined objects
            add_if_present(object_metadata_map, "TABLES_AND_COLUMNS", table_metadata_str, column_metadata_str)
            add_if_present(object_metadata_map, "TASKS", task_metadata_str, copy_metadata_str)
            add_if_present(object_metadata_map, "SNOWPIPES", snowpipe_metadata_str, copy_metadata_str)
            add_if_present(object_metadata_map, "ALTER_TASK",alter_task_metadata_str)

            file_order_map = {
                "RESOURCE_MONITORS": "R__001__resource_monitors.sql",
                "WAREHOUSES": "R__002__warehouses.sql",
                "DATABASES": "R__003__databases.sql",
                "SCHEMAS": "R__004__schemas.sql",
                "STORAGE_INTEGRATIONS": "R__005__storage_integrations.sql",
                "NOTIFICATION_INTEGRATIONS": "R__006__notification_integrations.sql",
                "FILE_FORMATS": "R__007__file_formats.sql",
                "STAGES": "R__008__stages.sql",
                "TABLES_AND_COLUMNS": "R__009__tables.sql",
                "STREAMS": "R__010__streams.sql",
                "TASKS": "R__011__tasks.sql",
                "SNOWPIPES": "R__012__snowpipes.sql",
                "ALTER_TASK" : "R__013__altertask.sql"
            }

            os.makedirs("ddls", exist_ok=True)

            for obj_type, metadata in object_metadata_map.items():
                if not metadata.strip():
                    continue  # Skip empty ones

                datatype_prompt = build_prompt(obj_type, metadata)
                escaped_prompt = datatype_prompt.replace("'", "''")

                # print (datatype_prompt)

                sql = f"""
                    SELECT SNOWFLAKE.CORTEX.COMPLETE(
                        'claude-4-sonnet',
                        '{escaped_prompt}'
                ) AS response; 
                    """
                # result_text = result.get("response") if isinstance(result, dict) else str(result)

                df = session.sql(sql)
                result = df.collect()
                sql_part = result[0]["RESPONSE"]
                
                file_name = file_order_map[obj_type]
                print("File Name: ", file_name)
                file_path = f"ddls/{file_name}"

                commit_message = f"Auto commit - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(sql_part)
        
                result = push_file_to_github(
                    token = st.session_state.github_pat,
                    owner = st.session_state.github_user,
                    repo = st.session_state.github_repo,
                    branch = st.session_state.github_branch,
                    file_path = file_path,
                    content = sql_part,
                    message = commit_message
                )
                # st.write(result)

                # print(f"✅ Generated {file_path}")
                # st.write(f"✅ Generated {file_path}")

                # Determine GitHub push status
                if result.status_code in [200, 201]:
                    github_status = "✅ Pushed"
                    st.success(f"✅ Generated and pushed {file_path}")
                else:
                    github_status = f"❌ Push failed: {result.status_code}"
                    st.error(f"❌ Failed to push {file_path}: {result.status_code}")

                # **ADD THIS: Save to session state for tracking and downloads**
                st.session_state.generated_scripts.append({
                    "name": file_name,
                    "type": obj_type,
                    "content": sql_part,
                    "file_path": file_path,
                    "github_status": github_status,
                    "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

            print("Process Completed")

    
    # Display Generated Scripts
    if st.session_state.generated_scripts:
        st.markdown("---")
        st.markdown("### 📝 Generated DDL Scripts")
        
        for idx, script in enumerate(st.session_state.generated_scripts):
            with st.expander(f"📄 {script['name']} ({script['type']}) - {script.get('github_status', '')}"):
                st.code(script['content'], language="sql")
                
                st.download_button(
                    label=f"💾 Download {script['name']}",
                    data=script['content'],
                    file_name=script['name'],
                    mime="text/plain",
                    key=f"download_{idx}",
                    use_container_width=True
                )

with col2:
    st.markdown("### 📊 Generation Summary")
    
    if st.session_state.metadata_uploaded:
        st.metric("Metadata File", "✅ Uploaded")
    else:
        st.metric("Metadata File", "⏳ Pending")
    
    if st.session_state.generated_scripts:
        st.metric("Scripts Generated", len(st.session_state.generated_scripts))
        
        # Count by type
        script_types = {}
        for script in st.session_state.generated_scripts:
            script_types[script['type']] = script_types.get(script['type'], 0) + 1
        
        st.markdown("**Scripts by Type:**")
        for script_type, count in script_types.items():
            st.write(f"• {script_type}: {count}")
        
        # GitHub push status
        st.markdown("---")
        st.markdown("**GitHub Push Status:**")
        success_count = sum(1 for s in st.session_state.generated_scripts if "✅" in s.get('github_status', ''))
        st.write(f"✅ Successfully pushed: {success_count}")
        st.write(f"❌ Failed: {len(st.session_state.generated_scripts) - success_count}")
    else:
        st.metric("Scripts Generated", "0")
    
    st.markdown("---")
    
    # Download All Scripts
    if st.session_state.generated_scripts:
        st.markdown("### 💾 Download Options")
        
        # Create ZIP file
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for script in st.session_state.generated_scripts:
                zip_file.writestr(script['name'], script['content'])
        
        st.download_button(
            label="📥 Download All Scripts (ZIP)",
            data=zip_buffer.getvalue(),
            file_name=f"ddl_scripts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
            mime="application/zip",
            use_container_width=True
        )
    
    st.markdown("---")
    
    # Configuration Status
    st.markdown("### ⚙️ Configuration Status")
    
    if st.session_state.github_connected:
        st.write("✅ GitHub Connection")
        st.caption(f"Owner: {st.session_state.get('github_owner', 'N/A')}")
        st.caption(f"Repo: {st.session_state.get('github_repo_name', 'N/A')}")
    else:
        st.write("⚠️ GitHub Connection")
    
    # Check Snowflake connection
    conn_test = session
    if conn_test:
        st.write("✅ Snowflake Connection")
        try:
            session.sql("SELECT 1").collect()
            st.success("✅ Snowflake connection is active")
        except Exception as e:
            st.error("⚠️ Snowflake connection failed")
            st.exception(e)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; padding: 1rem;'>
    <p>DDL Generator v1.0 | Healthcare Analytics Platform</p>
</div>
""", unsafe_allow_html=True)
