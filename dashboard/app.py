from flask import Flask, render_template, jsonify, redirect, request, session
import psycopg2
import paho.mqtt.client as mqtt
import json
from datetime import datetime, timedelta
import os
import jwt
import hashlib
import secrets
from functools import wraps
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


load_dotenv()
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '../.env'))

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "supersecretkey")
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "supersecretjwtkey_Tefa2026_Secure!")


limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)



MQTT_BROKER = os.getenv("MQTT_HOST", "broker")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensors/iot")

MQTT_USER = os.getenv("MQTT_USER", "alice")
MQTT_PASSWORD = os.getenv("MQTT_PASS", "1234")



DB_HOST = os.getenv("PG_HOST", "database")
DB_NAME = os.getenv("PG_DB", "mydb")
DB_USER = os.getenv("PG_USER", "alice")
DB_PASS = os.getenv("PG_PASSWORD", "1234")


def crear_tabla():
    import time
    print("Conectando a la base de datos...")
    while True:
        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASS
            )
            print("¡Conexión exitosa a la base de datos!")
            break
        except Exception as e:
            print("Base de datos no lista, reintentando en 2 segundos...")
            time.sleep(2)

    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sensores (
            id SERIAL PRIMARY KEY,
            timestamp TIMESTAMP,
            cultivo TEXT,
            humedad INTEGER,
            luz INTEGER,
            bomba INTEGER
        )
    """)


    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(20) DEFAULT 'user'
        )
    """)

    cur.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'user';")


    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_keys (
            id SERIAL PRIMARY KEY,
            client_name VARCHAR(100) NOT NULL,
            key_hash VARCHAR(255) UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            active BOOLEAN DEFAULT TRUE
        )
    """)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM usuarios")
    count = cur.fetchone()[0]
    if count == 0:
        admin_user = os.getenv("ADMIN_USER", "admin")
        admin_password = os.getenv("ADMIN_PASSWORD", "Tefa_2026!Secure")
        hashed_password = generate_password_hash(admin_password)
        cur.execute("""
            INSERT INTO usuarios (username, password_hash, role)
            VALUES (%s, %s, %s)
        """, (admin_user, hashed_password, 'admin'))
        conn.commit()
        print(f"Usuario administrador '{admin_user}' sembrado con éxito.")
    else:

        admin_user = os.getenv("ADMIN_USER", "admin")
        cur.execute("UPDATE usuarios SET role = 'admin' WHERE username = %s", (admin_user,))
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM api_keys")
    keys_count = cur.fetchone()[0]
    if keys_count == 0:
        client_name = "Tercero_Default"
        default_key = os.getenv("THIRD_PARTY_API_KEY", "Tefa_IoT_Partner_2026_Key")

        hashed_key = hashlib.sha256(default_key.encode()).hexdigest()
        cur.execute("""
            INSERT INTO api_keys (client_name, key_hash)
            VALUES (%s, %s)
        """, (client_name, hashed_key))
        conn.commit()
        print(f"API Key por defecto para '{client_name}' sembrada con éxito.")

    cur.close()
    conn.close()

crear_tabla()


def on_connect(client, userdata, flags, rc):
    print("Conectado a MQTT:", rc)
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())

        cultivo = data.get("cultivo")
        humedad = data.get("humedad")
        luz = data.get("luz")
        bomba = data.get("bomba")

        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )

        cur = conn.cursor()

        cur.execute("""
            INSERT INTO sensores
            (timestamp, cultivo, humedad, luz, bomba)
            VALUES (%s, %s, %s, %s, %s)
        """, (
            datetime.now(),
            cultivo,
            humedad,
            luz,
            bomba
        ))

        conn.commit()

        cur.close()
        conn.close()
        print(f"[MQTT] Mensaje recibido e insertado: {data}")
    except Exception as e:
        print(f"[MQTT Error] Error procesando mensaje MQTT: {e}")



client = mqtt.Client()

client.username_pw_set(MQTT_USER, MQTT_PASSWORD)

client.on_connect = on_connect
client.on_message = on_message

client.connect(MQTT_BROKER, MQTT_PORT, 60)

client.loop_start()



def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.cookies.get("access_token")

        if not token:
            return redirect("/")

        try:
            
            data = jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
            request.user = data
            request.user_role = data.get("role", "user")
            request.username = data.get("sub")
        except jwt.ExpiredSignatureError:
            return redirect("/")
        except jwt.InvalidTokenError:
            return redirect("/")

        return f(*args, **kwargs)
    return decorated


def api_key_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get("X-API-Key")

        if not api_key:
            return jsonify({"error": "Falta la cabecera X-API-Key."}), 401


        key_hash = hashlib.sha256(api_key.encode()).hexdigest()

        try:
            conn = psycopg2.connect(
                host=DB_HOST,
                database=DB_NAME,
                user=DB_USER,
                password=DB_PASS
            )
            cur = conn.cursor()
            cur.execute("""
                SELECT id, client_name 
                FROM api_keys 
                WHERE key_hash = %s AND active = TRUE
            """, (key_hash,))
            client_row = cur.fetchone()
            cur.close()
            conn.close()

            if not client_row:
                return jsonify({"error": "La X-API-Key proporcionada es invalida o esta inactiva."}), 401

            request.client_name = client_row[1]
        except Exception as e:
            return jsonify({"error": f"Error de base de datos al validar API Key: {str(e)}"}), 500

        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        role = getattr(request, "user_role", None)
        if role != "admin":
            if request.path.startswith("/admin/"):
                return jsonify({"error": "Acceso denegado. Se requieren privilegios de administrador."}), 403
            return redirect("/dashboard?error=admin_only")
        return f(*args, **kwargs)
    return decorated



@app.route("/", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def login():
    token = request.cookies.get("access_token")
    if token:
        try:
            jwt.decode(token, JWT_SECRET_KEY, algorithms=["HS256"])
            return redirect("/dashboard")
        except jwt.PyJWTError:
            pass

    error = None
    if request.method == "POST":
        username = request.form.get("usuario")
        password = request.form.get("password")

        if not username or not password:
            error = "Por favor, complete todos los campos."
        else:
            try:
                conn = psycopg2.connect(
                    host=DB_HOST,
                    database=DB_NAME,
                    user=DB_USER,
                    password=DB_PASS
                )
                cur = conn.cursor()
                cur.execute("SELECT id, username, password_hash, role FROM usuarios WHERE username = %s", (username,))
                user_row = cur.fetchone()
                cur.close()
                conn.close()

                if user_row and check_password_hash(user_row[2], password):

                    payload = {
                        "sub": username,
                        "role": user_row[3],
                        "exp": datetime.utcnow() + timedelta(hours=2)
                    }
                    token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")
                    
                    response = redirect("/dashboard")
                    response.set_cookie(
                        "access_token",
                        token,
                        httponly=True,
                        samesite="Lax",
                        max_age=7200  # 2 horas
                    )
                    return response
                else:
                    error = "Usuario o contraseña incorrectos."
            except Exception as e:
                error = f"Error al conectar con la base de datos: {str(e)}"

    return render_template("login.html", error=error)



@app.route("/dashboard")
@jwt_required
def dashboard():
    return render_template("index.html", role=request.user_role, username=request.username)


@app.route("/admin/data", methods=["GET"])
@jwt_required
@admin_required
def admin_data():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()
        
        cur.execute("SELECT id, username, role FROM usuarios ORDER BY id ASC")
        users_rows = cur.fetchall()
        usuarios = []
        for r in users_rows:
            usuarios.append({"id": r[0], "username": r[1], "role": r[2]})
            
        cur.execute("SELECT id, client_name, created_at, active FROM api_keys ORDER BY id ASC")
        keys_rows = cur.fetchall()
        keys = []
        for r in keys_rows:
            keys.append({
                "id": r[0],
                "client_name": r[1],
                "created_at": r[2].strftime("%Y-%m-%d %H:%M:%S"),
                "active": r[3]
            })
            
        cur.close()
        conn.close()
        
        return jsonify({
            "usuarios": usuarios,
            "api_keys": keys
        })
    except Exception as e:
        return jsonify({"error": f"Error al cargar datos administrativos: {str(e)}"}), 500

@app.route("/admin/crear-usuario", methods=["POST"])
@jwt_required
@admin_required
def admin_crear_usuario():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Por favor complete todos los campos."}), 400
        
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM usuarios WHERE username = %s", (username,))
        exists = cur.fetchone()[0]
        
        if exists > 0:
            cur.close()
            conn.close()
            return jsonify({"error": f"El nombre de usuario '{username}' ya esta registrado."}), 400
            
        password_hash = generate_password_hash(password)
        cur.execute("""
            INSERT INTO usuarios (username, password_hash, role)
            VALUES (%s, %s, %s)
        """, (username, password_hash, 'user'))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"message": f"Usuario '{username}' registrado con éxito."}), 201
    except Exception as e:
        return jsonify({"error": f"Error al registrar usuario: {str(e)}"}), 500

@app.route("/admin/crear-api-key", methods=["POST"])
@jwt_required
@admin_required
def admin_crear_api_key():
    data = request.get_json() or {}
    client_name = data.get("client_name", "").strip()
    
    if not client_name:
        return jsonify({"error": "Por favor complete el nombre del cliente."}), 400
        
    try:
        api_key = "iot_" + secrets.token_urlsafe(32)
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()
        
        cur.execute("""
            INSERT INTO api_keys (client_name, key_hash)
            VALUES (%s, %s)
        """, (client_name, key_hash))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({
            "message": f"API Key para '{client_name}' creada con éxito.",
            "api_key": api_key
        }), 201
    except Exception as e:
        return jsonify({"error": f"Error al crear API Key: {str(e)}"}), 500

@app.route("/admin/toggle-api-key", methods=["POST"])
@jwt_required
@admin_required
def admin_toggle_api_key():
    data = request.get_json() or {}
    key_id = data.get("id")
    
    if not key_id:
        return jsonify({"error": "ID de API Key requerido."}), 400
        
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()
        

        cur.execute("UPDATE api_keys SET active = NOT active WHERE id = %s RETURNING active, client_name", (key_id,))
        res = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        
        if not res:
            return jsonify({"error": "API Key no encontrada."}), 404
            
        estado = "activada" if res[0] else "desactivada"
        return jsonify({"message": f"API Key de '{res[1]}' {estado} con éxito."})
    except Exception as e:
        return jsonify({"error": f"Error al alternar estado de API Key: {str(e)}"}), 500


@app.route("/api/datos")
@limiter.exempt
@jwt_required
def api_datos():
    conn = psycopg2.connect(
        host=DB_HOST,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASS
    )

    cur = conn.cursor()

    cur.execute("""
        SELECT timestamp, cultivo, humedad, luz, bomba
        FROM sensores
        ORDER BY timestamp DESC
        LIMIT 20
    """)

    rows = cur.fetchall()

    datos = []

    for row in rows:
        datos.append({
            "ts": row[0].strftime("%H:%M:%S"),
            "cultivo": row[1],
            "humedad": row[2],
            "luz": row[3],
            "bomba": row[4]
        })

    cur.close()
    conn.close()

    return jsonify(datos)



@app.route("/api/v1/sensores", methods=["GET"])
@limiter.limit("60 per minute")
@api_key_required
def api_v1_sensores():
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS
        )
        cur = conn.cursor()


        cultivo = request.args.get("cultivo")
        limit = request.args.get("limite", default=20, type=int)


        if limit > 100:
            limit = 100

        if cultivo:
            cur.execute("""
                SELECT timestamp, cultivo, humedad, luz, bomba
                FROM sensores
                WHERE cultivo = %s
                ORDER BY timestamp DESC
                LIMIT %s
            """, (cultivo, limit))
        else:
            cur.execute("""
                SELECT timestamp, cultivo, humedad, luz, bomba
                FROM sensores
                ORDER BY timestamp DESC
                LIMIT %s
            """, (limit,))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        datos = []
        for row in rows:
            datos.append({
                "ts": row[0].isoformat(),
                "cultivo": row[1],
                "humedad": row[2],
                "luz": row[3],
                "bomba": row[4]
            })

        return jsonify({
            "cliente": request.client_name,
            "total_registros": len(datos),
            "data": datos
        })

    except Exception as e:
        return jsonify({"error": f"Error al procesar la solicitud: {str(e)}"}), 500



@app.route("/logout")
def logout():
    response = redirect("/")
    response.delete_cookie("access_token")
    session.clear()
    return response



@app.errorhandler(429)
def rate_limit_handler(e):
    return render_template("login.html", error="Demasiados intentos de inicio de sesión. Por favor, espere una hora."), 429


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000  
    )