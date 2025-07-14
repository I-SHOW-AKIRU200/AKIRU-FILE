import os
import secrets
import string
from datetime import datetime
from flask import Flask, request, jsonify
from pymongo import MongoClient
from telegram import Bot
from telegram.constants import ParseMode
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    GROUP_ID = int(os.getenv("GROUP_ID"))
    MONGO_URI = os.getenv("MONGO_URI")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex(32))
    REQUIRED_HEADERS = {
        "Name": "TEAM-AKIRU-STORAGE",
        "Connection": "keep-alive",
        "Models": "ATLDE5S1.0",
        "Version": "1.0",
        "Host": "storage-api.team-akiru.site"
    }

app.config.from_object(Config)

# Initialize Telegram Bot
bot = Bot(token=app.config['BOT_TOKEN'])

# MongoDB Setup with error handling
try:
    client = MongoClient(
        app.config['MONGO_URI'],
        connectTimeoutMS=30000,
        socketTimeoutMS=None,
        socketKeepAlive=True,
        connect=False,
        maxPoolSize=1
    )
    client.admin.command('ping')  # Test connection
    db = client["team_akiru_storage"]
    keys_collection = db["keys"]
    files_collection = db["files"]
except Exception as e:
    raise RuntimeError(f"Failed to connect to MongoDB: {str(e)}")

def validate_headers():
    for header, value in app.config['REQUIRED_HEADERS'].items():
        if request.headers.get(header) != value:
            return False
    return True

def generate_secure_key(length=10):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@app.route('/key', methods=['POST'])
def create_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    try:
        key = generate_secure_key()
        keys_collection.insert_one({
            "key": key,
            "created_at": datetime.utcnow(),
            "active": True,
            "ip_address": request.remote_addr
        })
        return jsonify({"key": key})
    except Exception as e:
        return jsonify({"error": "Key generation failed"}), 500

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
    
    try:
        file_key = generate_secure_key(8)
        message = bot.send_document(
            chat_id=app.config['GROUP_ID'],
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
            "file_id": message.document.file_id
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/get', methods=['POST'])
def get_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    file_key = request.form.get('key')
    if not file_key:
        return jsonify({"error": "Missing key"}), 400
    
    file_data = files_collection.find_one(
        {"file_key": file_key, "active": True},
        {"_id": 0, "telegram_file_id": 1}
    )
    
    if not file_data:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify(file_data)

@app.route('/check', methods=['POST'])
def check_keys():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if request.form.get('Password') != app.config['ADMIN_PASSWORD']:
        return jsonify({"error": "Invalid password"}), 403
    
    active_keys = list(keys_collection.find(
        {"active": True},
        {"_id": 0, "key": 1, "created_at": 1, "ip_address": 1}
    ))
    
    return jsonify({"keys": active_keys})

@app.route('/delete', methods=['POST'])
def delete_key():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    if not all(field in request.form for field in ['key', 'password']):
        return jsonify({"error": "Missing required fields"}), 400
    
    if request.form['password'] != app.config['ADMIN_PASSWORD']:
        return jsonify({"error": "Invalid password"}), 403
    
    result = keys_collection.update_one(
        {"key": request.form['key']},
        {"$set": {"active": False}}
    )
    
    if result.modified_count == 0:
        return jsonify({"error": "Key not found"}), 404
    
    return jsonify({"status": "deleted"})

@app.route('/delete-file', methods=['POST'])
def delete_file():
    if not validate_headers():
        return jsonify({"error": "Invalid headers"}), 403
    
    required_fields = ['key', 'file_key', 'password']
    if not all(field in request.form for field in required_fields):
        return jsonify({"error": "Missing required fields"}), 400
    
    if request.form['password'] != app.config['ADMIN_PASSWORD']:
        return jsonify({"error": "Invalid password"}), 403
    
    result = files_collection.update_one(
        {
            "user_key": request.form['key'],
            "file_key": request.form['file_key']
        },
        {"$set": {"active": False}}
    )
    
    if result.modified_count == 0:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({"status": "deleted"})

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true"
    )
