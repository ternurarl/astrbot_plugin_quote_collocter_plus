# astrbot_plugin_quote_collocter_plus
回复抽象发言自动入典

> Fork 自 [litsum/astrbot_plugin_quote_collocter](https://github.com/litsum/astrbot_plugin_quote_collocter)

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

## 注意事项
图片投稿没有限制，请自己注意审核

## 投稿到 AstrBot 官方插件市场
如果你要把本插件提交到 AstrBot 官方插件市场，请按官方流程操作：

1. 先将你的插件代码发布到你自己的 GitHub 插件仓库。  
2. 打开官方插件市场：<https://plugins.astrbot.app>  
3. 点击右下角 `+`，填写插件信息（基础信息、作者信息、仓库信息等）。  
4. 点击 `Submit to GITHUB`，跳转到 AstrBot 主仓库的 Issue 提交页后，确认无误并点击 `Create` 完成投稿。  

> 说明：`AstrBotDevs/AstrBot_Plugins_Collection` 已不再接受 PR，请使用上述官方提交通道。
