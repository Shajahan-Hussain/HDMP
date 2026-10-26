import streamlit as st
from datetime import datetime
import pandas as pd
from snowflake.snowpark.context import get_active_session

session = get_active_session()

# Page configuration
st.set_page_config(
    page_title="dbt Project Creator - Healthcare Platform",
    page_icon="🔄",
    layout="wide",
    initial_sidebar_state="expanded"
)

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
    .warning-box {
        padding: 1rem;
        border-radius: 5px;
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        margin: 1rem 0;
    }
    .success-box {
        padding: 1rem;
        border-radius: 5px;
        background-color: #d4edda;
        border-left: 5px solid #28a745;
        margin: 1rem 0;
    }
    </style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">🔄 dbt Project Creator</div>', unsafe_allow_html=True)

st.markdown("""
<div class="info-box">
Create and deploy dbt projects in Snowflake with GitHub integration, scheduled tasks, and automated workflows.
</div>
""", unsafe_allow_html=True)

# Initialize session state
if 'dbt_ddl_generated' not in st.session_state:
    st.session_state.dbt_ddl_generated = False
if 'generated_dbt_ddl' not in st.session_state:
    st.session_state.generated_dbt_ddl = None
if 'dbt_config' not in st.session_state:
    st.session_state.dbt_config = {}

