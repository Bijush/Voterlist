import os
import json
import base64
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, abort
import firebase_admin
from firebase_admin import credentials, db, storage
import io

app = Flask(__name__)

# --- Required environment variables (same style you used before) ---
# FIREBASE_SERVICE_ACCOUNT_BASE64  : base64-encoded service account JSON
# FIREBASE_DATABASE_URL           : e.g. https://your-project-default-rtdb.firebaseio.com
# FIREBASE_STORAGE_BUCKET         : e.g. your-project.appspot.com

firebase_base64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_BASE64")
firebase_db_url = os.environ.get("FIREBASE_DATABASE_URL")
firebase_bucket = os.environ.get("FIREBASE_STORAGE_BUCKET")

if not firebase_base64 or not firebase_db_url or not firebase_bucket:
    raise RuntimeError("Missing required Firebase environment variables")

# decode service account JSON
service_json = json.loads(base64.b64decode(firebase_base64).decode("utf-8"))

if not firebase_admin._apps:
    cred = credentials.Certificate(service_json)
    firebase_admin.initialize_app(cred, {
        "databaseURL": firebase_db_url,
        "storageBucket": firebase_bucket
    })

DB_REF = db.reference("voterlists")   # top-level node for this app
BUCKET = storage.bucket()

def now_str():
    return datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S")

# --- Helpers ---
def default_entry(data=None):
    d = data or {}
    defaults = {
        "district": "",
        "block": "",
        "gp": "",
        "polling_station": "",
        "year": "",
        "filename": "",
        "storage_path": "",
        "public_url": "",
        "uploaded_at": "",
        "uploader": ""
    }
    defaults.update(d)
    return defaults

# --- Routes ---

@app.route("/")
def index():
    # load all entries and pass to template (client will filter)
    snapshot = DB_REF.get() or {}
    entries = []
    for eid, item in snapshot.items():
        e = default_entry(item)
        e["id"] = eid
        entries.append(e)
    # sort by district/block/ps/year
    entries.sort(key=lambda x: (x.get("district",""), x.get("block",""), x.get("gp",""), x.get("polling_station",""), x.get("year","")))
    return render_template("index_voterlist.html", entries=entries)

@app.route("/upload", methods=["GET", "POST"])
def upload():
    if request.method == "POST":
        # simple validation
        district = request.form.get("district","").strip()
        block = request.form.get("block","").strip()
        gp = request.form.get("gp","").strip()
        polling_station = request.form.get("polling_station","").strip()
        year = request.form.get("year","").strip()
        uploader = request.form.get("uploader","").strip() or "anonymous"

        if not (district and block and gp and polling_station and year):
            return "Missing fields", 400

        files = request.files.getlist("pdfs")
        if not files:
            return "No files", 400

        created = []
        for f in files:
            if not f.filename:
                continue
            # only accept .pdf
            if not f.filename.lower().endswith(".pdf"):
                continue

            rec_id = str(uuid.uuid4())
            filename = f.filename.rsplit("/",1)[-1]
            storage_path = f"voterlists/{district}/{block}/{gp}/{polling_station}/{year}/{rec_id}___{filename}"

            blob = BUCKET.blob(storage_path)
            # upload
            blob.upload_from_file(f, content_type="application/pdf")
            # Make public to allow direct link (optional). If you prefer signed urls, remove this.
            try:
                blob.make_public()
                public_url = blob.public_url
            except Exception:
                public_url = ""

            entry = default_entry({
                "district": district,
                "block": block,
                "gp": gp,
                "polling_station": polling_station,
                "year": year,
                "filename": filename,
                "storage_path": storage_path,
                "public_url": public_url,
                "uploaded_at": now_str(),
                "uploader": uploader
            })

            DB_REF.child(rec_id).set(entry)
            created.append(entry)

        return redirect(url_for("index"))

    # GET: render upload form
    return render_template("upload_voterlist.html")

@app.route("/delete/<string:entry_id>", methods=["POST"])
def delete_entry(entry_id):
    rec = DB_REF.child(entry_id).get()
    if not rec:
        return "Not found", 404
    storage_path = rec.get("storage_path")
    # delete blob if exists
    if storage_path:
        blob = BUCKET.blob(storage_path)
        if blob.exists():
            try:
                blob.delete()
            except Exception as e:
                app.logger.warning(f"Failed to delete blob {storage_path}: {e}")
    # delete db record
    DB_REF.child(entry_id).delete()
    return redirect(url_for("index"))

@app.route("/download/<string:entry_id>")
def download_entry(entry_id):
    rec = DB_REF.child(entry_id).get()
    if not rec:
        abort(404)
    storage_path = rec.get("storage_path")
    filename = rec.get("filename") or "file.pdf"
    if not storage_path:
        abort(404)

    blob = BUCKET.blob(storage_path)
    if not blob.exists():
        abort(404)

    # stream blob bytes and send with correct headers
    try:
        data = blob.download_as_bytes()
        return send_file(io.BytesIO(data),
                         download_name=filename,
                         as_attachment=True,
                         mimetype="application/pdf")
    except Exception as e:
        app.logger.error(f"Failed to stream blob {storage_path}: {e}")
        # fallback to public url redirect if available
        public_url = rec.get("public_url")
        if public_url:
            return redirect(public_url)
        abort(500)

# simple api to serve entries as json (optional)
@app.route("/api/entries")
def api_entries():
    snapshot = DB_REF.get() or {}
    entries = []
    for eid, item in snapshot.items():
        e = default_entry(item)
        e["id"] = eid
        entries.append(e)
    return jsonify(entries)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))