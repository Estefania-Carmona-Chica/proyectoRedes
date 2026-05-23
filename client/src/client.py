#from dotenv import load_dotenv
import json
import os
import time
import psycopg2
import paho.mqtt.client as mqtt
from datetime import datetime, timezone

PG_HOST = os.getenv('PG_HOST')
PG_PORT = int(os.getenv('PG_PORT'))
PG_DB = os.getenv('PG_DB')
PG_USER = os.getenv('PG_USER')
PG_PASSWORD = os.getenv('PG_PASSWORD')
MQTT_HOST = os.getenv('MQTT_HOST')
MQTT_PORT = int(os.getenv('MQTT_PORT'))
MQTT_TOPIC = os.getenv('MQTT_TOPIC')
MQTT_USER = os.getenv('MQTT_USER')
MQTT_PASS = os.getenv('MQTT_PASS')

print('Conectando a DB...')
while True:
    try:
        conn = psycopg2.connect(host=PG_HOST, port=PG_PORT, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD)
        print('Conectado a DB')
        break
    except Exception as e:
        print('DB no lista, reintentando...')
        time.sleep(2)

conn.autocommit = True
cur = conn.cursor()
cur.execute("""
CREATE TABLE IF NOT EXISTS sensors (
    ts TIMESTAMP WITH TIME ZONE,
    cultivo TEXT,
    humedad INTEGER,
    luz INTEGER,
    bomba INTEGER
);
""")

def on_connect(client, userdata, flags, rc):
    print('Connected to MQTT')
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    data = json.loads(msg.payload.decode())
    cultivo = data["cultivo"]
    humedad = int(data["humedad"])
    luz = int(data["luz"])
    bomba = int(data["bomba"])
    ts = datetime.now(timezone.utc)
    cur.execute(
        "INSERT INTO sensors (ts, cultivo, humedad, luz, bomba) VALUES (%s, %s, %s, %s, %s);",
        (ts, cultivo, humedad, luz, bomba)
    )
    print(f"Saved: cultivo={cultivo} humedad={humedad} luz={luz} bomba={bomba}")

client = mqtt.Client()
if MQTT_USER:
    client.username_pw_set(MQTT_USER, MQTT_PASS)
client.on_connect = on_connect
client.on_message = on_message
print(f'Conectando a MQTT: {MQTT_HOST}:{MQTT_PORT}')
client.connect(MQTT_HOST, MQTT_PORT, 60)
client.loop_forever()
