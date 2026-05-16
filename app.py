#!/usr/bin/env python3
"""
Vocal Reference Generator — Web App
Flask-based web interface with async job processing.
"""

import os
import sys
import uuid
import time
import threading
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, render_template, request, jsonify, send_file, abort, session, redirect, url_for
import functools
import hashlib
import time
from collections import defaultdict

# Add the app directory to path so we can import pipeline
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import process_file, process_vocals_only

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-in-production-vocal-ref-2024")

# Abuse Prevention
LOGIN_PASSWORD = os.environ.get("VOCAL_REF_PASSWORD", None)  # Set to enable password protection
MAX_UPLOADS_PER_HOUR = int(os.environ.get("MAX_UPLOADS_PER_HOUR", "10"))
RATE_LIMIT_WINDOW = 3600  # 1 hour

# Simple in-memory rate limiter: IP -> [timestamps]
upload_attempts = defaultdict(list)

# Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
OUTPUT_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "outputs")
MAX_CONTENT_LENGTH = 100 * 1024 * 1024  # 100 MB max upload
JOB_TIMEOUT_HOURS = 24

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# In-memory job storage (sufficient for single-user personal use)
# For multi-user production, switch to Redis or database
jobs = {}
jobs_lock = threading.Lock()


class Job:
    def __init__(self, job_id, filename):
        self.id = job_id
        self.filename = filename
        self.status = "queued"  # queued, processing, completed, error
        self.progress = 0
        self.message = "Waiting to start..."
        self.error = None
        self.output_path = None
        self.created_at = datetime.utcnow()
        self.thread = None

    def to_dict(self):
        return {
            "id": self.id,
            "filename": self.filename,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


def cleanup_old_jobs():
    """Remove jobs and files older than JOB_TIMEOUT_HOURS."""
    cutoff = datetime.utcnow() - timedelta(hours=JOB_TIMEOUT_HOURS)
    with jobs_lock:
        to_remove = [jid for jid, job in jobs.items() if job.created_at < cutoff]
        for jid in to_remove:
            job = jobs.pop(jid, None)
            if job:
                # Clean up files
                upload_path = os.path.join(UPLOAD_FOLDER, job.filename)
                if os.path.exists(upload_path):
                    os.remove(upload_path)
                if job.output_path and os.path.exists(job.output_path):
                    os.remove(job.output_path)


def run_pipeline(job_id, input_path, output_path, settings):
    """Run the processing pipeline in a background thread."""
    with jobs_lock:
        job = jobs.get(job_id)
        if not job:
            return
        job.status = "processing"
        job.message = "Starting..."

    def progress_callback(msg, pct):
        with jobs_lock:
            j = jobs.get(job_id)
            if j:
                j.message = msg
                j.progress = pct

    try:
        mode = settings.get("mode", "mix")

        if mode == "vocals_only":
            process_vocals_only(
                input_path, output_path,
                formant_ratio=float(settings.get("formant_ratio", 1.5)),
                pitch_shift_semitones=float(settings.get("pitch_shift", 0.0)),
                pitch_range_ratio=float(settings.get("pitch_range", 1.0)),
                noise_db=float(settings.get("noise_db", -75.0)),
                device=settings.get("device", "cpu"),
                vocal_style=settings.get("vocal_style", "formant"),
                progress_callback=progress_callback,
            )
        else:
            process_file(
                input_path, output_path,
                formant_ratio=float(settings.get("formant_ratio", 1.5)),
                pitch_shift_semitones=float(settings.get("pitch_shift", 0.0)),
                pitch_range_ratio=float(settings.get("pitch_range", 1.0)),
                noise_db=float(settings.get("noise_db", -75.0)),
                vocal_gain_db=float(settings.get("vocal_gain", -2.0)),
                device=settings.get("device", "cpu"),
                vocal_style=settings.get("vocal_style", "formant"),
                transpose_semitones=float(settings.get("transpose", 0.0)),
                progress_callback=progress_callback,
            )

        with jobs_lock:
            j = jobs.get(job_id)
            if j:
                j.status = "completed"
                j.progress = 100
                j.message = "Done!"
                j.output_path = output_path

    except Exception as e:
        import traceback
        error_msg = f"{str(e)}\n{traceback.format_exc()}"
        with jobs_lock:
            j = jobs.get(job_id)
            if j:
                j.status = "error"
                j.error = error_msg
                j.message = f"Error: {str(e)}"


def login_required(f):
    """Require login if LOGIN_PASSWORD is set."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if LOGIN_PASSWORD and not session.get("logged_in"):
            if request.is_json:
                return jsonify({"error": "Unauthorized. Please login."}), 401
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)
    return decorated


def rate_limit(f):
    """Rate limit uploads by IP address."""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        now = time.time()
        ip = request.remote_addr or "unknown"
        # Clean old entries
        upload_attempts[ip] = [t for t in upload_attempts[ip] if now - t < RATE_LIMIT_WINDOW]
        if len(upload_attempts[ip]) >= MAX_UPLOADS_PER_HOUR:
            return jsonify({"error": f"Rate limit exceeded. Max {MAX_UPLOADS_PER_HOUR} uploads per hour."}), 429
        upload_attempts[ip].append(now)
        return f(*args, **kwargs)
    return decorated


@app.route("/login", methods=["GET", "POST"])
def login_page():
    if not LOGIN_PASSWORD:
        session["logged_in"] = True
        return redirect(url_for("index"))
    if request.method == "POST":
        password = request.form.get("password", "")
        # Simple constant-time comparison
        if hashlib.sha256(password.encode()).hexdigest() == hashlib.sha256(LOGIN_PASSWORD.encode()).hexdigest():
            session["logged_in"] = True
            return redirect(url_for("index"))
        return render_template("login.html", error="Invalid password"), 401
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login_page"))


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
@login_required
@rate_limit
def upload():
    """Handle file upload and start processing."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    # Validate file extension
    allowed_extensions = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".wma"}
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed_extensions:
        return jsonify({"error": f"Unsupported file type: {ext}. Allowed: {allowed_extensions}"}), 400

    # Generate job ID
    job_id = str(uuid.uuid4())
    safe_name = f"{job_id}{ext}"
    input_path = os.path.join(UPLOAD_FOLDER, safe_name)
    output_filename = f"{job_id}_output.mp3"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)

    # Save uploaded file
    file.save(input_path)

    # Get settings from form
    settings = {
        "formant_ratio": request.form.get("formant_ratio", "1.5"),
        "pitch_shift": request.form.get("pitch_shift", "0.0"),
        "pitch_range": request.form.get("pitch_range", "1.0"),
        "noise_db": request.form.get("noise_db", "-75.0"),
        "vocal_gain": request.form.get("vocal_gain", "-2.0"),
        "device": request.form.get("device", "cpu"),
        "mode": request.form.get("mode", "mix"),
        "vocal_style": request.form.get("vocal_style", "formant"),
        "transpose": request.form.get("transpose", "0.0"),
    }

    # Create job
    job = Job(job_id, safe_name)
    with jobs_lock:
        jobs[job_id] = job

    # Start processing in background thread
    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, input_path, output_path, settings),
        daemon=True,
    )
    job.thread = thread
    thread.start()

    return jsonify({"job_id": job_id, "status": "queued"})


