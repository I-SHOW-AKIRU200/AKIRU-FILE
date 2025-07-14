import os
import secrets
import string
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
from telegram import Bot
from telegram.constants import ParseMode

app = Flask(__name__)

# Constants
BOT_TOKEN = "7486741325:AAFW27smrvnRk5Y2_j1QOxdE6cn3NxFvFXg"
GROUP_ID = -4790735842
PASSWORD = "TEAM-AKIRU"
REQUIRED_HEADERS = {
    "Name": "TEAM-AKIRU-STORAGE",
    "Connection": "keep-alive",
    "Models": "ATLDE5S1.0",
    "Version": "1.0",
    "Host": "storage-api.team-akiru.site"
}

# Initialize Telegram Bot
bot = Bot(token=BOT_TOKEN)

# MongoDB Setup
client = MongoClient("mongodb+srv://AKIRU:1234@cluster0.yrhcncv.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0")
db = client["team_akiru_storage"]
keys_collection = db["keys"]
files_collection = db["files"]

def validate_headers():
    for header, value in REQUIRED_HEADERS.items():
        if request.headers.get(header) != value:
            return False
    return True

def generate_key(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

@app.route('/key', methods=['POST'])
def create_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    key = generate_key()
    creation_time = datetime.utcnow()
    
    keys_collection.insert_one({
        "key": key,
        "created_at": creation_time,
        "active": True
    })
    
    return jsonify({"key": key})

@app.route('/upload', methods=['POST'])
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
        # Upload to Telegram
        message = bot.send_document(
            chat_id=GROUP_ID,
            document=file,
            parse_mode=ParseMode.HTML
        )
        
        file_id = message.document.file_id
        
        # Store metadata
        files_collection.insert_one({
            "user_key": user_key,
            "file_key": file_key,
            "telegram_file_id": file_id,
            "uploaded_at": datetime.utcnow(),
            "active": True
        })
        
        return jsonify({
            "status": "uploaded",
            "file_key": file_key
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get', methods=['POST'])
def get_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if 'key' not in request.form:
        return jsonify({"error": "Missing key"}), 400
    
    file_key = request.form['key']
    file_data = files_collection.find_one({"file_key": file_key, "active": True})
    
    if not file_data:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({"file_id": file_data["telegram_file_id"]})

@app.route('/check', methods=['POST'])
def check_keys():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if request.form.get('Password') != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403
    
    active_keys = list(keys_collection.find({"active": True}, {"_id": 0, "key": 1, "created_at": 1}))
    
    return jsonify({"keys": active_keys})

@app.route('/delete', methods=['POST'])
def delete_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if 'key' not in request.form or 'password' not in request.form:
        return jsonify({"error": "Missing key or password"}), 400
    
    if request.form['password'] != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403
    
    user_key = request.form['key']
    
    # Deactivate key and associated files
    keys_collection.update_one({"key": user_key}, {"$set": {"active": False}})
    files_collection.update_many({"user_key": user_key}, {"$set": {"active": False}})
    
    return jsonify({"status": "deleted"})

@app.route('/delete-file', methods=['POST'])
def delete_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if not all(field in request.form for field in ['key', 'file_key', 'password']):
        return jsonify({"error": "Missing required fields"}), 400
    
    if request.form['password'] != PASSWORD:
        return jsonify({"error": "Invalid password"}), 403
    
    user_key = request.form['key']
    file_key = request.form['file_key']
    
    result = files_collection.update_one(
        {"user_key": user_key, "file_key": file_key},
        {"$set": {"active": False}}
    )
    
    if result.modified_count == 0:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({"status": "deleted"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
