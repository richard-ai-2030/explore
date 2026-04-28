import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from kafka import KafkaProducer
from psycopg.rows import dict_row

KAFKA_ENABLED = os.getenv('KAFKA_ENABLED', 'true').lower() == 'true'
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', '172.19.0.1:9092')
KAFKA_EVENTS_TOPIC = os.getenv('KAFKA_EVENTS_TOPIC', 'explore.events')
OUTBOX_POLL_INTERVAL = float(os.getenv('OUTBOX_POLL_INTERVAL', '2.0'))
OUTBOX_BATCH_SIZE = int(os.getenv('OUTBOX_BATCH_SIZE', '50'))


def event_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_outbox_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS outbox_events (
          id TEXT PRIMARY KEY,
          topic TEXT NOT NULL,
          event_key TEXT NOT NULL,
          event_type TEXT NOT NULL,
          payload TEXT NOT NULL,
          headers TEXT NOT NULL DEFAULT '{}',
          status TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          published_at TEXT
        )
        """
    )


def build_event(service_name: str, event_type: str, aggregate_id: str, payload: dict[str, Any], request_headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = request_headers or {}
    return {
        'eventId': str(uuid.uuid4()),
        'eventType': event_type,
        'eventVersion': 1,
        'occurredAt': event_timestamp(),
        'producer': service_name,
        'aggregateId': aggregate_id,
        'partitionKey': aggregate_id,
        'correlationId': request_headers.get('x-correlation-id') or request_headers.get('x-request-id') or str(uuid.uuid4()),
        'actor': request_headers.get('x-auth-user-email') or request_headers.get('x-auth-user-id'),
        'payload': payload,
    }


def enqueue_outbox_event(conn, service_name: str, event_type: str, aggregate_id: str, payload: dict[str, Any], request_headers: dict[str, str] | None = None, topic: str | None = None) -> dict[str, Any]:
    event = build_event(service_name, event_type, aggregate_id, payload, request_headers=request_headers)
    conn.execute(
        'INSERT INTO outbox_events (id, topic, event_key, event_type, payload, headers, status, attempts, created_at, published_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)',
        (
            event['eventId'],
            topic or KAFKA_EVENTS_TOPIC,
            event['partitionKey'],
            event['eventType'],
            json.dumps(event),
            json.dumps({
                'service': service_name,
                'eventType': event_type,
            }),
            'pending',
            0,
            event['occurredAt'],
            None,
        ),
    )
    return event


class OutboxRelay:
    def __init__(self, service_name: str, db_factory):
        self.service_name = service_name
        self.db_factory = db_factory
        self.enabled = KAFKA_ENABLED
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._producer: KafkaProducer | None = None

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name=f'{self.service_name}-outbox-relay', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._producer:
            try:
                self._producer.flush(timeout=2)
            except Exception:
                pass
            try:
                self._producer.close(timeout=2)
            except Exception:
                pass

    def _get_producer(self) -> KafkaProducer:
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=[item.strip() for item in KAFKA_BOOTSTRAP_SERVERS.split(',') if item.strip()],
                value_serializer=lambda value: json.dumps(value).encode('utf-8'),
                key_serializer=lambda value: value.encode('utf-8'),
                acks='all',
                retries=5,
                linger_ms=50,
            )
        return self._producer

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with self.db_factory() as conn:
                    rows = conn.execute(
                        'SELECT * FROM outbox_events WHERE status = %s ORDER BY created_at ASC LIMIT %s',
                        ('pending', OUTBOX_BATCH_SIZE),
                    ).fetchall()
                    if not rows:
                        time.sleep(OUTBOX_POLL_INTERVAL)
                        continue
                    producer = self._get_producer()
                    for row in rows:
                        event = json.loads(row['payload'])
                        producer.send(row['topic'], key=row['event_key'], value=event).get(timeout=10)
                        conn.execute(
                            'UPDATE outbox_events SET status = %s, attempts = attempts + 1, published_at = %s WHERE id = %s',
                            ('published', event_timestamp(), row['id']),
                        )
                    conn.commit()
                    producer.flush(timeout=10)
            except Exception as exc:
                print(f'[{self.service_name}] outbox relay error: {exc}')
                time.sleep(OUTBOX_POLL_INTERVAL)