@app.route("/api/status/<job_id>")
@login_required
def status(job_id):
    """Get job status and progress."""
    cleanup_old_jobs()

    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        return jsonify({"error": "Job not found"}), 404

    return jsonify(job.to_dict())


@app.route("/api/download/<job_id>")
@login_required
def download(job_id):
    """Download the processed file."""
    with jobs_lock:
        job = jobs.get(job_id)

    if not job:
        abort(404, "Job not found")

    if job.status != "completed" or not job.output_path:
        abort(400, "Job not completed yet")

    if not os.path.exists(job.output_path):
        abort(404, "Output file no longer available")

    return send_file(
        job.output_path,
        as_attachment=True,
        download_name=f"vocal_reference_{job.filename.rsplit('.', 1)[0]}.mp3",
    )


@app.route("/api/presets")
@login_required
def presets():
    """Return available presets."""
    return jsonify({
        "Default": {"formant": 1.5, "pitch": 0.0, "pitch_range": 1.0, "noise": -75.0, "gain": -2.0, "mode": "mix", "vocal_style": "formant", "transpose": 0.0},
        "Suno Reference": {"formant": 1.4, "pitch": 0.0, "pitch_range": 1.0, "noise": -80.0, "gain": 0.0, "mode": "mix", "vocal_style": "formant", "transpose": 0.0},
        "Alien/Gibberish": {"formant": 1.8, "pitch": 0.0, "pitch_range": 1.0, "noise": -75.0, "gain": -2.0, "mode": "mix", "vocal_style": "formant", "transpose": 0.0},
        "Simlish": {"formant": 1.5, "pitch": 0.0, "pitch_range": 1.0, "noise": -75.0, "gain": 0.0, "mode": "vocals_only", "vocal_style": "humming", "transpose": 0.0},
        "Subtle": {"formant": 1.2, "pitch": 0.0, "pitch_range": 1.0, "noise": -85.0, "gain": -2.0, "mode": "mix", "vocal_style": "formant", "transpose": 0.0},
        "Vocals Only (Suno)": {"formant": 1.4, "pitch": 0.0, "pitch_range": 1.0, "noise": -80.0, "gain": 0.0, "mode": "vocals_only", "vocal_style": "formant", "transpose": 0.0},
    })


if __name__ == "__main__":
    # Development server - not for production
    app.run(host="127.0.0.1", port=5000, debug=True)