# Main layout
col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("### 🎯 Create dbt Project and Tasks")
    
    with st.expander("⚙️ Configure dbt Project", expanded=not st.session_state.dbt_ddl_generated):
        st.markdown("#### 📋 GitHub Repository Configuration")
        
        github_uri = st.text_input(
            "GitHub Repository URI",
            placeholder="https://github.com/your-org/dbt-healthcare",
            help="Full URL to your dbt project GitHub repository",
            key="github_uri"
        )
        
        col_branch, col_path = st.columns(2)
        
        with col_branch:
            github_branch = st.text_input(
                "Branch Name",
                value="main",
                placeholder="main",
                help="Git branch to use for dbt project",
                key="github_branch"
            )
        
        with col_path:
            dbt_project_path = st.text_input(
                "dbt Project Path (Optional)",
                placeholder="dbt/",
                help="Path to dbt project within the repository",
                key="dbt_path"
            )
        
        st.markdown("---")
        
        st.markdown("#### 🔐 Snowflake Authentication")
        
        col_secret, col_api, col_external_access = st.columns(3)
        
        with col_secret:
            snowflake_secret = st.text_input(
                "Snowflake Secret Name",
                placeholder="DBT_GIT_SECRET",
                help="Name of the secret containing Git credentials (username/PAT)",
                key="sf_secret"
            )
        
        with col_api:
            api_integration = st.text_input(
                "API Integration Name",
                placeholder="DBT_GIT_INTEGRATION",
                help="Name of the API integration for Git access",
                key="api_integration"
            )

        with col_external_access:
            external_access_integration = st.text_input(
                "External Access Integration Name",
                placeholder = "",
                help = "Name of the External Access Integration for Git Access",
                key = "external_access_integration"
            )
        
        st.markdown("---")
        
        st.markdown("#### 📦 dbt Project Configuration")
        
        col_repo_name, col_project_name = st.columns(2)
        
        with col_repo_name:
            git_repo_name = st.text_input(
                "Git Repository Object Name",
                placeholder="DBT_HEALTHCARE_REPO",
                help="Name for the Snowflake Git Repository object",
                key="git_repo_name"
            )
        
        with col_project_name:
            dbt_project_name = st.text_input(
                "dbt Project Object Name",
                placeholder="DBT_HEALTHCARE_PROJECT",
                help="Name for the Snowflake dbt Project object",
                key="dbt_project_name"
            )
        
        st.markdown("---")
        
        st.markdown("#### ⏰ Task Scheduling Configuration")
        
        task_name = st.text_input(
            "Task Name",
            placeholder="DBT_HEALTHCARE_DAILY_RUN",
            help="Name for the scheduled task that will run dbt",
            key="task_name"
        )
        
        col_schedule, col_warehouse = st.columns(2)
        
        with col_schedule:
            task_schedule = st.text_input(
                "Task Schedule (CRON)",
                value="0 2 * * *",
                placeholder="0 2 * * *",
                help="CRON expression (e.g., '0 2 * * *' = daily at 2 AM)",
                key="task_schedule"
            )
        
        with col_warehouse:
            task_warehouse = st.text_input(
                "Warehouse for Task",
                placeholder="COMPUTE_WH",
                help="Warehouse to use for running dbt tasks",
                key="task_warehouse"
            )
        
        dbt_command = st.text_input(
            "dbt Command",
            value="run --select silver --target dev",
            placeholder="run --select silver --target dev",
            help="dbt command to execute (e.g., 'dbt run', 'dbt test', 'dbt build')",
            key="dbt_command"
        )
        
        st.markdown("---")
        
        # Validation and Generate Button
        generate_disabled = not all([
            github_uri,
            snowflake_secret,
            api_integration,
            git_repo_name,
            dbt_project_name,
            task_name,
            task_warehouse
        ])
        
        if generate_disabled:
            st.markdown("""
            <div class="warning-box">
            ⚠️ <strong>Please fill in all required fields to generate DDL scripts.</strong>
            </div>
            """, unsafe_allow_html=True)
        
        if st.button("🔨 Generate DDL Scripts", type="primary", disabled=generate_disabled, use_container_width=True):
            # Store configuration
            st.session_state.dbt_config = {
                'github_uri': github_uri,
                'github_branch': github_branch,
                'dbt_project_path': dbt_project_path,
                'snowflake_secret': snowflake_secret,
                'api_integration': api_integration,
                'git_repo_name': git_repo_name,
                'dbt_project_name': dbt_project_name,
                'task_name': task_name,
                'task_schedule': task_schedule,
                'task_warehouse': task_warehouse,
                'dbt_command': dbt_command
            }
            
            # Generate DDL
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Construct full dbt path
            if dbt_project_path:
                full_dbt_path = f"branches/{github_branch}/{dbt_project_path.rstrip('/')}"
            else:
                full_dbt_path = f"branches/{github_branch}"
            
            ddl_script = f"""-- ========================================================================
-- dbt Project and Task DDL Script
-- Generated: {timestamp}
-- ========================================================================

-- ========================================================================
-- 1. CREATE GIT REPOSITORY
-- ========================================================================
-- This creates a Git repository object in Snowflake that references your
-- dbt project repository.

CREATE OR REPLACE GIT REPOSITORY {git_repo_name}
  API_INTEGRATION = {api_integration}
  GIT_CREDENTIALS = {snowflake_secret}
  ORIGIN = '{github_uri}';

-- Fetch the latest code from the repository
ALTER GIT REPOSITORY {git_repo_name} FETCH;

-- Verify repository is created
SHOW GIT REPOSITORIES LIKE '{git_repo_name}';

-- List files in the repository
LS @{git_repo_name}/{full_dbt_path};

-- ========================================================================
-- 2. CREATE DBT PROJECT
-- ========================================================================
-- This creates a dbt project object that references the Git repository.

CREATE SCHEMA IF NOT EXISTS EHDP.LOGS;

CREATE OR REPLACE DBT PROJECT {dbt_project_name}
FROM @{git_repo_name}/{full_dbt_path}
EXTERNAL_ACCESS_INTEGRATIONS = ('{external_access_integration}');


-- ========================================================================
-- 3. CREATE SCHEDULED TASK
-- ========================================================================
-- This creates a task that will execute the dbt project on a schedule.

-- EXECUTE DBT PROJECT {dbt_project_name} args = 'run --select dbt_artifacts';

CREATE OR REPLACE TASK {task_name}
  WAREHOUSE = {task_warehouse}
  SCHEDULE = 'USING CRON {task_schedule} UTC'
  COMMENT = 'Automated dbt run task - Generated on {timestamp}'
AS
  EXECUTE DBT PROJECT {dbt_project_name} args = '{dbt_command}';


CREATE OR REPLACE TASK {task_name}_intermediate
    WAREHOUSE = {task_warehouse}
    AFTER {task_name}
AS
    EXECUTE DBT PROJECT {dbt_project_name} args = 'run --select intermediate --target dev';
    
CREATE OR REPLACE TASK {task_name}_gold
    WAREHOUSE = {task_warehouse}
    AFTER {task_name}_intermediate
AS
    EXECUTE DBT PROJECT {dbt_project_name} args = 'run --select gold --target dev';

-- Resume the tasks to enable scheduling
ALTER TASK {task_name}_gold RESUME;
ALTER TASK {task_name}_intermediate RESUME;
ALTER TASK {task_name} RESUME;

-- View task history
-- SELECT *
-- FROM TABLE(INFORMATION_SCHEMA.TASK_HISTORY())
-- WHERE NAME = '{task_name}'
-- ORDER BY SCHEDULED_TIME DESC
-- LIMIT 10;

-- ========================================================================
-- ADDITIONAL COMMANDS
-- ========================================================================

-- To manually execute the task immediately:
-- EXECUTE TASK {task_name};

-- To suspend the task:
-- ALTER TASK {task_name} SUSPEND;

-- To drop objects (in reverse order):
-- DROP TASK IF EXISTS {task_name};
-- DROP DBT PROJECT IF EXISTS {dbt_project_name};
-- DROP GIT REPOSITORY IF EXISTS {git_repo_name};

-- To view dbt project details:
-- DESC DBT PROJECT {dbt_project_name};

-- ========================================================================
-- PREREQUISITES CHECKLIST
-- ========================================================================
-- ✓ API Integration '{api_integration}' must exist
-- ✓ Secret '{snowflake_secret}' must exist with Git credentials
-- ✓ Warehouse '{task_warehouse}' must exist
-- ✓ User must have OWNERSHIP privilege on the database/schema
-- ✓ User must have CREATE GIT REPOSITORY, CREATE DBT PROJECT privileges
-- ✓ User must have CREATE TASK, EXECUTE TASK privileges
-- ========================================================================
"""
            
            st.session_state.generated_dbt_ddl = ddl_script
            st.session_state.dbt_ddl_generated = True
            st.rerun()
    
    # Display after generation
    if st.session_state.dbt_ddl_generated and st.session_state.generated_dbt_ddl:
        st.markdown("---")
        st.markdown("### 📄 Generated DDL Script")
        
        st.code(st.session_state.generated_dbt_ddl, language="sql")
        
        st.markdown("---")
        st.markdown("### 🚀 Deployment Options")
        
        col_download, col_deploy = st.columns(2)
        
        with col_download:
            st.download_button(
                label="📥 Download SQL File",
                data=st.session_state.generated_dbt_ddl,
                file_name=f"dbt_project_ddl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql",
                mime="text/sql",
                use_container_width=True,
                type="secondary"
            )
        
        with col_deploy:
            if st.button("🚀 Deploy to Snowflake", type="primary", use_container_width=True):
                st.session_state.show_deploy_config = True
        
        # Deploy Configuration
        if st.session_state.get('show_deploy_config', False):
            st.markdown("---")
            st.markdown("### ⚙️ Deployment Configuration")
            
            with st.form("deployment_form"):
                st.markdown("**Select Target Database and Schema:**")
                
                col_db, col_schema = st.columns(2)
                
                with col_db:
                    deploy_database = st.text_input(
                        "Database",
                        placeholder="DBT_PROD",
                        help="Database where objects will be created"
                    )
                
                with col_schema:
                    deploy_schema = st.text_input(
                        "Schema",
                        placeholder="DBT_PROJECTS",
                        help="Schema where objects will be created"
                    )
                
                st.markdown("---")
                
                col_submit, col_cancel = st.columns(2)
                
                with col_submit:
                    deploy_submit = st.form_submit_button(
                        "✅ Execute Deployment",
                        use_container_width=True,
                        type="primary"
                    )
                
                with col_cancel:
                    deploy_cancel = st.form_submit_button(
                        "❌ Cancel",
                        use_container_width=True
                    )
                
                if deploy_cancel:
                    st.session_state.show_deploy_config = False
                    st.rerun()
                
                if deploy_submit:
                    if not deploy_database or not deploy_schema:
                        st.error("❌ Please provide both database and schema")
                    else:
                        with st.spinner("Deploying to Snowflake..."):
                            try:
                                ddl_script = st.session_state.generated_dbt_ddl

                                config = st.session_state.dbt_config
                                git_repo_name = config['git_repo_name']
                                dbt_project_name = config['dbt_project_name']
                                task_name = config['task_name']

                                # Fully qualify object names with database.schema                       
                                ddl_script = ddl_script.replace(
                                    f"CREATE OR REPLACE DBT PROJECT {dbt_project_name}",
                                    f"CREATE OR REPLACE DBT PROJECT {deploy_database}.{deploy_schema}.{dbt_project_name}"
                                )

                                ddl_script = ddl_script.replace(
                                    f"CREATE OR REPLACE TASK {task_name}",
                                    f"CREATE OR REPLACE TASK {deploy_database}.{deploy_schema}.{task_name}"
                                )
                        
                                ddl_script = ddl_script.replace(
                                    f"ALTER TASK {task_name}",
                                    f"ALTER TASK {deploy_database}.{deploy_schema}.{task_name}"
                                )

                                ddl_script = ddl_script.replace(
                                    f"AFTER {task_name}",
                                    f"AFTER {deploy_database}.{deploy_schema}.{task_name}"
                                )

                                ddl_script = ddl_script.replace(
                                    f"AFTER {task_name}_intermediate",
                                    f"AFTER {deploy_database}.{deploy_schema}.{task_name}_intermediate"
                                )

                                ddl_script = ddl_script.replace(
                                    f"EXECUTE DBT PROJECT {dbt_project_name}",
                                    f"EXECUTE DBT PROJECT {deploy_database}.{deploy_schema}.{dbt_project_name}"
                                )

                                
                                # Split and execute each statement
                                statements = ddl_script.split(';')
                                st.write(statements)
                                
                                results = []
                                for idx, statement in enumerate(statements):
                                    statement = statement.strip()
                                    
                                    # remove comment lines before executing
                                    lines = [l for l in statement.split('\n') if not l.strip().startswith('--')]
                                    statement = '\n'.join(lines).strip()
                                    
                                    if not statement:
                                        continue
                                    
                                    try:
                                        # Execute statement
                                        session.sql(statement).collect()
                                        results.append({
                                            'statement_num': idx + 1,
                                            'status': '✅ Success',
                                            'statement': statement[:100] + '...' if len(statement) > 100 else statement
                                        })
                                    except Exception as e:
                                        results.append({
                                            'statement_num': idx + 1,
                                            'status': f'❌ Failed',
                                            'statement': statement[:100] + '...' if len(statement) > 100 else statement,
                                            'error': str(e)
                                        })
                                
                                # Display results
                                st.markdown("### 📊 Deployment Results")
                                
                                results_df = pd.DataFrame(results)
                                st.dataframe(results_df, use_container_width=True, hide_index=True)
                                
                                success_count = sum(1 for r in results if r['status'] == '✅ Success')
                                
                                if success_count == len(results):
                                    st.markdown(f"""
                                    <div class="success-box">
                                    ✅ <strong>Deployment Successful!</strong><br>
                                    All {len(results)} statements executed successfully in {deploy_database}.{deploy_schema}
                                    </div>
                                    """, unsafe_allow_html=True)
                                elif success_count > 0:
                                    st.warning(f"⚠️ Partial Success: {success_count}/{len(results)} statements executed")
                                else:
                                    st.error("❌ Deployment failed")
                                
                                st.session_state.show_deploy_config = False
                                
                            except Exception as e:
                                st.error(f"❌ Deployment failed: {str(e)}")

