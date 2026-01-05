# RSA公钥 - 会话存档加密

## 公钥内容

**复制以下全部内容到企业微信后台：**

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

**生成时间：** 2026-01-04  
**算法：** RSA 2048位
