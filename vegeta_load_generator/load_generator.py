from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import subprocess
import asyncio
from subprocess import CalledProcessError
import json
import sqlite3
from datetime import datetime
import logging

# Configuration
DB_PATH = "vegeta_results.db"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# Mount the static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Database Functions ---

def init_db():
    """Initializes the SQLite database and creates the necessary table."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vegeta_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                server_ip TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                duration_s INTEGER,
                requests INTEGER,
                success_rate REAL,
                latency_mean REAL,
                latency_p50 REAL,
                latency_p95 REAL,
                latency_p99 REAL,
                errors TEXT
            )
        """)
        conn.commit()
        conn.close()
        logging.info("SQLite database initialized successfully.")
    except Exception as e:
        logging.error(f"Error initializing database: {e}")


def insert_report(ip, report_data):
    """Inserts a successfully generated report into the database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Extract core metrics from the vegeta report JSON structure
        duration_ns = report_data.get("duration", 0)
        duration_s = duration_ns / 1_000_000_000 # Convert nanoseconds to seconds

        requests = report_data.get("requests", 0)
        success_rate = report_data.get("success", 0.0)
        
        # Latency metrics are in nanoseconds (ns), storing as ns for precision
        latencies = report_data.get("latencies", {})
        latency_mean = latencies.get("mean", 0.0)
        latency_p50 = latencies.get("50th", 0.0)
        latency_p95 = latencies.get("95th", 0.0)
        latency_p99 = latencies.get("99th", 0.0)
        
        # Errors (stored as a JSON string for simplicity)
        errors = json.dumps(report_data.get("errors", []))

        current_time = datetime.now().isoformat()

        cursor.execute("""
            INSERT INTO vegeta_reports 
            (server_ip, timestamp, duration_s, requests, success_rate, latency_mean, latency_p50, latency_p95, latency_p99, errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (ip, current_time, duration_s, requests, success_rate, latency_mean, latency_p50, latency_p95, latency_p99, errors))
        
        conn.commit()
        conn.close()
        logging.info(f"Report for {ip} successfully saved to database.")
    except Exception as e:
        logging.error(f"Error inserting report into database: {e}")
    finally:
        if conn:
            conn.close()

# Initialize the database when the application starts up
@app.on_event("startup")
def startup_event():
    init_db()


# --- API Endpoints ---

@app.get("/", response_class=HTMLResponse)
async def get_index():
    html_path = Path("static/index.html")
    # In a real environment, you'd check for file existence.
    # For this example, we assume static/index.html is created below.
    return html_path.read_text(encoding="utf-8")


def run_vegeta_task(server_ip: str) -> bool:
    """Runs the vegeta load test and attempts to save the report."""
    logging.info(f"Starting load test on {server_ip}...")
    try:
        command = f"echo 'GET {server_ip}' | vegeta attack -rate=100 -duration=10s | vegeta report -type=json"
        
        # Execute the command inside the Docker container
        result = subprocess.run(
            f'docker run --rm -i peterevans/vegeta sh -c "{command}"', 
            shell=True, 
            check=True, 
            capture_output=True,
            text=True
        )
        
        vegeta_output = result.stdout
        report = json.loads(vegeta_output)
        
        # Save the report to the SQLite database
        insert_report(server_ip, report)
        
        logging.info(f"Load test on {server_ip} completed and saved.")
        return True
    
    except CalledProcessError as e:
        logging.error(f"Vegeta Error for {server_ip}: {e.stderr.strip()}")
        return False
    except Exception as e:
        logging.error(f"General Error during test for {server_ip}: {e}")
        return False


@app.post("/hit")
async def record_hit(request: Request):
    data = await request.json()
    server_ip = data.get("server_ip")
    
    if not server_ip:
        return JSONResponse({"message": "Server IP is required"}, status_code=400)
    
    # Run the load test in a background thread to prevent blocking the FastAPI server
    asyncio.create_task(asyncio.to_thread(run_vegeta_task, server_ip))
    return JSONResponse({"message": f"Server {server_ip} load test started successfully in the background! Check reports shortly."}, status_code=202)


@app.get("/reports")
async def get_reports():
    """
    Fetches aggregated load test reports per server, 
    sorted by performance (Avg Success Rate DESC, then Avg P95 Latency ASC).
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row # Allows accessing columns by name
        cursor = conn.cursor()
        
        # Fetch aggregated metrics for ranking
        cursor.execute("""
            SELECT
                server_ip,
                COUNT(id) AS total_tests,
                SUM(requests) AS total_requests,
                AVG(success_rate) AS avg_success_rate,
                AVG(latency_mean) AS avg_latency_mean,
                AVG(latency_p95) AS avg_latency_p95
            FROM vegeta_reports
            GROUP BY server_ip
            -- Rank by performance: Highest success rate, then lowest P95 latency
            ORDER BY avg_success_rate DESC, avg_latency_p95 ASC
        """)
        rows = cursor.fetchall()
        
        # Convert rows to a list of dictionaries for JSON serialization
        reports = [dict(row) for row in rows]
        
        # Process data for display (convert ns to ms, 0.x to %)
        for report in reports:
            # Latencies: ns to ms (divide by 1,000,000) and round to 2 decimals
            report['avg_latency_mean_ms'] = round(report.pop('avg_latency_mean') / 1_000_000, 2)
            report['avg_latency_p95_ms'] = round(report.pop('avg_latency_p95') / 1_000_000, 2)
            
            # Success Rate: 0.x to X%
            report['avg_success_rate_percent'] = round(report.pop('avg_success_rate') * 100, 2)
            
        conn.close()
        return JSONResponse(reports)

    except Exception as e:
        logging.error(f"Error fetching reports: {e}")
        return JSONResponse({"message": f"Error fetching reports: {e}"}, status_code=500)