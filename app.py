from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
import base64
import os
from datetime import datetime

# New imports for login
from flask_login import LoginManager, login_user, logout_user, login_required, UserMixin, current_user

app = Flask(__name__)
app.secret_key = 'your-secret-key'  # Required for session management, set a strong secret in production

# ---------- MongoDB Setup ----------
client = MongoClient("mongodb://localhost:27017/")
db = client['attendance_db']
users_collection = db['users']

# ---------- Flask-Login Setup ----------
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'  # Redirect to /login if unauthorized

# Simple admin user class
class AdminUser(UserMixin):
    def __init__(self, id):
        self.id = id
        self.name = "sahil"
        self.password = "sahil123"  # Hardcoded password, change this for production!

# In-memory user store
users = {
    "sahil": AdminUser("sahil")
}

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# ---------- Sub-center mapping logic ----------
sub_center_mapping = {
    "Center A": {
        "morning": "Sub A1",
        "evening": "Sub A2"
    },
    "Center B": {
        "morning": "Sub B1",
        "evening": "Sub B2"
    },
    "Center C": {
        "morning": "Sub C1",
        "evening": "Sub C2"
    }
}

# ---------- Routes ----------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = users.get(username)
        if user and password == user.password:
            login_user(user)
            return redirect(url_for('admin_panel'))
        else:
            flash("Invalid username or password", "error")

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/upload-photo', methods=['POST'])
def upload_photo():
    import requests

    data = request.get_json()

    # New fields from form
    volunteer_id = data.get('volunteer_id')
    center_name = data.get('center_name')
    shift = data.get('shift')

    # Automatically determine sub_center_name
    sub_center_name = sub_center_mapping.get(center_name, {}).get(shift, "Unknown Sub-Center")

    # Existing fields
    name = data.get('name')
    photo = data.get('photo')
    latitude = data.get('latitude')
    longitude = data.get('longitude')

    # Get attendance date (UTC date only, ISO format)
    attendance_date = datetime.utcnow().date().isoformat()

    # Check if attendance already marked today for same volunteer, shift
    existing = users_collection.find_one({
        "volunteer_id": volunteer_id,
        "attendance_date": attendance_date,
        "shift": shift
    })
    if existing:
        return jsonify({"status": "error", "message": "Attendance already marked for this shift today"}), 400

    # Strip base64 prefix if present
    if photo and photo.startswith('data:image/jpeg;base64,'):
        photo = photo.split(',', 1)[1]

    # Optional reverse geocoding
    location_name = None
    try:
        response = requests.get(
            'https://nominatim.openstreetmap.org/reverse',
            params={
                'format': 'json',
                'lat': latitude,
                'lon': longitude
            },
            headers={
                'User-Agent': 'attendance-system/1.0'
            }
        )
        location_json = response.json()
        location_name = location_json.get('display_name')
    except Exception as e:
        print("Reverse geocoding failed:", e)

    user = {
        "volunteer_id": volunteer_id,
        "center_name": center_name,
        "sub_center_name": sub_center_name,
        "name": name,
        "shift": shift,
        "attendance_date": attendance_date,  # <-- Added field
        "photo": photo,
        "latitude": latitude,
        "longitude": longitude,
        "location_name": location_name,
        "timestamp": datetime.utcnow(),
        "device_id": request.headers.get('User-Agent'),
        "credential_id": None,
        "public_key": None,
        "attendance_marked": False
    }

    result = users_collection.insert_one(user)
    return jsonify({"status": "success", "user_id": str(result.inserted_id)})

@app.route('/auth/begin-registration')
def begin_registration():
    from base64 import b64encode
    user_id = request.args.get('user_id')
    user = users_collection.find_one({'_id': ObjectId(user_id)})
    if not user:
        return jsonify({'error': 'User not found'}), 404

    challenge = os.urandom(32)

    return jsonify({
        "publicKey": {
            "challenge": b64encode(challenge).decode(),
            "rp": {"name": "Volunteer Attendance"},
            "user": {
                "id": b64encode(user_id.encode()).decode(),
                "name": user['name'],
                "displayName": user['name']
            },
            "pubKeyCredParams": [{"type": "public-key", "alg": -7}],
            "timeout": 60000,
            "attestation": "direct",
            "authenticatorSelection": {
                "authenticatorAttachment": "platform",
                "userVerification": "required"
            }
        }
    })

@app.route('/auth/finish-registration', methods=['POST'])
def finish_registration():
    try:
        data = request.get_json()
        user_id = data['user_id']
        credential_id = data['credentialId']
        public_key = data['publicKey']

        result = users_collection.update_one(
            {'_id': ObjectId(user_id)},
            {'$set': {
                'credential_id': credential_id,
                'public_key': public_key,
                'attendance_marked': True
            }}
        )

        if result.matched_count == 0:
            return jsonify({'error': 'User not found'}), 404

        return jsonify({'status': 'Fingerprint registered ✅'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/view-photos')
def view_photos():
    users = []
    for user in users_collection.find({'photo': {'$exists': True}}).sort('_id', -1):
        users.append({
            'id': str(user['_id']),
            'name': user.get('name', 'N/A'),
            'shift': user.get('shift', 'N/A'),
            'photo': user.get('photo'),
            'latitude': user.get('latitude'),
            'longitude': user.get('longitude'),
            'attendance_marked': user.get('attendance_marked', False)
        })
    return render_template('view_photos.html', users=users)

@app.route('/admin')
@login_required
def admin_panel():
    users_cursor = users_collection.find().sort('_id', -1)
    users = []
    for user in users_cursor:
        # Add attendance_date from timestamp for frontend filtering
        if 'timestamp' in user and isinstance(user['timestamp'], datetime):
            user['attendance_date'] = user['timestamp'].strftime('%Y-%m-%d')
        else:
            user['attendance_date'] = 'N/A'
        users.append(user)
    return render_template('admin.html', users=users)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, ssl_context='adhoc')
