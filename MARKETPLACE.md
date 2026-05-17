# 每日60秒新闻 - 插件市场提交说明

## 推荐分类

- Utility Tools
- External Integration

## 推荐标签

- daily-news
- 60s-news
- scheduler
- astrbot-port

## 迁移来源

本插件是 MaiBot 移植版，功能参考并移植自 AstrBot 插件 `anka-afk/astrbot_plugin_daily_news`。

- 原仓库：https://github.com/anka-afk/astrbot_plugin_daily_news
- 原许可：MIT License
- 移植说明：参考原插件的每日新闻能力与 API 设计，将 AstrBot 定时任务、命令和发送接口改为 MaiBot Hook 与 OneBot HTTP 发送。

## 上架备注

当前 `_manifest.json` 的 `urls.repository` 指向 MaiBot 移植版仓库；上游来源保留在 README 与 `THIRD_PARTY_NOTICES.md`。
