from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="TeamProject2026 AI Service",
    version="0.2.0",
    description="Internal AI and pipeline service for Spring backend integration.",
)


class PipelineRunRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=200)


class PipelineRunResponse(BaseModel):
    runId: str
    topic: str


def _launch_pipeline(topic: str) -> str:
    process = subprocess.Popen(
        ["python", "-u", "run_pipeline.py"],
        cwd=BASE_DIR,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    if process.stdin is None or process.stdout is None:
        process.kill()
        raise RuntimeError("Failed to open pipeline process streams")

    process.stdin.write(topic + "\n")
    process.stdin.flush()
    process.stdin.close()

    run_id: str | None = None

    def consume_output() -> None:
        for line in process.stdout:
            print(line, end="")

    for line in process.stdout:
        print(line, end="")
        if line.startswith("runId: "):
            run_id = line.split("runId: ", 1)[1].strip()
            break

    if run_id is None:
        process.kill()
        raise RuntimeError("Pipeline process did not report runId")

    threading.Thread(target=consume_output, daemon=True).start()
    return run_id


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/internal/pipeline/run", response_model=PipelineRunResponse)
def run_pipeline(request: PipelineRunRequest) -> PipelineRunResponse:
    run_id = _launch_pipeline(request.topic)
    return PipelineRunResponse(runId=run_id, topic=request.topic)
