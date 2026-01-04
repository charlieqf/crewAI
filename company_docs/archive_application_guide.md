# 企业微信会话存档申请材料

## 申请背景

**业务需求：** 在企业微信群聊中实现AI助手（@gemini）自动读取和分析文件

**现有问题：**
- ❌ 企业微信群聊**不支持**在同一条消息中发送文件和@提及
- ❌ 必须分两条消息发送，导致文件与AI提问分离
- ❌ 现有的Quote和10分钟窗口方案在群聊中**基本不可用**

**解决方案：** 使用会话存档API实时获取群聊消息和文件

---

## 申请清单

### ✅ 第一步：了解费用（必须）

**联系渠道：**
1. 点击申请页面的"咨询"按钮
2. 或拨打企业微信客服：400-900-7899
3. 或联系企业微信客户经理

**需要咨询的问题：**
```
1. 会话存档按什么计费？
   - 按存储容量？
   - 按消息条数？
   - 按用户数？

2. 预估费用是多少？
   - 我们企业约 X 人
   - 主要用于 Y 个群聊
   - 预计月消息量 Z 条

3. 是否有试用期？

4. 最低购买周期是多久？（月付/年付）

5. 是否需要额外的服务器存储费用？
```

---

### ✅ 第二步：生成RSA密钥对

**在本地Windows电脑上操作：**

```powershell
# 1. 打开PowerShell（以管理员身份）

# 2. 生成RSA私钥
openssl genrsa -out archive_private_key.pem 2048

# 3. 从私钥导出公钥
openssl rsa -in archive_private_key.pem -pubout -out archive_public_key.pem

# 4. 查看公钥内容（用于上传到企业微信）
Get-Content archive_public_key.pem
```

**如果没有openssl，先安装：**
```powershell
# 使用Chocolatey安装
choco install openssl

# 或直接下载：https://slproweb.com/products/Win32OpenSSL.html
```

**生成后的文件：**
- `archive_private_key.pem` - **私钥（保密，存服务器）**
- `archive_public_key.pem` - **公钥（上传到企业微信）**

---

### ✅ 第三步：填写申请表单

**页面位置：** 企业微信管理后台 → 管理工具 → 会话内容存档

#### 1. 选择版本
- ☑️ **企业版**（内部群聊、单聊）
- ⬜ 服务版（客户联系）

**原因：** 我们需要监控内部群聊的文件消息

---

#### 2. 设置升级范围
点击"设置升级范围"按钮：
- ☑️ 选择需要存档的部门/群聊
- **建议：** 先选择1-2个测试群，验证后再扩展

---

#### 3. 设置接收消息服务器 ☑️

**服务器URL：**
```
https://104.238.213.119/wecom/archive-callback
```

**Token：** 自己生成一个随机字符串
```
建议格式：Archive_Token_2024_随机字符
例如：Archive_Token_2024_Kx9mP2qL
```

**EncodingAESKey：** 点击"随机生成"

**⚠️ 重要：** 先不要保存，等服务器代码部署后再验证！

---

#### 4. 设置可信IP地址 ☑️

**IP地址：**
```
104.238.213.119
```

**说明：** 这是Kamatera服务器IP，限制只有这个IP能调用存档API

---

#### 5. 设置消息加密公钥 ☑️

**公钥内容：**
```
复制 archive_public_key.pem 的全部内容
（从 "-----BEGIN PUBLIC KEY-----" 到 "-----END PUBLIC KEY-----"）
```

**示例：**
```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA...
（中间内容省略）
...QIDAQAB
-----END PUBLIC KEY-----
```

---

## 提交信息汇总

**在提交申请前，整理以下信息发给我：**

```markdown
# 会话存档配置信息

## 1. 费用确认
- 月费用：¥ _____
- 计费方式：____________
- 试用期：有/无，___天

## 2. 接收消息配置
- Token: Archive_Token_2024_Kx9mP2qL
- EncodingAESKey: ________________________（企微生成）

## 3. 公钥
已生成，文件位置：
- 私钥：C:\path\to\archive_private_key.pem
- 公钥：已上传到企业微信

## 4. 其他
- CorpId: ww________________（企业ID）
- Secret: __________________（会话存档的Secret，申请后获得）
```

