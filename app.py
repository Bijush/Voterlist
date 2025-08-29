from flask import Flask, request, send_from_directory, render_template, redirect
import os, json
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import json

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 🔹 Initialize Firebase (using environment variable for Render)
# You must set FIREBASE_CREDENTIALS env variable in Render with your service account JSON
cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
firebase_admin.initialize_app(cred)
db = firestore.client()
metadata_ref = db.collection("pdf_metadata")

@app.route('/')
def index():
    query = request.args.get('search', '').lower()
    files = []

    # Fetch metadata from Firestore
    docs = metadata_ref.stream()
    for doc in docs:
        data = doc.to_dict()
        filename = data.get("filename")
        title = data.get("title", "Untitled")
        upload_time = data.get("timestamp", "Unknown")

        if query in title.lower():
            files.append({
                "filename": filename,
                "title": title,
                "timestamp": upload_time
            })

    return render_template('index.html', files=files, search=query)

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    title = request.form.get('title') or 'Untitled'
    filename = file.filename
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # Save metadata in Firestore
    metadata_ref.document(filename).set({
        "filename": filename,
        "title": title,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

    return redirect('/')

@app.route('/delete/<filename>')
def delete_pdf(filename):
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    # Delete metadata from Firestore
    metadata_ref.document(filename).delete()

    return redirect('/')

@app.route('/view/<filename>')
def view_pdf(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
