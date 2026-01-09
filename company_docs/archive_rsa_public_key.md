# RSA公钥 - 会话存档加密

## 公钥内容

**复制以下全部内容到企业微信后台：**

```
-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmKlDi1w1y7SJOQCNO24P
aGUyulxubrZDFqdksTkGL0GclDl886bOgmwF4VBQrU3cErXkWDdsH0YFj3MLfAAm
pqww//rjg5AN/is0fHjTfK5AJzm1xljJVJmyJYIjGUWtptRKISTA6sI1wHtAHtd4
0R2Pwg365MnpQQYRRZrdZdF2RK+gTpxr7IGl505wpr4TfSz+M1897vBXpXlNzSZu
v5lOQF9Yb4J4KSj2ylCgJIr4LZ6BYbV8L4Fh3e/pjw0KmfFgMq4UpJnYDZnIHCAm
1ZxTC3pTtaYZbD5MW+hn/pbkp5j2RZ5PYmWBjD8TDaxv5cG43Z8N8uEWBbtPChhb
bwIDAQAB
-----END PUBLIC KEY-----
```

## 私钥位置

- **服务器路径：** `/opt/wecom-callback/keys/archive_private_key.pem`
- **权限：** root:root 600
- **状态：** ✅ 已生成并保存

## 使用位置

**企业微信管理后台：**
1. 管理工具 → 会话内容存档
2. 勾选"设置消息加密公钥"
3. 粘贴上面的公钥内容
4. 保存

---

**生成时间：** 2026-01-08 (重新生成)
**算法：** RSA 2048位
