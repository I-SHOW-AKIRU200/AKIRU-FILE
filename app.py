import os
import secrets
import string
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
from telegram import Bot
from telegram.constants import ParseMode

app = Flask(__name__)

# === Configuration ===
BOT_TOKEN = os.getenv("BOT_TOKEN") or "YOUR_BOT_TOKEN"
GROUP_ID = int(os.getenv("GROUP_ID") or "-4790735842")
MONGO_URI = os.getenv("MONGO_URI") or "mongodb+srv://AKIRU:1234@cluster0.yrhcncv.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

PASSWORD = "TEAM-AKIRU"
API_URL = "https://storage-api.team-akiru.site"

REQUIRED_HEADERS = {
    "Name": "TEAM-AKIRU-STORAGE",
    "Connection": "keep-alive",
    "Models": "ATLDE5S1.0",
    "Version": "1.0"
}

# === Setup ===
bot = Bot(token=BOT_TOKEN)

try:
    client = MongoClient(MONGO_URI, connectTimeoutMS=5000, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    db = client["team_akiru_storage"]
    keys_collection = db["keys"]
    files_collection = db["files"]
except Exception as e:
    raise RuntimeError(f"Failed to connect to MongoDB: {str(e)}")

# === Helpers ===
def validate_headers():
    incoming = {k.lower(): v for k, v in request.headers.items()}
    for key, expected in REQUIRED_HEADERS.items():
        if incoming.get(key.lower()) != expected:
            return False
    return True

def generate_key(length=10):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))

# === Routes ===
@app.route("/key", methods=["POST"])
def create_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403

    key = generate_key()
    keys_collection.insert_one({
        "key": key,
        "created_at": datetime.utcnow(),
        "ip_address": request.remote_addr,
        "active": True
    })

    return jsonify({"key": key}), 200

@app.route("/upload", methods=["POST"])
def upload_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    if 'file' not in request.files or 'key' not in request.form:
        return jsonify({"error": "Missing file or key"}), 400

    file = request.files['file']
    user_key = request.form['key']

    if not keys_collection.find_one({"key": user_key, "active": True}):
        return jsonify({"error": "Invalid key"}), 403

    file_key = generate_key(8)

    try:
        message = bot.send_document(
            chat_id=GROUP_ID,
            document=file,
            parse_mode=ParseMode.HTML
        )
        files_collection.insert_one({
            "user_key": user_key,
            "file_key": file_key,
            "telegram_file_id": message.document.file_id,
            "uploaded_at": datetime.utcnow(),
            "original_filename": file.filename,
            "file_size": file.content_length,
            "active": True
        })

        return jsonify({
            "status": "uploaded",
            "file_key": file_key,
            "file_id": message.document.file_id,
            "url": f"{API_URL}/get"
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/get", methods=["POST"])
def get_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    if "key" not in request.form:
        return jsonify({"error": "Missing key"}), 400

    file_key = request.form["key"]
    file_data = files_collection.find_one(
        {"file_key": file_key, "active": True},
        {"_id": 0, "telegram_file_id": 1}
    )

    if not file_data:
        return jsonify({"error": "File not found"}), 404

    return jsonify(file_data), 200

@app.route("/check", methods=["POST"])
def check_keys():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    if request.form.get("Password") != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403

    keys = list(keys_collection.find(
        {"active": True},
        {"_id": 0, "key": 1, "created_at": 1, "ip_address": 1}
    ))
    return jsonify({"keys": keys}), 200

@app.route("/delete", methods=["POST"])
def delete_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    if "key" not in request.form or "password" not in request.form:
        return jsonify({"error": "Missing key or password"}), 400
    if request.form["password"] != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403

    user_key = request.form["key"]
    keys_collection.update_one({"key": user_key}, {"$set": {"active": False}})
    files_collection.update_many({"user_key": user_key}, {"$set": {"active": False}})

    return jsonify({"status": "deleted"}), 200

@app.route("/delete-file", methods=["POST"])
def delete_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    if not all(k in request.form for k in ["key", "file_key", "password"]):
        return jsonify({"error": "Missing required fields"}), 400
    if request.form["password"] != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403

    result = files_collection.update_one(
        {"user_key": request.form["key"], "file_key": request.form["file_key"]},
        {"$set": {"active": False}}
    )

    if result.modified_count == 0:
        return jsonify({"error": "File not found"}), 404

    return jsonify({"status": "deleted"}), 200

# === Main ===
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
