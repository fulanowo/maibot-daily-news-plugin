# -*- coding: utf-8 -*-
"""Daily 60-second news plugin for MaiBot SDK 2.x."""
from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import urllib.parse
from pathlib import Path
from typing import Any, ClassVar

import aiohttp
from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase
from maibot_sdk.types import HookMode, HookOrder


API_URLS = (
    "https://60s.viki.moe/v2/60s",
    "https://60s.b23.run/v2/60s",
    "https://60s-api-cf.viki.moe/v2/60s",
    "https://60s-api.114128.xyz/v2/60s",
    "https://60s-api-cf.114128.xyz/v2/60s",
)

# 显式声明可解码的压缩算法：部分环境下 aiohttp 与 brotli 库接口不匹配，
# 服务器返回 br 时会直接抛 "Can not decode content-encoding: br"。
REQUEST_HEADERS = {"Accept-Encoding": "gzip, deflate"}


class PluginSectionConfig(PluginConfigBase):
    __ui_label__ = "插件"
    __ui_order__ = 0

    enabled: bool = Field(default=True, description="是否启用插件")
    config_version: str = Field(default="1.0.0", description="配置版本")


class NewsSectionConfig(PluginConfigBase):
    __ui_label__ = "每日新闻"
    __ui_order__ = 1

    target_groups: list[str] = Field(default_factory=list, description="定时推送目标 QQ 群")
    push_time: str = Field(default="08:00", description="每天推送时间，服务器时区，例如 08:00")
    scheduled_mode: str = Field(default="image", description="定时推送模式：image/text/all")
    command_prefixes: list[str] = Field(default=["/get_news", "/news", "/每日新闻"], description="手动获取新闻命令")
    admin_push_commands: list[str] = Field(default=["/push_news"], description="管理员推送到配置群命令")
    status_commands: list[str] = Field(default=["/news_status"], description="查看状态命令")
    admins: list[str] = Field(default_factory=list, description="可手动全局推送的 QQ 号")
    timeout_seconds: int = Field(default=30, description="请求超时秒数", ge=5, le=120)


class ApiSectionConfig(PluginConfigBase):
    __ui_label__ = "OneBot API"
    __ui_order__ = 2

    host: str = Field(default="127.0.0.1", description="OneBot HTTP API 主机")
    port: int = Field(default=3000, description="OneBot HTTP API 端口", ge=1, le=65535)
    token: str = Field(default="", description="OneBot HTTP API Token")


class DailyNewsConfig(PluginConfigBase):
    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    news: NewsSectionConfig = Field(default_factory=NewsSectionConfig)
    api: ApiSectionConfig = Field(default_factory=ApiSectionConfig)


