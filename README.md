# astrbot_plugin_quote_collocter_plus
回复抽象发言自动入典

> Fork 自 [litsum/astrbot_plugin_quote_collocter](https://github.com/litsum/astrbot_plugin_quote_collocter)

## 注意
本插件由AI史量级生成,有问题请直接转给AI

## 使用方法
发送"语录投稿+图片"或者"入典+图片"，bot会将群u语录保存到本地（不同群聊相互隔离）  
如果你的qq未开启半屏相册发图功能，可以通过【qq左划→设置→通用→图片、视频→发图方式】进行修改  
权限系统可以通过发送"投稿权限+模式数字"进行设置  
   0：关闭投稿系统  
   1：仅管理员可投稿  
   2：全体成员均可投稿  

在bot被戳一戳时，将会随机选择一张黑历史发送（有10秒默认冷却）  
如果想要修改这个冷却，请发送"戳戳冷却+冷却时间"来设置，单位为秒  
发送"/语录"或"语录"可以主动触发随机语录  

## 引用文本转图（html_render + Jinja2 模板）
- 当你**引用一条纯文本消息**并发送`语录投稿`/`入典`时，插件会自动生成气泡语录图并入典。
- 当前渲染风格为 **统一左侧白色气泡**（头像 + 昵称 + 左侧白色气泡）。
- 仅替换“引用文本生成图”分支，不影响原有图片投稿、投稿权限、戳戳冷却与随机发送逻辑。

### 渲染配置（AstrBot 全局配置）
支持以下配置项：

- `quote_collector_plus_render_style`：渲染风格，默认 `white_bubble`，可设为 `off`/`none` 关闭文本转图
- `quote_collector_plus_render_max_lines`：文本最多行数，默认 `18`
- `quote_collector_plus_render_max_chars`：文本最大字符数，默认 `600`
- `quote_collector_plus_render_use_sender_avatar`：是否使用被引用消息发送者 QQ 头像，默认 `true`
- `quote_collector_plus_render_default_avatar`：关闭发送者头像时使用的默认头像 URL

### 文本处理与降级策略
- 超长文本自动截断并追加省略号
- 空文本自动降级为 `（无文本内容）`
- 头像 URL 支持发送者 QQ 头像或配置默认头像
- 渲染结果同时兼容本地文件路径与 URL 返回值
- html_render 不可用时，仅“引用文本转图”分支给出可控提示，不影响其他功能

## 注意事项
图片投稿没有限制，请自己注意审核

## 依赖要求
- 必需：`PyYAML`、`aiohttp`

安装示例：

```bash
pip install -r requirements.txt
```

## 数据目录配置（Windows / Docker）
插件会将图片与群配置统一存放在：

`<data_root>/quotes_data/<group_id>/`

其中 `data_root` 的优先级如下：
1. AstrBot 配置项：`quote_collector_plus_data_root`（兼容旧拼写 `quote_collocter_plus_data_root`）
2. 环境变量：`QUOTE_COLLECTOR_PLUS_DATA_ROOT`（兼容旧拼写 `QUOTE_COLLOCTER_PLUS_DATA_ROOT`）
3. 自动识别：若插件位于 `.../data/plugins/<plugin>`，则默认使用上级 `.../data`
4. 兜底默认值：`data`（即默认目录为 `data/quotes_data/...`）

插件启动时会输出最终生效的绝对路径，并检查目录是否可写。

### Windows 部署建议
- 建议将 `data_root` 指向固定目录（例如 `D:\astrbot_data`），避免工作目录变化导致数据分散。
- 请确保运行账号对该目录有读写权限。

### Docker 部署建议
- AstrBot 官方 compose 默认挂载为：`./data:/AstrBot/data`。
- 本插件在该官方部署方式下可开箱即用，无需额外配置环境变量。
- 若你自定义了挂载目录，再按需设置 `QUOTE_COLLECTOR_PLUS_DATA_ROOT`。

### 迁移说明
- 若你此前使用默认 `data/quotes_data`，可直接将旧目录整体拷贝到新的 `<data_root>/quotes_data` 下完成迁移。
- 目录结构保持不变即可，无需改动群号子目录内容。

## 兼容说明
- 数据路径规则与历史版本保持兼容（包含旧配置键兼容）。
- 命令触发方式保持兼容：`语录投稿` / `入典` / `投稿权限` / `戳戳冷却` / `/语录`。
