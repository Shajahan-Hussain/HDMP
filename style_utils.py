import streamlit as st


def apply_style():
    """Injects global CSS styling across all Streamlit pages."""
    st.markdown(
        """
        <style>
        /* Sidebar (light tone) */
        section[data-testid="stSidebar"] {
            background: linear-gradient(180deg, #E8EEFF 0%, #D6E4FF 100%) !important;
            color: #1A1A1A !important;
            font-family: 'Segoe UI', sans-serif !important;
            border-right: 1px solid #BFD2FF !important;
        }
        section[data-testid="stSidebar"] * {
            color: #1A1A1A !important;
        }

        /* Page container */
        [data-testid="stAppViewContainer"] {
            background-color: #F9FBFF !important;
            color: #1A1A1A !important;
            font-family: 'Segoe UI', sans-serif !important;
        }

        h1, h2, h3 {
            color: black !important;
            font-weight: 600 !important;
        }

        p, li {
            color: #2C2C2C !important;
            font-size: 16px !important;
        }

        /* Primary Action Button */
        .stButton > button {
            background-color: #D8E4FF !important; /* Soft Snowflake Blue */
            color: #1A1A1A !important;            /* Dark text for contrast */
            border: 1.5px solid #AFC7FF !important;
            border-radius: 6px !important;
            font-weight: 600 !important;
            box-shadow: 0px 2px 4px rgba(0,0,0,0.1) !important;
            transition: 0.3s ease-in-out;
        }

        /* Hover State */
        .stButton > button:hover {
            background-color: #C2D5FF !important; /* Slightly deeper blue */
            border-color: #8FB4FF !important;
        }

        /* Secondary Button (optional) */
        .stButton.secondary > button {
            background-color: #FFFFFF !important;
            color: #1F4FE0 !important;            /* Blue text */
            border: 1.5px solid #BFD2FF !important;
        }
        .stButton.secondary > button:hover {
            background-color: #F2F6FF !important;
            border-color: #A7C0FF !important;
        }

        .stTextInput > div > div > input,
        .stTextArea > div > div > textarea {
            color: #1A1A1A !important;
            background-color: white !important;
            border: 1px solid #C6C6C6 !important;
            border-radius: 4px !important;
        }

        .stAlert {
            border: 1px solid #B6C8FF !important;
            background-color: #E9EFFF !important;
            color: #1A1A1A !important;
        }

        .block-container {
            padding-top: 2.5rem !important;
            padding-bottom: 1rem !important;
        }

        img {
            display: inline-block !important;
            opacity: 1 !important;
        }

        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    """Displays the app header (logo + title)."""

    col1, col2 = st.columns([1, 6])
    with col1:
        st.markdown("<div style='padding-top: 20px;'></div>", unsafe_allow_html=True)
        try:
            st.image("assets/elait_health_no_bg.png",)
        except Exception:
            st.warning("Logo not found")
