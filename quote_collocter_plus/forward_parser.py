from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from .message_parser import MessageParser
from .models import RenderNode
from .onebot import OneBotClient

try:
    from astrbot.core.message.components import At, Forward, Image, Json, Node, Nodes, Plain
except Exception:  # pragma: no cover - only used outside an AstrBot runtime.
    At = Forward = Image = Json = Node = Nodes = Plain = None


def _is_component(value: Any, component_type: Any) -> bool:
    return component_type is not None and isinstance(value, component_type)


class ForwardParser:
    def __init__(
        self,
        parser: MessageParser,
        onebot: OneBotClient,
        resolve_image_src: Callable[[Any, Any], Awaitable[str | None]],
        logger: Any = None,
        max_depth: int = 3,
    ):
        self.parser = parser
        self.onebot = onebot
        self.resolve_image_src = resolve_image_src
        self.logger = logger
        self.max_depth = max_depth

    def _debug(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "debug"):
            self.logger.debug(message)

    def _info(self, message: str) -> None:
        if self.logger and hasattr(self.logger, "info"):
            self.logger.info(message)

    def looks_like_forward_node(self, value: Any) -> bool:
        if _is_component(value, Node):
            return True
        if not isinstance(value, dict):
            return False
        if str(value.get("type", "")).lower() == "node":
            return True
        if "type" in value:
            return False
        return (
            isinstance(value.get("sender"), dict)
            or "content" in value
            or "message" in value
        )

    def forward_node_list_from_payload(self, payload: Any) -> list[Any] | None:
        data = self.parser.unwrap_api_data(payload)
        for key in ("messages", "message", "nodes", "nodeList"):
            value = data.get(key)
            if isinstance(value, list) and any(self.looks_like_forward_node(item) for item in value):
                return value
        return None

    async def fetch_forward_render_nodes(
        self,
        event: Any,
        forward_id: Any,
        group_id: str,
        depth: int,
        visited: set[str],
    ) -> list[RenderNode]:
        forward_id = str(forward_id).strip()
        if not forward_id or forward_id in visited or depth > self.max_depth:
            return []
        visited.add(forward_id)

        last_error = None
        for payload in ({"id": forward_id}, {"message_id": forward_id}):
            try:
                result = await self.onebot.get_forward_msg(event, **payload)
                nodes = await self.extract_forward_render_nodes(
                    event,
                    result,
                    group_id,
                    depth=depth + 1,
                    visited=visited,
                )
                if nodes:
                    return nodes
            except Exception as e:
                last_error = e
                self._debug(f"获取合并转发消息失败: {e}, payload={payload}")

        if last_error:
            self._info(f"无法获取合并转发消息: id={forward_id}, error={last_error}")
        return []

    async def extract_forward_render_nodes(
        self,
        event: Any,
        payload: Any,
        group_id: str,
        depth: int = 0,
        visited: set[str] | None = None,
    ) -> list[RenderNode]:
        if visited is None:
            visited = set()
        if payload is None or depth > self.max_depth:
            return []

        if _is_component(payload, Forward):
            return await self.fetch_forward_render_nodes(event, payload.id, group_id, depth, visited)
        if _is_component(payload, Nodes):
            nodes: list[RenderNode] = []
            for node in payload.nodes:
                nodes.extend(await self.parse_component_forward_node(event, node, group_id, depth, visited))
            return nodes
        if _is_component(payload, Node):
            return await self.parse_component_forward_node(event, payload, group_id, depth, visited)
        if _is_component(payload, Json):
            forward_id = self.parser.extract_forward_id_from_multimsg_json(payload.data)
            if forward_id:
                return await self.fetch_forward_render_nodes(event, forward_id, group_id, depth, visited)
            return []
        if isinstance(payload, str):
            return await self.extract_forward_render_nodes(
                event,
                self.parser.parse_cq_message_string(payload),
                group_id,
                depth=depth + 1,
                visited=visited,
            )
        if isinstance(payload, list):
            nodes = []
            for part in payload:
                nodes.extend(await self.extract_forward_render_nodes(
                    event,
                    part,
                    group_id,
                    depth=depth,
                    visited=visited,
                ))
            return nodes
        if not isinstance(payload, dict):
            return []

        if "type" in payload:
            return await self.extract_forward_nodes_from_segment(
                event,
                payload,
                group_id,
                depth,
                visited,
            )

        data = self.parser.unwrap_api_data(payload)
        node_list = self.forward_node_list_from_payload(data)
        if node_list:
            nodes = []
            for node in node_list:
                nodes.extend(await self.parse_onebot_forward_node(event, node, group_id, depth, visited))
            return nodes

        chain = self.parser.message_chain_from_payload(data)
        if chain is not None:
            return await self.extract_forward_render_nodes(
                event,
                chain,
                group_id,
                depth=depth + 1,
                visited=visited,
            )
        return []

    async def extract_forward_nodes_from_segment(
        self,
        event: Any,
        segment: dict[str, Any],
        group_id: str,
        depth: int,
        visited: set[str],
    ) -> list[RenderNode]:
        seg_type = str(segment.get("type", "")).lower()
        seg_data = segment.get("data", {})
        if not isinstance(seg_data, dict):
            seg_data = {}

        if seg_type in {"forward", "forward_msg"}:
            forward_id = seg_data.get("id") or seg_data.get("message_id")
            if forward_id:
                return await self.fetch_forward_render_nodes(event, forward_id, group_id, depth, visited)
            for key in ("content", "nodes", "messages", "message", "nodeList"):
                value = seg_data.get(key)
                if isinstance(value, list):
                    return await self.extract_forward_render_nodes(
                        event,
                        {"nodes": value},
                        group_id,
                        depth=depth + 1,
                        visited=visited,
                    )
            return []

        if seg_type == "node":
            return await self.parse_onebot_forward_node(event, segment, group_id, depth, visited)

        if seg_type == "nodes":
            node_list = (
                seg_data.get("nodes")
                or seg_data.get("content")
                or seg_data.get("messages")
                or seg_data.get("message")
                or seg_data.get("nodeList")
            )
            if isinstance(node_list, list):
                nodes = []
                for node in node_list:
                    nodes.extend(await self.parse_onebot_forward_node(event, node, group_id, depth, visited))
                return nodes
            return []

        if seg_type == "json":
            forward_id = self.parser.extract_forward_id_from_multimsg_json(seg_data.get("data"))
            if forward_id:
                return await self.fetch_forward_render_nodes(event, forward_id, group_id, depth, visited)
        return []

    async def parse_component_forward_node(
        self,
        event: Any,
        node: Any,
        group_id: str,
        depth: int,
        visited: set[str],
    ) -> list[RenderNode]:
        text, images, nested_nodes = await self.parse_forward_node_content(
            event,
            getattr(node, "content", []),
            group_id,
            depth,
            visited,
        )
        current = self.build_forward_render_node(
            event,
            name=getattr(node, "name", "") or getattr(node, "uin", ""),
            user_id=getattr(node, "uin", ""),
            text=text,
            images=images,
        )
        return current + nested_nodes

    async def parse_onebot_forward_node(
        self,
        event: Any,
        node: Any,
        group_id: str,
        depth: int,
        visited: set[str],
    ) -> list[RenderNode]:
        if _is_component(node, Node):
            return await self.parse_component_forward_node(event, node, group_id, depth, visited)
        if not isinstance(node, dict):
            return []

        raw_node = node.get("data") if str(node.get("type", "")).lower() == "node" else node
        if not isinstance(raw_node, dict):
            return []

        sender = raw_node.get("sender")
        if not isinstance(sender, dict):
            sender = {}
        user_id = (
            sender.get("user_id")
            or raw_node.get("user_id")
            or raw_node.get("uin")
            or raw_node.get("qq")
        )
        name = (
            sender.get("card")
            or sender.get("nickname")
            or raw_node.get("nickname")
            or raw_node.get("name")
            or (str(user_id) if user_id is not None else "未知用户")
        )

        content = raw_node.get("message")
        if content is None:
            content = raw_node.get("content")
        if content is None:
            content = raw_node.get("messages")

        text, images, nested_nodes = await self.parse_forward_node_content(
            event,
            content,
            group_id,
            depth,
            visited,
        )
        current = self.build_forward_render_node(
            event,
            name=name,
            user_id=user_id,
            text=text,
            images=images,
        )
        return current + nested_nodes

    async def parse_forward_node_content(
        self,
        event: Any,
        content: Any,
        group_id: str,
        depth: int,
        visited: set[str],
    ) -> tuple[str, list[str], list[RenderNode]]:
        text_parts: list[str] = []
        images: list[str] = []
        nested_nodes: list[RenderNode] = []

        async def consume(item: Any) -> None:
            if item is None:
                return
            if _is_component(item, Plain):
                if item.text:
                    text_parts.append(item.text)
                return
            if _is_component(item, At):
                target = item.name or item.qq
                if target:
                    text_parts.append(f"@{target}")
                return
            if _is_component(item, Image):
                for image_ref in self.parser.image_refs_from_segment(item):
                    src = await self.resolve_image_src(event, image_ref)
                    if src:
                        images.append(src)
                return
            if (
                _is_component(item, Forward)
                or _is_component(item, Node)
                or _is_component(item, Nodes)
                or _is_component(item, Json)
            ):
                nested_nodes.extend(await self.extract_forward_render_nodes(
                    event,
                    item,
                    group_id,
                    depth=depth + 1,
                    visited=visited,
                ))
                return
            if isinstance(item, str):
                raw = item.strip()
                if not raw:
                    return
                parsed = None
                if raw[0] in "[{":
                    try:
                        parsed = json.loads(raw.replace("&#44;", ","))
                    except Exception:
                        parsed = None
                if isinstance(parsed, (list, dict)):
                    await consume(parsed)
                else:
                    await consume(self.parser.parse_cq_message_string(raw))
                return
            if isinstance(item, list):
                for part in item:
                    await consume(part)
                return
            if not isinstance(item, dict):
                return

            if "type" in item:
                seg_type = str(item.get("type", "")).lower()
                seg_data = item.get("data", {})
                if not isinstance(seg_data, dict):
                    seg_data = {}

                if seg_type in {"text", "plain"}:
                    text = seg_data.get("text")
                    if isinstance(text, str) and text:
                        text_parts.append(text)
                    return
                if seg_type == "at":
                    target = seg_data.get("name") or seg_data.get("qq")
                    if target:
                        text_parts.append(f"@{target}")
                    return
                if seg_type == "image":
                    for image_ref in self.parser.image_refs_from_segment(item):
                        src = await self.resolve_image_src(event, image_ref)
                        if src:
                            images.append(src)
                    return
                if seg_type in {"forward", "forward_msg", "node", "nodes", "json"}:
                    nested_nodes.extend(await self.extract_forward_render_nodes(
                        event,
                        item,
                        group_id,
                        depth=depth + 1,
                        visited=visited,
                    ))
                    return
                return

            if self.looks_like_forward_node(item):
                nested_nodes.extend(await self.parse_onebot_forward_node(
                    event,
                    item,
                    group_id,
                    depth + 1,
                    visited,
                ))
                return

            for key in ("message", "content", "messages"):
                value = item.get(key)
                if isinstance(value, (list, str, dict)):
                    await consume(value)
                    return

        await consume(content)
        return "".join(text_parts).strip(), self.parser.dedupe_strings(images), nested_nodes

    def build_forward_render_node(
        self,
        event: Any,
        name: Any,
        user_id: Any,
        text: Any,
        images: Any,
    ) -> list[RenderNode]:
        text = "" if text is None else str(text).strip()
        images = self.parser.dedupe_strings(images)
        if not text and not images:
            return []
        name = "" if name is None else str(name).strip()
        user_id = "" if user_id is None else str(user_id).strip()
        if not name:
            name = user_id or "未知用户"
        return [RenderNode(
            name=name,
            avatar=self.parser.avatar_for_sender(user_id, event),
            text=text,
            images=images,
        )]