---

## 开发实施计划

**收到你的配置信息后，我将：**

### 第1天（6小时）：Python SDK封装
```
✓ 使用ctypes封装C SDK
✓ 实现Init、GetChatData、DecryptData、GetMediaData
✓ 单元测试
```

### 第2天（8小时）：集成到wecom-callback
```
✓ 实现 /wecom/archive-callback 端点
✓ 消息解密和验证
✓ 文件自动下载和上传七牛
✓ 保存到chat_files表
✓ 集成测试
```

**总工作量：** 14小时（约2天）

---

## 部署所需的服务器配置

```bash
# 需要添加到 /etc/wecom-callback/wecom_env.sh

# 会话存档配置
export ARCHIVE_CORPID="ww你的企业ID"
export ARCHIVE_SECRET="你的会话存档Secret"
export ARCHIVE_RSA_PRIVATE_KEY_PATH="/opt/wecom-callback/keys/archive_private_key.pem"

# 回调验证
export ARCHIVE_TOKEN="Archive_Token_2024_Kx9mP2qL"
export ARCHIVE_AES_KEY="企微生成的EncodingAESKey"
```

**私钥上传到服务器：**
```bash
# 在本地PowerShell执行
scp -i $env:USERPROFILE\.ssh\kamatera archive_private_key.pem root@104.238.213.119:/opt/wecom-callback/keys/
```

---

## 验证测试计划

**部署完成后：**

### 测试1：回调验证
1. 在企业微信后台点击"保存"
2. 企微会发送验证请求到服务器
3. 检查是否显示"配置成功"

### 测试2：消息接收
1. 在测试群发送一条文本消息
2. 查看服务器日志，确认收到消息
3. 检查能否正确解密

### 测试3：文件处理
1. 在测试群发送PDF文件
2. 等待3秒
3. 发送 "@gemini 分析这个PDF"
4. 检查Gemini是否成功读取文件

**预期日志：**
```
[ARCHIVE] Received message: type=file, filename=test.pdf
[ARCHIVE] Downloaded file from WeCom: 1024 bytes
[ARCHIVE] Uploaded to Qiniu: http://...
[ARCHIVE] Saved to DB: msg_id=xxx, chat_id=yyy
[AIBOT_CTX] Found file from archive: test.pdf
```

---

## 费用评估参考

**行业参考（仅供参考，以实际报价为准）：**

| 方案 | 预估费用 | 说明 |
|------|---------|------|
| 基础版 | ¥200-500/月 | 少量用户和消息 |
| 标准版 | ¥500-2000/月 | 中等规模 |
| 企业版 | ¥2000+/月 | 大规模或定制 |

**成本效益分析：**
- ✅ 解决群聊文件访问的**唯一方案**
- ✅ 提升用户体验（无需Quote，自动关联）
- ✅ 为未来功能打基础（审计、合规、知识库）
- ⚠️ 需要持续费用

**建议：**
- 先申请试用（如果有）
- 或选择最小套餐测试1个月
- 验证效果后再扩大范围

---

## 常见问题

### Q1: 会话存档会保存所有消息吗？
A: 是的，但我们的代码只会处理文件类型消息，其他消息会忽略。

### Q2: 历史消息能获取吗？
A: 企业微信存档通常保留30-90天，可以拉取历史消息。

### Q3: 隐私问题？
A: 文件会上传到七牛云，消息文本不会保存（除非你明确配置）。

### Q4: 影响性能吗？
A: 会话存档是异步推送，不影响企微正常使用。服务器处理是后台任务。

---

## 下一步行动

**你需要做：**
1. ☐ 咨询企业微信了解费用（最重要！）
2. ☐ 确认费用可接受
3. ☐ 生成RSA密钥对（按上面步骤）
4. ☐ 填写申请表单（先不保存）
5. ☐ 把配置信息发给我

**我需要做：**
1. ⏳ 等待你的配置信息
2. ⏳ 开发Python SDK封装（第1天）
3. ⏳ 实现archive-callback端点（第2天）
4. ⏳ 部署并协助你完成验证

---

**准备好了就开始咨询费用吧！** 🚀

有任何问题随时问我。
