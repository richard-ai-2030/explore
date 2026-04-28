import json
import os
import threading
import time
from typing import Callable

from kafka import KafkaConsumer

KAFKA_ENABLED = os.getenv('KAFKA_ENABLED', 'true').lower() == 'true'
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', '172.19.0.1:9092')
KAFKA_EVENTS_TOPIC = os.getenv('KAFKA_EVENTS_TOPIC', 'explore.events')
KAFKA_CONSUMER_GROUP = os.getenv('KAFKA_CONSUMER_GROUP', 'explore-consumer')
KAFKA_AUTO_OFFSET_RESET = os.getenv('KAFKA_AUTO_OFFSET_RESET', 'earliest')
KAFKA_POLL_TIMEOUT_MS = int(os.getenv('KAFKA_POLL_TIMEOUT_MS', '1000'))


class KafkaEventConsumer:
    def __init__(self, service_name: str, handler: Callable[[dict], None], topics: list[str] | None = None, consumer_group: str | None = None):
        self.service_name = service_name
        self.handler = handler
        self.topics = topics or [KAFKA_EVENTS_TOPIC]
        self.consumer_group = consumer_group or f'{service_name}-group'
        self.enabled = KAFKA_ENABLED
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        self._thread = threading.Thread(target=self._run, name=f'{self.service_name}-kafka-consumer', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        consumer = None
        while not self._stop.is_set():
            try:
                consumer = KafkaConsumer(
                    *self.topics,
                    bootstrap_servers=[item.strip() for item in KAFKA_BOOTSTRAP_SERVERS.split(',') if item.strip()],
                    group_id=self.consumer_group,
                    value_deserializer=lambda value: json.loads(value.decode('utf-8')),
                    enable_auto_commit=True,
                    auto_offset_reset=KAFKA_AUTO_OFFSET_RESET,
                    consumer_timeout_ms=KAFKA_POLL_TIMEOUT_MS,
                )
                while not self._stop.is_set():
                    for message in consumer:
                        self.handler(message.value)
                    time.sleep(1)
            except Exception as exc:
                print(f'[{self.service_name}] kafka consumer error: {exc}')
                time.sleep(2)
            finally:
                if consumer is not None:
                    try:
                        consumer.close()
                    except Exception:
                        pass
                        
