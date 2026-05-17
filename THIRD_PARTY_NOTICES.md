# Third Party Notices

## anka-afk/astrbot_plugin_daily_news

- Source: https://github.com/anka-afk/astrbot_plugin_daily_news
- License: MIT License
- Usage in this MaiBot port:
  - Reused the feature design and 60s news API fallback list
  - Reimplemented scheduling, commands and message sending for MaiBot SDK and OneBot HTTP

## 60s API

- API: https://60s.viki.moe/v2/60s
- Project mentioned by API response: https://github.com/vikiboss/60s

This plugin depends on public 60s news API availability. For production use, consider a private deployment if public quota or compatibility changes.
