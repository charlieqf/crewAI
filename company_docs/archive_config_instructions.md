# 企业微信会话存档配置说明

## 配置位置
企业微信管理后台 → **管理工具** → **会话内容存档**

---

## 配置项 1: 设置接收事件服务器

### URL（服务器地址）
```
http://104.238.213.119:8000/wecom/archive-callback
```
**说明：** 这是我们的服务器接收企业微信推送消息的地址，请完整复制粘贴。

---

### Token（令牌）
```
Archive_Token_2026_Secure
```
**说明：** 
- 这是用于验证请求的密钥
- 请完整复制粘贴这个值
- **重要：填写后请把这个值告诉技术人员**

---

### EncodingAESKey（消息加密密钥）
**操作：** 点击输入框右边的"**随机生成**"按钮

**说明：**
- 不要手动输入
- 点击按钮后会自动生成一个43字符的随机字符串
- **重要：生成后请复制这个值并告诉技术人员**

---

## 配置项 2: 设置可信IP地址

### IP地址
```
104.238.213.119
```
**说明：** 这是我们服务器的IP地址，请完整复制粘贴。

---

## 配置项 3: 设置消息加密公钥

### 公钥内容
```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqyE/j7EHIX6UWjePQPzi
GXj/Iq9gFd+JIdrjG4QOiY/lyDcc1NYj/7eBP1Hepde6eLj4Wv9GazVBBRjGAs5P
GYKDy0HEBgzshwzleQPzVTmLW1Mj4Yjc+5VpAlRjLWXyUmHZP83369liXWBE59wi
yM9pRI/2qWeHL2TB18hIsGiNQJV/sJ07LExoJMJ45fyXwnWOmBJHzkAT60pg5lMH
BY+BYc6Ig2OUMIxPMjJIxS2ve6G4xEQcHkGX+IdrP25aKizQb3s84s+c1+mbeDf7
Id1bbubKT8WALT+Y+o+CalvC03x465NzsskqOMLJeS64gvNaALhY5FklHxeQMwqU
YQIDAQAB
-----END PUBLIC KEY-----
```
**说明：** 
- 请完整复制粘贴，包括开头的 `-----BEGIN PUBLIC KEY-----` 和结尾的 `-----END PUBLIC KEY-----`
- 如果提示格式错误，尝试只复制中间的字母数字部分（不含BEGIN和END行）

---

## ⚠️ 重要提醒

### 填写完成后的操作：

1. **先不要点击"保存"按钮！**
2. **请把以下信息发给技术人员：**
   ```
   Token: Archive_Token_2026_Secure
   EncodingAESKey: （刚才点击"随机生成"后显示的43字符）
   ```
3. **等待技术人员确认配置完成**
4. **技术人员确认后，再点击"保存"进行验证**

### 为什么要等？
技术人员需要先在服务器上配置这些密钥，配置完成后你点击"保存"，企业微信才能成功验证服务器连接。

---

## 快速检查清单

- [ ] URL已填写：`http://104.238.213.119:8000/wecom/archive-callback`
- [ ] Token已填写：`Archive_Token_2026_Secure`
- [ ] EncodingAESKey已点击"随机生成"并记录
- [ ] 可信IP已填写：`104.238.213.119`
- [ ] 公钥已完整粘贴（包含BEGIN/END）
- [ ] 已将Token和AESKey发送给技术人员
- [ ] **尚未点击"保存"按钮**

---

## 遇到问题？

**如果公钥提示格式错误：**
只复制粘贴中间的字母数字部分（不含BEGIN和END那两行）：
```
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqyE/j7EHIX6UWjePQPzi
GXj/Iq9gFd+JIdrjG4QOiY/lyDcc1NYj/7eBP1Hepde6eLj4Wv9GazVBBRjGAs5P
GYKDy0HEBgzshwzleQPzVTmLW1Mj4Yjc+5VpAlRjLWXyUmHZP83369liXWBE59wi
yM9pRI/2qWeHL2TB18hIsGiNQJV/sJ07LExoJMJ45fyXwnWOmBJHzkAT60pg5lMH
BY+BYc6Ig2OUMIxPMjJIxS2ve6G4xEQcHkGX+IdrP25aKizQb3s84s+c1+mbeDf7
Id1bbubKT8WALT+Y+o+CalvC03x465NzsskqOMLJeS64gvNaALhY5FklHxeQMwqU
YQIDAQAB
```

**其他问题：**
联系技术人员协助

---

**配置完成时间：** 约5分钟  
**联系人：** Charlie（技术负责人）
