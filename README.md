# HawkEye - Database Monitoring Dashboard (Only Oracle 12c+ Supported for now)

HawkEye is a real-time database monitoring application for Oracle and PostgreSQL targets. Built on Python and Flask, it keeps engine-specific adapters and features separated while sharing authentication, target management, and common UI components.

Database-independent routes, utilities, and templates are shared. Database-specific adapters, routes, and feature templates live under `app/database/<engine>/`; the Oracle adapter preserves the existing Oracle feature set. Existing target records are migrated with `database_type='oracle'`. When registering a target, select Oracle or PostgreSQL and provide that engine's connection details; HawkEye validates the selected connection before saving. PostgreSQL targets provide a connection summary, a Top Activity dashboard with five-second activity charts, Top SQL and Top Wait Events summaries, a Session Monitor with state filtering, and a SQL Monitor for active queries. Administrators can terminate PostgreSQL sessions from either monitor. PostgreSQL monitoring features will be added incrementally, and unsupported Oracle-specific routes are disabled for PostgreSQL targets.

## Features

- **Modern & Real-Time Setup**: Monitor top SQL activity, workload profiles, tablespace usages, and active sessions.
- **Oracle Tuning Advisor Integration**: Select a date range to run the DB Tuning Advisor, view reports in the UI, and export reports as `.txt` files.
- **Cross-Database Target Support**: Add, update, configure, and monitor multiple target databases from a unified panel.
- **Role-Based Access**: Manage active viewers and grant detailed administrator permissions to other database specialists via local store mechanism securely.
- **Detailed Error Handling & Modal Support**: Sleek inline error handlers and action confirmations built natively without needing to navigate away from context. 

<img width="700" height="400" alt="image" src="https://github.com/user-attachments/assets/a2c36afb-01d9-4186-9c0d-a8b7466e4884" />
<img width="700" height="400" alt="image" src="https://github.com/user-attachments/assets/bc6bad68-dd0f-4a4f-bbdd-5c5f109ef418" />
<img width="700" height="400" alt="image" src="https://github.com/user-attachments/assets/70919c9f-d3a8-4c5e-a8e0-2d1801df7c75" />


## Requirements

- Python 3.12+
- Packages detailed in `requirements.txt` (`Flask`, `oracledb`, `psycopg`, `pygal`, `plotly`, `Werkzeug`, `Jinja2`, `cryptography`)

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/your-username/HawkEye.git
   cd HawkEye
   ```

2. **Create a virtual environment:**
   Using standard Python or `uv`:
   ```bash
   uv venv
   ```
   Or
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize Database Targets & Start Server:**
   Update your database target and user setup by logging onto the portal for the first time.
   
   Start the application:
   ```bash
   python run_server.py
   ```
   *Note: Optionally start using `uv` if preferred (`uv run python run_server.py`)*

5. **Open Browser:**
   Visit `http://0.0.0.0:5000/` or the specific mapped interface host in your browser. Default Admin setup usually takes you directly through the environment config layout.

## Testing

HawkEye utilizes `pytest` alongside `pytest-flask` for managing its testing framework accurately without manual intervention.

To execute tests:
```bash
export PYTHONPATH=$PYTHONPATH:$(pwd)
pytest tests/ -v
```

## Contributing 

Contributions, issue creations, and enhancements are highly welcome. HawkEye operates on ensuring direct SQL parsing limits are securely bounded and dashboard aesthetics maintain real-time feel via JS updates.

## License

Designed initially as an internal monitoring capability, HawkEye adheres to its standard GNU GPL/MIT/Apache specifications. Please review `LICENSE` for extended legal guidance.
