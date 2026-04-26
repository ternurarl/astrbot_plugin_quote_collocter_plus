from __future__ import annotations

import base64
import html
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from astrbot.core.message.components import Image, Json, Plain
except Exception:  # pragma: no cover - only used outside an AstrBot runtime.
    Image = Json = Plain = None


def _is_component(value: Any, component_type: Any) -> bool:
    return component_type is not None and isinstance(value, component_type)


class MessageParser:
    def __init__(self, max_depth: int = 3):
        self.max_depth = max_depth

    def extract_reply_text(self, chain: Any) -> str:
        return (self.extract_plain_text_from_payload(chain) or "").strip()

    def unwrap_api_data(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and "type" not in payload:
            data = payload.get("data")
            if isinstance(data, dict):
                return data
        return payload if isinstance(payload, dict) else {}

    def message_chain_from_payload(self, payload: Any) -> list[Any] | str | None:
        data = self.unwrap_api_data(payload)
        for key in ("message", "messages"):
            value = data.get(key)
            if isinstance(value, (list, str)):
                return value
        return None

    def reply_sender_meta(self, event: Any, reply_msg: Any, reply_comp: Any) -> tuple[Any, str, str]:
        data = self.unwrap_api_data(reply_msg)
        sender = data.get("sender") if isinstance(data, dict) else {}
        if not isinstance(sender, dict):
            sender = {}

        sender_id = (
            sender.get("user_id")
            or getattr(reply_comp, "sender_id", None)
            or getattr(reply_comp, "qq", None)
        )
        sender_name = (
            sender.get("card")
            or sender.get("nickname")
            or getattr(reply_comp, "sender_nickname", "")
            or (str(sender_id) if sender_id is not None else "未知用户")
        )
        return sender_id, sender_name, self.avatar_for_sender(sender_id, event)

    def avatar_for_sender(self, user_id: Any, event: Any) -> str:
        user_id = "" if user_id is None else str(user_id).strip()
        if user_id and user_id != "0":
            return f"https://q1.qlogo.cn/g?b=qq&nk={user_id}&s=640"
        try:
            return event.get_sender_avatar()
        except Exception:
            return ""

    def cq_unescape(self, value: Any) -> str:
        return html.unescape(str(value))

    def parse_cq_message_string(self, value: Any) -> list[dict[str, Any]]:
        text = "" if value is None else str(value)
        segments: list[dict[str, Any]] = []
        cursor = 0
        for match in re.finditer(r"\[CQ:([^,\]]+)((?:,[^\]]*)?)\]", text):
            if match.start() > cursor:
                segments.append({
                    "type": "text",
                    "data": {"text": self.cq_unescape(text[cursor:match.start()])},
                })

            seg_type = match.group(1).strip()
            data: dict[str, str] = {}
            params = match.group(2).lstrip(",")
            if params:
                for item in params.split(","):
                    if "=" not in item:
                        continue
                    key, raw_value = item.split("=", 1)
                    data[key.strip()] = self.cq_unescape(raw_value)
            segments.append({"type": seg_type, "data": data})
            cursor = match.end()

        if cursor < len(text):
            segments.append({
                "type": "text",
                "data": {"text": self.cq_unescape(text[cursor:])},
            })
        return segments

    def parse_json_payload(self, value: Any) -> Any:
        if _is_component(value, Json):
            value = value.data
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip().replace("&#44;", ",")
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return None
        return None

    def extract_text_from_multimsg_json(self, value: Any) -> str:
        parsed = self.parse_json_payload(value)
        if not isinstance(parsed, dict) or parsed.get("app") != "com.tencent.multimsg":
            return ""
        config = parsed.get("config")
        if isinstance(config, dict) and config.get("forward") != 1:
            return ""

        meta = parsed.get("meta")
        if not isinstance(meta, dict):
            return ""
        detail = meta.get("detail")
        news_items = detail.get("news") if isinstance(detail, dict) else None
        if not isinstance(news_items, list):
            return ""

        texts = []
        for item in news_items:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                cleaned = text.strip().replace("[图片]", "").strip()
                if cleaned:
                    texts.append(cleaned)
        return "\n".join(texts).strip()

    def extract_forward_id_from_multimsg_json(self, value: Any) -> str:
        parsed = self.parse_json_payload(value)
        if not isinstance(parsed, dict) or parsed.get("app") != "com.tencent.multimsg":
            return ""
        meta = parsed.get("meta")
        if not isinstance(meta, dict):
            return ""
        detail = meta.get("detail")
        if not isinstance(detail, dict):
            return ""
        for key in ("resid", "m_resid", "id"):
            forward_id = detail.get(key)
            if forward_id:
                return str(forward_id).strip()
        return ""

    def extract_plain_text_from_payload(self, payload: Any, depth: int = 0) -> str:
        if payload is None or depth > self.max_depth + 2:
            return ""
        if _is_component(payload, Plain):
            return payload.text or ""
        if _is_component(payload, Json):
            return self.extract_text_from_multimsg_json(payload.data)
        if isinstance(payload, str):
            return self.extract_plain_text_from_payload(
                self.parse_cq_message_string(payload),
                depth + 1,
            )
        if isinstance(payload, list):
            return "".join(
                self.extract_plain_text_from_payload(part, depth + 1)
                for part in payload
            )
        if isinstance(payload, dict):
            if "type" in payload:
                seg_type = str(payload.get("type", "")).lower()
                seg_data = payload.get("data", {})
                if not isinstance(seg_data, dict):
                    seg_data = {}
                if seg_type in {"text", "plain"}:
                    return str(seg_data.get("text") or "")
                if seg_type == "json":
                    return self.extract_text_from_multimsg_json(seg_data.get("data"))
                return ""

            data = self.unwrap_api_data(payload)
            chain = self.message_chain_from_payload(data)
            if chain is not None:
                return self.extract_plain_text_from_payload(chain, depth + 1)
            raw = data.get("raw_message")
            if isinstance(raw, str):
                return self.extract_plain_text_from_payload(raw, depth + 1)
        return ""

    def extract_first_image_file_id(self, payload: Any, depth: int = 0) -> str | None:
        if payload is None or depth > self.max_depth + 2:
            return None
        if _is_component(payload, Image):
            for candidate in (payload.file, payload.url, payload.path):
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
            return None
        if isinstance(payload, str):
            return self.extract_first_image_file_id(
                self.parse_cq_message_string(payload),
                depth + 1,
            )
        if isinstance(payload, list):
            for part in payload:
                image_ref = self.extract_first_image_file_id(part, depth + 1)
                if image_ref:
                    return image_ref
            return None
        if isinstance(payload, dict):
            if "type" in payload:
                seg_type = str(payload.get("type", "")).lower()
                seg_data = payload.get("data", {})
                if not isinstance(seg_data, dict):
                    seg_data = {}
                if seg_type == "image":
                    for key in ("file", "url", "path"):
                        value = seg_data.get(key)
                        if isinstance(value, str) and value.strip():
                            return value.strip()
                return None

            data = self.unwrap_api_data(payload)
            chain = self.message_chain_from_payload(data)
            if chain is not None:
                return self.extract_first_image_file_id(chain, depth + 1)
        return None

    def image_mime_from_base64(self, payload: str) -> str:
        sample = payload[:96]
        sample += "=" * (-len(sample) % 4)
        try:
            header = base64.b64decode(sample)
        except Exception:
            header = b""
        if header.startswith(b"\xff\xd8"):
            return "image/jpeg"
        if header.startswith(b"\x89PNG"):
            return "image/png"
        if header.startswith(b"GIF8"):
            return "image/gif"
        if header.startswith(b"RIFF") and b"WEBP" in header[:16]:
            return "image/webp"
        return "image/png"

    def base64_to_data_uri(self, value: Any) -> str:
        payload = str(value).strip()
        if payload.startswith("base64://"):
            payload = payload[len("base64://"):]
        payload = "".join(payload.split())
        if not payload:
            return ""
        return f"data:{self.image_mime_from_base64(payload)};base64,{payload}"

    def path_from_file_uri(self, uri: str) -> str:
        parsed = urlparse(uri)
        path = unquote(parsed.path)
        if os.name == "nt" and re.match(r"^/[A-Za-z]:", path):
            path = path[1:]
        return path

    def image_src_from_ref(self, image_ref: Any) -> str | None:
        if image_ref is None:
            return None
        raw = str(image_ref).strip()
        if not raw:
            return None
        if raw.startswith("data:"):
            return raw
        if raw.startswith("base64://"):
            return self.base64_to_data_uri(raw)
        if raw.startswith(("http://", "https://")):
            return raw
        if raw.startswith("file://"):
            local_path = self.path_from_file_uri(raw)
            if os.path.exists(local_path):
                return Path(local_path).resolve().as_uri()
            return raw
        if os.path.exists(raw):
            try:
                return Path(raw).resolve().as_uri()
            except Exception:
                return raw
        return None

    def image_refs_from_segment(self, segment: Any) -> list[str]:
        if _is_component(segment, Image):
            refs = []
            for candidate in (segment.url, segment.file, segment.path):
                if isinstance(candidate, str) and candidate.strip():
                    refs.append(candidate.strip())
            return refs

        if not isinstance(segment, dict):
            return []
        seg_data = segment.get("data", {})
        if not isinstance(seg_data, dict):
            return []

        refs = []
        for key in ("url", "file", "path"):
            value = seg_data.get(key)
            if isinstance(value, str) and value.strip():
                refs.append(value.strip())
        for key in ("base64", "data"):
            value = seg_data.get(key)
            if isinstance(value, str) and value.strip():
                value = value.strip()
                if value.startswith(("base64://", "data:")):
                    refs.append(value)
                else:
                    refs.append(f"base64://{value}")
        return refs

    def dedupe_strings(self, values: Any) -> list[str]:
        seen = set()
        result = []
        for value in values:
            if not isinstance(value, str):
                continue
            value = value.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
