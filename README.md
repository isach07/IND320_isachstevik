# IND320_isachstevik
Project work for IND320 (Data to Decision) at NMBU. The project explores NVE's weekly
reservoir statistics and ENTSO-E cross-border electricity flows for Norway.

## Run locally
    uv sync
    uv run streamlit run app.py

## Secrets
The app and notebook read secrets from `.streamlit/secrets.toml` (not in the repo):

    [mongo]
    uri = "mongodb+srv://..."

    [entsoe]
    token = "..."   # only needed by the notebook