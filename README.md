# 每日60秒新闻（MaiBot 移植版）

每天定时向 QQ 群推送每日 60 秒新闻，支持手动获取、管理员手动推送、图片/文字/图文模式。

## 迁移来源

本插件是 MaiBot 适配版，功能参考并移植自 AstrBot 插件：

- 原项目：`anka-afk/astrbot_plugin_daily_news`
- 原仓库：https://github.com/anka-afk/astrbot_plugin_daily_news
- 原许可：MIT License

本移植版将 AstrBot 的定时任务、命令与发送接口改为 MaiBot Hook + OneBot HTTP 发送方式。

## 功能

- 每天固定时间自动推送每日 60 秒新闻
- 支持手动获取新闻
- 支持管理员立即推送到配置群
- 支持图片、文字、图文三种模式
- 多个 60s API 域名自动降级

## 命令

- `/get_news`：当前会话获取图文新闻
- `/get_news image`：只发图片
- `/get_news text`：只发文字
- `/news`、`/每日新闻`：同 `/get_news`
- `/news_status`：查看下次推送时间
- `/push_news`：管理员手动推送到配置群

## 配置

主要配置位于 `config.toml`：

- `news.target_groups`：定时推送群号列表，公开版默认空列表；使用前请填写目标群号
- `news.push_time`：每天推送时间，默认 `08:00`
- `news.scheduled_mode`：定时推送模式，默认 `image`
- `news.admins`：允许执行 `/push_news` 的 QQ 号，公开版默认空列表；使用前请填写管理员 QQ
- `api.port`：OneBot HTTP API 端口，默认 `3000`

## 许可与署名

本移植版遵循 MIT License。第三方来源与许可见 `THIRD_PARTY_NOTICES.md`。