with col2:
    st.markdown("### 📊 Configuration Summary")
    
    if st.session_state.dbt_ddl_generated and st.session_state.dbt_config:
        config = st.session_state.dbt_config
        
        st.markdown("#### 🔗 Git Configuration")
        st.info(f"""
**Repository:** {config['github_uri']}  
**Branch:** {config['github_branch']}  
**dbt Path:** {config.get('dbt_project_path', '(root)')}
        """)
        
        st.markdown("#### 🔐 Authentication")
        st.info(f"""
**Secret:** {config['snowflake_secret']}  
**API Integration:** {config['api_integration']}
        """)
        
        st.markdown("#### 📦 Snowflake Objects")
        st.info(f"""
**Git Repo:** {config['git_repo_name']}  
**dbt Project:** {config['dbt_project_name']}  
**Task:** {config['task_name']}
        """)
        
        st.markdown("#### ⏰ Scheduling")
        st.info(f"""
**Schedule:** {config['task_schedule']}  
**Warehouse:** {config['task_warehouse']}  
**Command:** {config['dbt_command']}
        """)
        
        st.markdown("---")
        
        st.markdown("### ✅ Prerequisites")
        
        prerequisites = [
            f"API Integration: {config['api_integration']}",
            f"Secret: {config['snowflake_secret']}",
            f"Warehouse: {config['task_warehouse']}",
            "CREATE GIT REPOSITORY privilege",
            "CREATE DBT PROJECT privilege",
            "CREATE TASK privilege"
        ]
        
        for prereq in prerequisites:
            st.markdown(f"• {prereq}")
        
    else:
        st.info("""
        👈 Configure your dbt project from the left panel.
        
        The configuration summary will appear here after you fill in the required fields.
        """)
        
        st.markdown("---")
        
        st.markdown("### 💡 Quick Guide")
        
        with st.expander("1️⃣ Prepare Credentials"):
            st.markdown("""
**Create Git Secret:**
```sql
CREATE SECRET git_secret
  TYPE = PASSWORD
  USERNAME = 'your-github-username'
  PASSWORD = 'your-personal-access-token';
```

**Create API Integration:**
```sql
CREATE API INTEGRATION git_integration
  API_PROVIDER = GIT_HTTPS_API
  API_ALLOWED_PREFIXES = ('https://github.com/your-org/')
  ENABLED = TRUE;
```
            """)
        
        with st.expander("2️⃣ Configure Settings"):
            st.markdown("""
Fill in all required fields:
- GitHub repository URL
- Branch name (usually 'main' or 'master')
- Secret name (from step 1)
- API integration name (from step 1)
- Object names for Snowflake
- Task schedule (CRON format)
- Warehouse to use
            """)
        
        with st.expander("3️⃣ Generate & Deploy"):
            st.markdown("""
**Generate DDL:**
1. Click "Generate DDL Scripts"
2. Review the generated SQL

**Option A - Download:**
- Download SQL file
- Review and customize
- Execute manually in Snowflake

**Option B - Deploy:**
- Click "Deploy to Snowflake"
- Select database and schema
- Execute automatically
- Review results
            """)

# Footer
st.markdown("---")
st.markdown("""
<div style='text-align: center; color: #666; padding: 1rem;'>
    <p>dbt Project Creator v1.0 | Healthcare Analytics Platform</p>
</div>
""", unsafe_allow_html=True)