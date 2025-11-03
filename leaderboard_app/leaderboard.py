# app.py
from fastapi import FastAPI
from fastapi_socketio import SocketManager
import json, glob, asyncio
import os

app = FastAPI()
sio = SocketManager(app=app)

def parse_metrics():
    leaderboard = []
    for path in glob.glob("C:/Users/Anchal Agarwal/Documents/hackathon/load_generator/*.json"):
        durations = []
        with open(path) as f:
            for line in f:
                try:
                    record = json.loads(line)
                    if record.get("metric") == "http_req_duration" and record.get("type") == "Point":
                        durations.append(record["data"]["value"])
                except json.JSONDecodeError:
                    continue
        if durations:
            avg_latency = sum(durations) / len(durations)
            leaderboard.append({
                "server": path.replace(".json", ""),
                "avg_latency": round(avg_latency, 2),
                "requests": len(durations)
            })
    return sorted(leaderboard, key=lambda x: x["avg_latency"])

@app.on_event("startup")
async def start_broadcast():
    async def broadcaster():
        while True:
            leaderboard = parse_metrics()
            await sio.emit("leaderboard_update", leaderboard)
            await asyncio.sleep(5)
    asyncio.create_task(broadcaster())
