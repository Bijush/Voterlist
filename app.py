from flask import Flask, request, render_template, redirect
import os, json
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, db, storage

app = Flask(__name__)

# Initialize Firebase using credentials and the Realtime Database URL
cred = credentials.Certificate(json.loads(os.environ["FIREBASE_CREDENTIALS"]))
firebase_admin.initialize_app(cred, {
    "databaseURL": "https://bijus-app-52978.firebaseio.com/",
    "storageBucket": "bijus-app-52978.appspot.com"
})

bucket = storage.bucket()
metadata_ref = db.reference('pdf_metadata')


@app.route('/')
def index():
    query = request.args.get('search', '').lower()
    files = []

    all_metadata = metadata_ref.get() or {}
    for filename, data in all_metadata.items():
        title = data.get("title", "Untitled")
        timestamp = data.get("timestamp", "Unknown")
        url = data.get("url", "#")

        if query in title.lower():
            files.append({
                "filename": filename,
                "title": title,
                "timestamp": timestamp,
                "url": url
            })

    return render_template('index.html', files=files, search=query)


@app.route('/upload', methods=['POST'])
def upload():
    file = request.files['pdf']
    title = request.form.get('title') or 'Untitled'
    filename = file.filename

    # Upload PDF to Firebase Storage
    blob = bucket.blob(filename)
    blob.upload_from_file(file, content_type="application/pdf")

    # Generate signed URL valid for 1 year
    url = blob.generate_signed_url(expiration=timedelta(days=365))

    # Save metadata to Realtime Database
    metadata_ref.child(filename).set({
        "title": title,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "url": url
    })

    return redirect('/')


@app.route('/delete/<filename>')
def delete_pdf(filename):
    # Delete from Firebase Storage
    blob = bucket.blob(filename)
    if blob.exists():
        blob.delete()

    # Delete metadata from Realtime DB
    metadata_ref.child(filename).delete()

    return redirect('/')


@app.route('/view/<filename>')
def view_pdf(filename):
    data = metadata_ref.child(filename).get()
    if data:
        return redirect(data.get('url', '#'))
    return "File not found", 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