class DailyNewsPlugin(MaiBotPlugin):
    config_model: ClassVar[type[PluginConfigBase] | None] = DailyNewsConfig

    _task: asyncio.Task[None] | None = None
    _data_dir: Path | None = None

    async def on_load(self) -> None:
        self._data_dir = Path(__file__).resolve().parents[2] / "data" / "daily_news_plugin"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        if self.config.plugin.enabled:
            self._task = asyncio.create_task(self._daily_loop(), name="daily-news-loop")
            self.ctx.logger.info("Daily news plugin loaded, next push in %.1f hours", self._seconds_until_next_push() / 3600)

    async def on_unload(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        self.ctx.logger.info("Daily news plugin unloaded")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        del scope, config_data
        self.ctx.logger.info("Daily news config updated to %s; restart plugin to reschedule", version)

    @HookHandler(
        hook="chat.receive.after_process",
        name="daily_news_command_hook",
        description="每日 60 秒新闻命令",
        mode=HookMode.BLOCKING,
        order=HookOrder.EARLY,
    )
    async def handle_command(self, **kwargs) -> dict[str, Any] | None:
        if not self.config.plugin.enabled:
            return None

        message: dict[str, Any] = kwargs.get("message", {}) or {}
        text = str(message.get("processed_plain_text", "") or "").strip()
        if not text:
            return None

        mode = self._extract_mode(text)
        if self._starts_with_any(text, self.config.news.status_commands):
            await self._send_text_to_origin(message, self._status_text())
            return {"action": "abort"}

        if self._starts_with_any(text, self.config.news.command_prefixes):
            await self._send_news_to_origin(message, mode)
            return {"action": "abort"}

        if self._starts_with_any(text, self.config.news.admin_push_commands):
            if not self._is_admin(message):
                await self._send_text_to_origin(message, "只有管理员可以全局推送每日新闻。")
                return {"action": "abort"}
            await self.push_to_configured_groups(mode)
            await self._send_text_to_origin(message, f"已推送每日新闻到 {len(self.config.news.target_groups)} 个群。")
            return {"action": "abort"}

        return None

    async def push_to_configured_groups(self, mode: str | None = None) -> None:
        news_data = await self._fetch_news_data()
        mode = self._normalize_mode(mode or self.config.news.scheduled_mode)
        image_path: Path | None = None
        if mode in {"image", "all"}:
            image_path = await self._download_image(news_data)

        for group_id in self.config.news.target_groups:
            group_id = str(group_id).strip()
            if not group_id:
                continue
            if image_path is not None:
                await self._send_group_image(group_id, image_path)
            if mode in {"text", "all"}:
                await self._send_group_text(group_id, self._format_news_text(news_data))
            await asyncio.sleep(1)

    async def _send_news_to_origin(self, message: dict[str, Any], mode: str | None) -> None:
        news_data = await self._fetch_news_data()
        mode = self._normalize_mode(mode or "all")
        if mode in {"image", "all"}:
            image_path = await self._download_image(news_data)
            await self._send_image_to_origin(message, image_path)
        if mode in {"text", "all"}:
            await self._send_text_to_origin(message, self._format_news_text(news_data))

    async def _daily_loop(self) -> None:
        while True:
            try:
                seconds = self._seconds_until_next_push()
                self.ctx.logger.info("Daily news next push in %.2f hours", seconds / 3600)
                await asyncio.sleep(seconds)
                await self.push_to_configured_groups(self.config.news.scheduled_mode)
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ctx.logger.warning("Daily news scheduled push failed: %s", exc)
                await asyncio.sleep(300)

    async def _fetch_news_data(self) -> dict[str, Any]:
        timeout = aiohttp.ClientTimeout(total=int(self.config.news.timeout_seconds))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            last_error = ""
            for url in API_URLS:
                try:
                    async with session.get(url, headers=REQUEST_HEADERS) as response:
                        if response.status != 200:
                            last_error = f"{url} HTTP {response.status}"
                            continue
                        payload = await response.json()
                        data = payload.get("data")
                        if isinstance(data, dict):
                            return data
                        last_error = f"{url} missing data"
                except Exception as exc:
                    last_error = f"{url}: {exc}"
                    continue
        raise RuntimeError(f"每日新闻数据获取失败：{last_error}")

    async def _download_image(self, news_data: dict[str, Any]) -> Path:
        image_url = str(news_data.get("image") or news_data.get("cover") or "").strip()
        if not image_url:
            raise RuntimeError("每日新闻没有可用图片")
        date = str(news_data.get("date") or dt.date.today().isoformat())
        path = (self._data_dir or Path("/tmp")) / f"daily_news_{date}.png"
        if path.exists() and path.stat().st_size > 0:
            return path

        timeout = aiohttp.ClientTimeout(total=int(self.config.news.timeout_seconds))
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(image_url, headers=REQUEST_HEADERS) as response:
                if response.status != 200:
                    raise RuntimeError(f"每日新闻图片下载失败：HTTP {response.status}")
                data = await response.read()
        path.write_bytes(data)
        return path

    def _format_news_text(self, news_data: dict[str, Any]) -> str:
        date = str(news_data.get("date") or "")
        day = str(news_data.get("day_of_week") or "")
        news_items = news_data.get("news") or []
        tip = str(news_data.get("tip") or "")
        lines = [f"【每日60秒新闻】{date} {day}".strip(), ""]
        for index, item in enumerate(news_items, start=1):
            lines.append(f"{index}. {item}")
        if tip:
            lines.extend(["", f"【今日提示】{tip}"])
        lines.append("数据来源：每日60秒新闻")
        return "\n".join(lines)

    def _status_text(self) -> str:
        seconds = self._seconds_until_next_push()
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return (
            "每日60秒新闻插件正在运行\n"
            f"目标群：{', '.join(map(str, self.config.news.target_groups)) or '未配置'}\n"
            f"推送时间：{self.config.news.push_time}\n"
            f"定时模式：{self.config.news.scheduled_mode}\n"
            f"距离下次推送：{hours}小时{minutes}分钟"
        )

    def _seconds_until_next_push(self) -> float:
        now = dt.datetime.now()
        try:
            hour, minute = [int(part) for part in str(self.config.news.push_time).split(":", 1)]
        except Exception:
            hour, minute = 8, 0
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += dt.timedelta(days=1)
        return max(1.0, (target - now).total_seconds())

    async def _send_text_to_origin(self, message: dict[str, Any], text: str) -> bool:
        if self._is_private_message(message):
            user_id = self._get_user_id(message)
            if not user_id:
                return False
            return await self._post_onebot("/send_private_msg", {"user_id": user_id, "message": [{"type": "text", "data": {"text": text}}]})
        group_id = self._get_group_id(message)
        if not group_id:
            return False
        return await self._send_group_text(group_id, text)

    async def _send_image_to_origin(self, message: dict[str, Any], path: Path) -> bool:
        if self._is_private_message(message):
            user_id = self._get_user_id(message)
            if not user_id:
                return False
            return await self._post_onebot("/send_private_msg", {"user_id": user_id, "message": [self._image_segment(path)]})
        group_id = self._get_group_id(message)
        if not group_id:
            return False
        return await self._send_group_image(group_id, path)

    async def _send_group_text(self, group_id: str, text: str) -> bool:
        return await self._post_onebot("/send_group_msg", {"group_id": group_id, "message": [{"type": "text", "data": {"text": text}}]})

    async def _send_group_image(self, group_id: str, path: Path) -> bool:
        return await self._post_onebot("/send_group_msg", {"group_id": group_id, "message": [self._image_segment(path)]})

    async def _post_onebot(self, endpoint: str, payload: dict[str, Any]) -> bool:
        token = str(self.config.api.token or "").strip()
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        url = f"http://{self.config.api.host}:{self.config.api.port}{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60) as response:
                    body = await response.text()
                    if response.status in (401, 403) and token:
                        retry_url = f"{url}?access_token={urllib.parse.quote(token)}"
                        async with session.post(retry_url, json=payload, headers=headers, timeout=60) as retry:
                            retry_body = await retry.text()
                            if retry.status != 200:
                                self.ctx.logger.warning("OneBot retry failed: HTTP %s %s", retry.status, retry_body)
                                return False
                            return self._check_onebot_result(endpoint, retry_body)
                    if response.status != 200:
                        self.ctx.logger.warning("OneBot request failed: HTTP %s %s", response.status, body)
                        return False
                    return self._check_onebot_result(endpoint, body)
        except Exception as exc:
            self.ctx.logger.warning("OneBot request error: %s", exc)
            return False

    def _check_onebot_result(self, endpoint: str, body: str) -> bool:
        """检查 OneBot 响应体：业务失败常以 HTTP 200 + status=failed 返回，只看状态码会漏报。"""
        try:
            result = json.loads(body)
        except ValueError:
            return True
        if not isinstance(result, dict):
            return True
        status = str(result.get("status") or "ok").lower()
        if status in {"ok", "async"}:
            return True
        self.ctx.logger.warning(
            "OneBot %s 发送失败: status=%s retcode=%s message=%s",
            endpoint,
            status,
            result.get("retcode"),
            result.get("message") or result.get("wording") or result.get("msg") or "",
        )
        return False

    @staticmethod
    def _image_segment(path: Path) -> dict[str, Any]:
        """图片消息段内联 base64，避免 OneBot 服务与插件不在同一文件系统（容器/跨机）时读不到文件。"""
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return {"type": "image", "data": {"file": f"base64://{encoded}"}}

    @staticmethod
    def _starts_with_any(text: str, prefixes: list[str]) -> bool:
        return any(text == prefix or text.startswith(prefix + " ") for prefix in prefixes)

    @staticmethod
    def _extract_mode(text: str) -> str | None:
        parts = text.split()
        if len(parts) < 2:
            return None
        return parts[1].strip().lower()

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        mode = str(mode or "all").strip().lower()
        if mode in {"image", "img", "图片"}:
            return "image"
        if mode in {"text", "txt", "文字"}:
            return "text"
        return "all"

    def _is_admin(self, message: dict[str, Any]) -> bool:
        user_id = self._get_user_id(message)
        return bool(user_id) and user_id in {str(item) for item in self.config.news.admins}

    @staticmethod
    def _is_private_message(message: dict[str, Any]) -> bool:
        message_info = message.get("message_info", {})
        return bool(message_info) and message_info.get("group_info") is None

    @staticmethod
    def _get_user_id(message: dict[str, Any]) -> str | None:
        message_info = message.get("message_info", {})
        user_info = message_info.get("user_info", {}) if isinstance(message_info, dict) else {}
        user_id = user_info.get("user_id") if isinstance(user_info, dict) else None
        return str(user_id) if user_id else None

    @staticmethod
    def _get_group_id(message: dict[str, Any]) -> str | None:
        message_info = message.get("message_info", {})
        group_info = message_info.get("group_info") if isinstance(message_info, dict) else None
        group_id = group_info.get("group_id") if isinstance(group_info, dict) else None
        return str(group_id) if group_id else None


def create_plugin() -> DailyNewsPlugin:
    return DailyNewsPlugin()
