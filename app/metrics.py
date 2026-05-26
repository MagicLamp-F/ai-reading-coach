from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

from app.repository import Repository


class MetricsServer:
    def __init__(self, repo: Repository, host: str = "0.0.0.0", port: int = 9108):
        self.repo = repo
        self.server = HTTPServer((host, port), self._handler())

    def start_background(self) -> None:
        thread = Thread(target=self.server.serve_forever, daemon=True)
        thread.start()

    def _handler(self):
        repo = self.repo

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if self.path != "/metrics":
                    self.send_response(404)
                    self.end_headers()
                    return
                body = _render_metrics(repo).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; version=0.0.4")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):  # noqa: A002
                return

        return Handler


def _render_metrics(repo: Repository) -> str:
    conn = repo.conn
    run_rows = conn.execute("SELECT status, COUNT(*) AS count FROM run_logs GROUP BY status").fetchall()
    feedback_rows = conn.execute("SELECT feedback_type, COUNT(*) AS count FROM feedback_events GROUP BY feedback_type").fetchall()
    profile_count = conn.execute("SELECT COUNT(*) AS count FROM profile_items").fetchone()["count"]
    lines = [
        "# HELP reading_coach_profile_items Total profile items.",
        "# TYPE reading_coach_profile_items gauge",
        f"reading_coach_profile_items {profile_count}",
        "# HELP reading_coach_runs_total Total workflow runs by status.",
        "# TYPE reading_coach_runs_total counter",
    ]
    lines.extend(f'reading_coach_runs_total{{status="{row["status"]}"}} {row["count"]}' for row in run_rows)
    lines.extend(
        [
            "# HELP reading_coach_feedback_total Total feedback events by type.",
            "# TYPE reading_coach_feedback_total counter",
        ]
    )
    lines.extend(
        f'reading_coach_feedback_total{{feedback_type="{row["feedback_type"]}"}} {row["count"]}'
        for row in feedback_rows
    )
    return "\n".join(lines) + "\n"

