from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Optional

import pika


class RabbitMqPublisher:
    def __init__(
        self,
        *,
        amqp_url: str,
        exchange: str,
        routing_key: str,
        durable: bool = True,
    ) -> None:
        self.amqp_url = amqp_url
        self.exchange = exchange
        self.routing_key = routing_key
        self.durable = durable

        params = pika.URLParameters(amqp_url)
        self._conn = pika.BlockingConnection(params)
        self._ch = self._conn.channel()

        # (optional) declare exchange if you own it
        # self._ch.exchange_declare(exchange=self.exchange, exchange_type="topic", durable=durable)

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass

    def publish(self, payload: Any, *, message_id: Optional[str] = None) -> None:
        body = self._to_json(payload).encode("utf-8")

        props = pika.BasicProperties(
            content_type="application/json",
            delivery_mode=2,  #persistent
            message_id=message_id,
        )

        self._ch.basic_publish(
            exchange=self.exchange,
            routing_key=self.routing_key,
            body=body,
            properties=props,
        )

    @staticmethod
    def _to_json(payload: Any) -> str:
        # Prefer explicit to_es_doc if your models have it
        if hasattr(payload, "to_es_doc") and callable(payload.to_es_doc):
            d = payload.to_es_doc(include_subtitles=True)
            return json.dumps(d, ensure_ascii=False)

        # Dataclass fallback
        if is_dataclass(payload):
            return json.dumps(asdict(payload), ensure_ascii=False)

        # Dict fallback
        if isinstance(payload, dict):
            return json.dumps(payload, ensure_ascii=False)

        raise TypeError(f"Cannot serialize payload type: {type(payload)!r}")
