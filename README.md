# HawkEye - Database Monitoring Dashboard (Only Oracle 12c+ Supported for now)

HawkEye is a modern, real-time database monitoring application designed to provide crucial insights into your Oracle database. Featuring an intuitive web-based dashboard built on Python, Flask, and the modern `oracledb` python driver, HawkEye helps database administrators monitor queries, sessions, workloads, and targets smoothly in real-time.

## Features

- **Modern & Real-Time Setup**: Monitor top SQL activity, workload profiles, tablespace usages, and active sessions.
- **Oracle Tuning Advisor Integration**: Easily select a date range (From Date & Till Date) to execute the DB Tuning Advisor and generate SQL reports directly from the UI.
- **Cross-Database Target Support**: Add, update, configure, and monitor multiple target databases from a unified panel.
- **Role-Based Access**: Manage active viewers and grant detailed administrator permissions to other database specialists via local store mechanism securely.
- **Detailed Error Handling & Modal Support**: Sleek inline error handlers and action confirmations built natively without needing to navigate away from context. 

<img width="1137" height="769" alt="image" src="https://github.com/user-attachments/assets/a2c36afb-01d9-4186-9c0d-a8b7466e4884" />


## Requirements

- Python 3.12+
- Packages detailed in `requirements.txt` (`Flask`, `oracledb`, `pygal`, `plotly`, `Werkzeug`, `Jinja2`, `cryptography`)

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
