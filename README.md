# astrbot_plugin_quote_collocter_plus
回复抽象发言自动入典

> Fork 自 [litsum/astrbot_plugin_quote_collocter](https://github.com/litsum/astrbot_plugin_quote_collocter)

##注意
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

## 引用文本转图（QQbox风格）
- 当你**引用一条纯文本消息**并发送`语录投稿`/`入典`时，插件会自动生成气泡语录图并入典。
- 当前渲染风格为 **QQbox**（头像 + 昵称 + 圆角气泡 + 尾巴 + 描边/阴影）。
- 仅替换“引用文本生成图”分支，不影响原有图片投稿、投稿权限、戳戳冷却与随机发送逻辑。

### 渲染配置（AstrBot 全局配置）
支持以下配置项：

- `quote_collector_plus_render_style`：渲染风格，默认 `qqbox`，可设为 `off`/`none` 关闭文本转图
- `quote_collector_plus_render_format`：导出格式，`jpg`（默认）或 `png`
- `quote_collector_plus_render_quality`：导出质量，范围 `1-100`（jpg 为正向质量；png 会反向映射为压缩等级：质量越高压缩越低）
- `quote_collector_plus_render_transparent_bg`：是否透明背景（主要对 png 生效）
- `quote_collector_plus_render_max_width`：文本最大排版宽度，默认 `720`
- `quote_collector_plus_render_max_lines`：文本最多行数，默认 `18`
- `quote_collector_plus_render_max_chars`：文本最大字符数，默认 `600`
- `quote_collector_plus_render_font_paths`：可选字体路径列表（列表或逗号分隔字符串）

### 文本排版与降级策略
- 自动按最大宽度换行，包含基础标点换行优化（避免部分标点落在不合适位置）
- 超长文本自动截断并追加省略号
- 空文本自动降级为 `（无文本内容）`
- 字体缺失时自动回退默认字体
- 头像下载/解析失败时自动使用默认头像底图
- Pillow 不可用时，仅“引用文本转图”分支给出可控提示，不影响其他功能

## 注意事项
图片投稿没有限制，请自己注意审核

## 依赖要求
- 必需：`PyYAML`、`aiohttp`
- 图像渲染：`Pillow`（已纳入 `requirements.txt`，建议直接安装全部依赖）

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
