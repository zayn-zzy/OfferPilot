# OfferPilot 界面规范

采用 Mantine 8.3.18 的专业 SaaS App Screen 系统。石墨中性色、青绿强调色，支持浅色、深色与跟随系统；颜色、字体、间距、圆角来自 Mantine Theme 与全局语义变量。

- 全站业务页面共用 AppShell；桌面分组可折叠侧栏，移动端抽屉；当前路由高亮。
- 基础控件使用 Mantine，图标使用 Tabler，页面布局用 CSS Modules；不要重新手写基础输入框、菜单、弹窗。
- 页面标题 25–29px；表单与阅读区域有明确主次；不添加假指标、假来源、假聊天或工具记录。
- 创建表单按需进入 Drawer；岗位编辑仍在对应卡片内；审批的批准与执行分别显示。
- 错误和需核验信息保持可见，成功可通知；每项交互有 loading、disabled、error、empty 和 focus 状态。
- 只对透明度和 transform 使用短时动态；支持 reduced-motion；不动画改变布局尺寸。
- 13个路由与API、Cookie、幂等键、SSE、轮询及账户时区语义保持；不得把表单控件更换误当业务行为更换。
