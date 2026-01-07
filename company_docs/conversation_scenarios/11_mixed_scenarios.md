# 场景 11：混合复杂场景

## 场景描述

本场景涵盖结合多种能力（代码库、文件分析、文件生成、搜索）的复杂交互。

## 场景 A：从设计图到代码实现 (Vision + Codebase + FileGen)

用户发送 UI 设计图，要求根据现有代码库风格生成实现代码。

```
用户：[发送图片: 登录页设计稿.png]
用户：@gemini /codebase myproject 
Gemini：✅ 已设置代码库上下文: `myproject`

用户：@gemini /file-html 参考这个设计稿，并使用现有的组件库（查看 src/components），实现这个登录页面
Gemini：🔍 分析图片内容...
        🔍 检索代码库 `src/components`...
        
        云端链接: http://wecomfile.medmeeting.com/wecom/login_impl.html
        
        [内部逻辑]
        1. Vision 模型分析截图布局、颜色、文字
        2. RAG 检索 `src/components` 下的 Button, Input 等组件用法
        3. 结合两者生成符合项目规范的 HTML
```

## 场景 B：基于日志截图的 Bug 修复 (Vision + Codebase)

用户发送报错截图，Bot 结合代码库定位问题并给出修复建议。

```
用户：[发送图片: 报错堆栈截图.png]
用户：@gemini /codebase myproject 这个错是哪里的问题？
Gemini：🔍 分析截图文本 "NullPointerException at UserService.java:45"...
        🔍 定位代码库 `src/main/java/.../UserService.java` 第 45 行...
        
        分析结果：
        错误发生在 `getUserInfo` 方法中。截图显示 `userDao` 为空。
        
        可能原因：
        `UserService` 初始化时未通过依赖注入正确注入 `UserDao`。
        
        修复建议：
        请检查 `application-context.xml` 或 `@Autowired` 注解...
```

## 场景 C：文档驱动的代码生成 (FileAnalysis + FileGen)

用户上传需求文档 (PDF)，Bot 生成对应的代码文件。

```
用户：[发送 PDF: API接口定义文档.pdf]
用户：@gemini /file-html 根据这个文档生成 Swagger/OpenAPI 定义文件
Gemini：🔍 阅读 PDF 文档...
        
        云端链接: http://wecomfile.medmeeting.com/wecom/openapi.yaml
        (虽然指令是 /file-html，但内容是 yaml，浏览器可预览或下载)
```

## 场景 D：跨 Bot 协作 (Multi-Bot)

利用不同 Bot 的专长进行协作。

```
用户：@gemini /codebase myproject 分析一下 `src/algo/ranking.py` 的算法复杂度
Gemini：(Gemini 1.5 Pro 擅长长上下文代码分析)
        该算法的时间复杂度是 O(n^2)... 存在性能瓶颈...

用户：@chatgpt 针对 Gemini 指出的 O(n^2) 瓶颈，给出一个优化方案
ChatGPT：(GPT-4 擅长算法优化)
        可以优化为 O(n log n)，方法是使用归并排序...
        ```python
        def optimized_ranking(items):
            ...
        ```

用户：@grok 这个优化在 Python 3.12 下运行快吗？
Grok：(X.AI 擅长实时信息/最新技术栈)
        在 Python 3.12 中，由于自适应解释器的引入，这种写法...
```

## 场景 E：搜索驱动的回答 (WebSearch + Chat)

用户问最近的新闻或技术动态，Bot 联网搜索后回答。

```
用户：@grok Android 16 有什么新特性？
Grok：(联网搜索)
        Android 16 预计将引入... 
        [引用来源 1] [引用来源 2]
```

## 技术难点

1. **上下文传递**：不同能力（Vision, RAG, FileGen）共享同一个 Context Window，需要精细的 Token 管理。
2. **多模态对齐**：如何确保"图片里的按钮"和"代码库里的 Button 组件"对应上？
3. **指令组合**：用户可能把指令混合写，如 `/codebase myproject /file-html ...`（需支持或明确不支持）。

## 目前支持情况

| 组合 | 支持状态 | 备注 |
|-----|---------|-----|
| Vision + Codebase | ✅ | 上下文支持图片 + RAG |
| Vision + FileGen | ✅ | 上下文支持图片 + 生成指令 |
| PDF + FileGen | ✅ | 上下文支持 PDF + 生成指令 |
| Bot 间协作 | ✅ | 通过共享 Context 实现 |
| WebSearch | ❌ | 尚未集成 (Grok 原生支持但 API 可能受限) |

## 场景 F：每日可视化报告生成 (Archive + FileGen)

用户要求以 HTML 报告形式总结当天的群聊内容，要求包含话题汇总、待办事项、精准跳转。

```
用户：@gemini /file-html 基于今天的群聊内容，生成html报告发给我（包括话题汇总、待办事项、当天成果等，并且能够精准定位到单条聊天记录）

Gemini：(1. 调用 Archive Tool 获取今日消息)
        (2. 分析提取 topics, todos, achievements)
        (3. 生成包含 Tailwind CSS 的 HTML 报告)
        
        云端链接: http://wecomfile.medmeeting.com/archive/daily_report_20250107.html
        
        **报告特性**：
        - 📊 **可视化仪表盘**：使用 Chart.js 展示活跃度趋势
        - 📝 **话题卡片**：按话题聚类消息
        - ✅ **待办清单**：提取 @人名 的任务
        - 🔗 **精准定位**：每条摘要后附带 `[查看原消息]` 链接 
          (实现原理：链接指向 `/archive/viewer?msgid=xxx` 或使用 WeCom 引用格式)
```
