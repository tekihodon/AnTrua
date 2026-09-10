# Ăn Trưa BSV

![Version](https://img.shields.io/badge/version-v1.0.0-blue)

Hệ thống quản lý tiền ăn trưa BSV.

## Docker

```bash
docker run --rm -p 5000:5000 \
  -e DATABASE_URL=postgresql://user:password@host:5432/database \
  -e ADMIN_PASS=change-me \
  tekihodon/antrua:latest
```
